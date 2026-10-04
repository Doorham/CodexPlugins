// Althy · reviewed generic connector · Windows only
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

public class DriveSpec { public string letter; public string remote; public string lanRemote; }
public class ModuleConfig { public DriveSpec[] drives; public string defaultUser; }
public sealed class NasRemoteConnect : Form
{
    enum ConnectionMode { Auto, Lan, Tailscale }
    const string Installer = "tailscale-setup-1.102.4.exe";
    const string InstallerHash = "DC874BB9DB4A93E1E412F44ED629EC4B432AE24C7322F9D51D445B15A852A9E5";
    static readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    readonly TextBox output = new TextBox();
    readonly Button connect = new Button();
    readonly Button install = new Button();
    readonly Button check = new Button();
    readonly RadioButton automaticMode = new RadioButton();
    readonly RadioButton lanMode = new RadioButton();
    readonly RadioButton tailscaleMode = new RadioButton();
    readonly Label[] driveStates = new Label[4];
    readonly CancellationTokenSource cancel = new CancellationTokenSource();
    bool busy;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct Resource { public int scope, type, displayType, usage; public string local, remote, comment, provider; }
    [DllImport("mpr.dll", CharSet = CharSet.Unicode)] static extern int WNetGetConnection(string local, StringBuilder remote, ref int size);
    [DllImport("mpr.dll", CharSet = CharSet.Unicode)] static extern int WNetAddConnection2(ref Resource resource, string password, string user, int flags);
    [DllImport("mpr.dll", CharSet = CharSet.Unicode)] static extern int WNetCancelConnection2(string name, int flags, bool force);

    [DllImport("mpr.dll", CharSet = CharSet.Unicode, EntryPoint = "WNetAddConnection2W")] static extern int WNetAddSecure(ref Resource resource, IntPtr password, string user, int flags);

    [STAThread] public static void Main(string[] args)
    {
        try {
            if (args.Contains("--preview-credentials")) { PreviewCredentials(); return; }
            if (args.Contains("--preview-ui")) { PreviewUi(); return; }
            if (args.Contains("--self-test")) { SelfTest(); return; }
            RequireActivation();
            if (args.Contains("--check")) { WriteCheck(); return; }
            // Drive mappings must belong to the Explorer user's unelevated session.
            if (ShouldRelaunchUnelevated(new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator), UacEnabled())) {
                if (args.Contains("--unelevated")) throw new Exception("当前仍是管理员会话，请从普通桌面启动连接模块。");
                Type shellType = Type.GetTypeFromProgID("Shell.Application");
                object shell = Activator.CreateInstance(shellType);
                shellType.InvokeMember("ShellExecute", System.Reflection.BindingFlags.InvokeMethod, null, shell,
                    new object[] { Application.ExecutablePath, (args.Contains("--connect") ? "--connect " : "") + "--unelevated", Root, "open", 1 });
                Marshal.FinalReleaseComObject(shell);
                return;
            }
            using (var gate = new Mutex(false, "Local\\CompanyAIHelpers.NasRemoteConnect")) {
                if (!gate.WaitOne(0)) { MessageBox.Show("连接窗口已经打开，请切回该窗口。", "连接公司 NAS"); return; }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new NasRemoteConnect(args.Contains("--connect")));
                gate.ReleaseMutex();
            }
        } catch (Exception e) {
            if (args.Contains("--check") || args.Contains("--self-test")) {
                File.WriteAllText(Path.Combine(Root, "check-error.json"), Json.Serialize(new { error = e.Message }), new UTF8Encoding(false));
                Environment.ExitCode = 1;
            } else MessageBox.Show(e.Message, "连接公司 NAS", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    NasRemoteConnect(bool autoConnect, bool preview = false)
    {
        Text = "公司 NAS · 连接中心"; ClientSize = new Size(960, 650);
        MinimumSize = new Size(820, 580); StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 10); BackColor = Color.FromArgb(13, 18, 29); ForeColor = Color.FromArgb(235, 241, 250);
        var title = new Label { Text = "连接公司网络盘", AutoSize = true, Location = new Point(26, 25), Font = new Font(Font.FontFamily, 21, FontStyle.Bold), ForeColor = Color.White };
        var hint = new Label { Text = "先查看每个盘的映射入口，再选择本次连接方式。已有映射不会被悄悄切换。", AutoSize = true, Location = new Point(28, 74), ForeColor = Color.FromArgb(153, 168, 190) };
        var modeTitle = new Label { Text = "本次连接方式", AutoSize = true, Location = new Point(28, 117), Font = new Font(Font.FontFamily, 10, FontStyle.Bold) };
        var modeBar = new TableLayoutPanel { Location = new Point(26, 145), Size = new Size(908, 55), Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
            ColumnCount = 3, RowCount = 1, BackColor = Color.FromArgb(24, 32, 48), Padding = new Padding(5) };
        modeBar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 34));
        modeBar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33));
        modeBar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33));
        ConfigureMode(automaticMode, "自动 · 优先局域网");
        ConfigureMode(lanMode, "只用局域网");
        ConfigureMode(tailscaleMode, "只用 Tailscale");
        modeBar.Controls.Add(automaticMode, 0, 0); modeBar.Controls.Add(lanMode, 1, 0); modeBar.Controls.Add(tailscaleMode, 2, 0);
        automaticMode.Checked = true;
        var modeHint = new Label { Text = "自动模式保留已连接通道，只为缺失盘符选择可达地址。", AutoSize = true, Location = new Point(28, 211), ForeColor = Color.FromArgb(153, 168, 190) };
        automaticMode.CheckedChanged += delegate { if (automaticMode.Checked) modeHint.Text = "自动模式保留已连接通道，只为缺失盘符选择可达地址。"; };
        lanMode.CheckedChanged += delegate { if (lanMode.Checked) modeHint.Text = "只用局域网：已有 Tailscale 映射需要确认后才能切换。"; };
        tailscaleMode.CheckedChanged += delegate { if (tailscaleMode.Checked) modeHint.Text = "只用 Tailscale 地址；同网时底层仍可能直连，要测试外网请离开局域网。"; };
        var driveTitle = new Label { Text = "当前盘符与映射入口", AutoSize = true, Location = new Point(28, 247), Font = new Font(Font.FontFamily, 10, FontStyle.Bold) };
        var driveGrid = new TableLayoutPanel { Location = new Point(22, 274), Size = new Size(916, 81), Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
            ColumnCount = 4, RowCount = 1 };
        foreach (string letter in new[] { "W", "X", "Y", "Z" }) {
            int index = letter[0] - 'W'; driveGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 25));
            var card = new Panel { Dock = DockStyle.Fill, Margin = new Padding(4), BackColor = Color.FromArgb(25, 34, 51) };
            card.Controls.Add(new Label { Text = letter + ":", Location = new Point(14, 11), AutoSize = true, Font = new Font(Font.FontFamily, 13, FontStyle.Bold), ForeColor = Color.White });
            driveStates[index] = new Label { Text = "正在检查", Location = new Point(14, 43), AutoSize = true, ForeColor = Color.FromArgb(155, 169, 188) };
            card.Controls.Add(driveStates[index]); driveGrid.Controls.Add(card, index, 0);
        }
        connect.Text = "按所选通道连接"; connect.SetBounds(26, 370, 210, 43);
        install.Text = "安装 Tailscale"; install.SetBounds(248, 370, 188, 43);
        check.Text = "刷新状态"; check.SetBounds(448, 370, 145, 43);
        StyleButton(connect, true); StyleButton(install, false); StyleButton(check, false);
        var activity = new Label { Text = "操作记录", AutoSize = true, Location = new Point(28, 432), Font = new Font(Font.FontFamily, 10, FontStyle.Bold) };
        output.Multiline = true; output.ReadOnly = true; output.ScrollBars = ScrollBars.Vertical;
        output.SetBounds(26, 463, 908, 160); output.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        output.BackColor = Color.FromArgb(20, 28, 43); output.ForeColor = Color.FromArgb(205, 217, 233); output.BorderStyle = BorderStyle.None;
        output.Font = new Font("Microsoft YaHei UI", 9);
        Controls.AddRange(new Control[] { title, hint, modeTitle, modeBar, modeHint, driveTitle, driveGrid, connect, install, check, activity, output });
        connect.Click += async delegate { await RunAsync(false, false); };
        install.Click += async delegate { await RunAsync(true, false); };
        check.Click += async delegate { await RunAsync(false, true); };
        FormClosing += delegate(object sender, FormClosingEventArgs e) {
            if (busy) { e.Cancel = true; Log("操作进行中，请等待结束；安装程序不会被强制中止。"); }
        };
        Shown += async delegate { if (preview) return; Log("先选择通道再连接；刷新状态不会修改盘符。"); if (autoConnect) await RunAsync(false, false); else await RunAsync(false, true); };
    }

    static void ConfigureMode(RadioButton button, string label)
    {
        button.Text = label; button.Dock = DockStyle.Fill; button.Margin = new Padding(2);
        button.Appearance = Appearance.Button; button.FlatStyle = FlatStyle.Flat;
        button.FlatAppearance.BorderSize = 0; button.TextAlign = ContentAlignment.MiddleCenter;
        button.BackColor = Color.FromArgb(24, 32, 48); button.ForeColor = Color.FromArgb(180, 194, 212);
        button.CheckedChanged += delegate { button.BackColor = button.Checked ? Color.FromArgb(62, 91, 181) : Color.FromArgb(24, 32, 48); button.ForeColor = button.Checked ? Color.White : Color.FromArgb(180, 194, 212); };
    }
    static void StyleButton(Button button, bool primary)
    {
        button.FlatStyle = FlatStyle.Flat; button.FlatAppearance.BorderSize = 0;
        button.BackColor = primary ? Color.FromArgb(84, 113, 237) : Color.FromArgb(35, 47, 68);
        button.ForeColor = Color.White; button.Font = new Font("Microsoft YaHei UI", 9, FontStyle.Bold);
        button.Cursor = Cursors.Hand;
    }
    ConnectionMode SelectedMode() { return tailscaleMode.Checked ? ConnectionMode.Tailscale : lanMode.Checked ? ConnectionMode.Lan : ConnectionMode.Auto; }

    void Log(string line)
    {
        if (IsDisposed) return;
        if (InvokeRequired) { BeginInvoke(new Action<string>(Log), line); return; }
        output.AppendText(line + Environment.NewLine);
    }

    async Task RunAsync(bool installOnly, bool checkOnly)
    {
        if (busy) return;
        ConnectionMode mode = SelectedMode();
        busy = true; connect.Enabled = install.Enabled = check.Enabled = false;
        automaticMode.Enabled = lanMode.Enabled = tailscaleMode.Enabled = false;
        try {
            await Task.Run(delegate {
                var drives = LoadDrives();
                if (checkOnly) { Check(drives); UpdateDriveCards(drives); return; }
                if (installOnly) { EnsureInstalled(); Log("Tailscale 已安装；选择通道后点击“按所选通道连接”。"); UpdateDriveCards(drives); return; }
                var current = CurrentMappings(drives);
                var selected = SelectConnectionDrives(drives, current, Reachable, mode);
                var changes = selected.Where(d => !SameRemote(current[d.letter], d.remote)).ToArray();
                foreach (var d in drives) Log(d.letter + ": 当前" + RouteName(d, current[d.letter]) + "，本次选择" + RouteName(d, selected.Single(s => s.letter == d.letter).remote) + "。");
                if (changes.Length == 0) { CheckExisting(drives); Log("现有盘符已符合所选通道，没有断开或新建映射。"); UpdateDriveCards(drives); return; }
                int switches = changes.Count(d => current[d.letter] != null);
                if (switches > 0) {
                    bool approved = (bool)Invoke(new Func<bool>(delegate {
                        return MessageBox.Show(this, "将切换 " + switches + " 个已有盘符到所选通道。打开的文件可能中断；若文件正在使用，切换会停止，不会强制断开。是否继续？",
                            "确认切换连接通道", MessageBoxButtons.YesNo, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) == DialogResult.Yes;
                    }));
                    if (!approved) { Log("已取消：现有映射保持不变。"); return; }
                }
                if (NeedsRemoteAccess(drives, selected, current)) { EnsureInstalled(); EnsureLogin(); }
                else Log("所选新连接使用局域网地址，无需 Tailscale 授权。");
                foreach (string host in changes.Select(d => Host(d.remote)).Distinct()) {
                    if (!Reachable(host)) throw new Exception("NAS " + host + " 的文件共享暂不可达。请核对网络、NAS 在线状态及当前账号的授权。");
                    Log("NAS " + host + " 文件共享可达。");
                }
                // Collect all affected NAS accounts before changing any mapping, even with cached SMB credentials.
                bool confirmed = WithConfirmedCredentials(delegate { return (CredentialSet)Invoke(new Func<CredentialSet>(delegate {
                    using (var dialog = new CredentialDialog(changes.Select(d => Host(d.remote)).Distinct().ToArray(), LoadDefaultUser())) {
                        if (dialog.ShowDialog(this) != DialogResult.OK) return null;
                        return dialog.ExportCredentials();
                    }
                })); }, delegate(CredentialSet credentials) {
                    RequireActivation();
                    var fresh = CurrentMappings(drives); Plan(drives, fresh);
                    if (drives.Any(d => !SameRemote(current[d.letter], fresh[d.letter]))) throw new Exception("等待确认期间盘符发生变化，请刷新后重试；本次没有修改映射。");
                    ApplyChanges(changes, current, credentials);
                });
                if (!confirmed) { Log("已取消，未建立任何新映射。"); return; }
                bool complete = CheckExisting(drives);
                Log(complete ? "完成：四个盘都能打开，资源管理器中可直接使用。" : "部分检查未通过，请查看以上结果。");
                UpdateDriveCards(drives);
            });
        } catch (Exception e) { Log("未完成：" + e.Message); }
        finally {
            try { UpdateDriveCards(LoadDrives()); } catch (Exception) { }
            busy = false; connect.Enabled = install.Enabled = check.Enabled = true;
            automaticMode.Enabled = lanMode.Enabled = tailscaleMode.Enabled = true;
        }
    }

    void ApplyChanges(DriveSpec[] changes, IDictionary<string, string> original, CredentialSet credentials)
    {
        var completed = new List<DriveSpec>();
        try {
            foreach (var target in changes) {
                string prior = original[target.letter];
                if (prior != null) {
                    int removed = WNetCancelConnection2(target.letter + ":", 1, false);
                    if (removed != 0) throw new Exception(target.letter + ": 原映射正在使用或无法断开（" + removed + "）；未强制关闭文件。");
                }
                var resource = new Resource { type = 1, local = target.letter + ":", remote = target.remote };
                int result = credentials.Map(Host(target.remote), ref resource);
                if (result != 0) {
                    if (prior != null) RestorePrior(target, prior, credentials);
                    throw new Exception(target.letter + ": 新映射失败（" + result + "）：" + new Win32Exception(result).Message);
                }
                completed.Add(target);
                Log(target.letter + ": 已通过" + RouteName(target, target.remote) + "建立映射。");
            }
        } catch {
            foreach (var target in completed.AsEnumerable().Reverse()) {
                int removed = WNetCancelConnection2(target.letter + ":", 1, false);
                if (removed != 0) { Log(target.letter + ": 回退前无法断开新映射，请人工检查。"); continue; }
                if (original[target.letter] != null) RestorePrior(target, original[target.letter], credentials);
            }
            throw;
        }
    }
    void RestorePrior(DriveSpec target, string prior, CredentialSet credentials)
    {
        var old = new Resource { type = 1, local = target.letter + ":", remote = prior };
        int restored = credentials.Map(Host(target.remote), ref old);
        Log(restored == 0 ? target.letter + ": 已恢复原映射。" : target.letter + ": 原映射恢复失败（" + restored + "），请人工检查。");
    }
    void UpdateDriveCards(DriveSpec[] drives)
    {
        var states = drives.Select(d => {
            try { return RouteName(d, CurrentRemote(d.letter)); }
            catch (Exception) { return "状态未知"; }
        }).ToArray();
        if (IsDisposed) return;
        if (InvokeRequired) { BeginInvoke(new Action(delegate { SetDriveCards(states); })); return; }
        SetDriveCards(states);
    }
    void SetDriveCards(string[] states)
    {
        for (int i = 0; i < driveStates.Length; i++) {
            driveStates[i].Text = states[i];
            driveStates[i].ForeColor = states[i] == "局域网" ? Color.FromArgb(105, 220, 180)
                : states[i] == "Tailscale 地址" ? Color.FromArgb(141, 179, 255) : Color.FromArgb(176, 185, 201);
        }
    }

    bool CheckExisting(DriveSpec[] drives)
    {
        bool complete = true;
        foreach (var d in drives) {
            try { using (var items = Directory.EnumerateFileSystemEntries(d.letter + @":\").GetEnumerator()) { items.MoveNext(); } Log(d.letter + ": " + RouteName(d, CurrentRemote(d.letter)) + " · 可以打开。"); }
            catch (Exception) { complete = false; Log(d.letter + ": 已映射，但打开失败，请检查 NAS 文件权限或连接状态。"); }
        }
        return complete;
    }

    static bool UacEnabled()
    {
        using (var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System")) {
            return key == null || Convert.ToInt32(key.GetValue("EnableLUA", 1)) != 0;
        }
    }
    static bool ShouldRelaunchUnelevated(bool administrator, bool uacEnabled) { return administrator && uacEnabled; }

    static string LoadDefaultUser()
    {
        return Json.Deserialize<ModuleConfig>(File.ReadAllText(Path.Combine(Root, "nas-drives.json"), Encoding.UTF8)).defaultUser ?? "";
    }
    static void RequireActivation()
    {
        string stateRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "CompanyAIHelpers", "CodexTools", "CompanyAccess");
        byte[] sealedRecord = File.ReadAllBytes(Path.Combine(stateRoot, "activation.dpapi"));
        byte[] plain = ProtectedData.Unprotect(sealedRecord, null, DataProtectionScope.CurrentUser);
        Dictionary<string, object> record;
        try { record = Json.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(plain)); }
        finally { Array.Clear(plain, 0, plain.Length); }
        if (Convert.ToString(record["companyId"]) != "wanling-media" || Convert.ToString(record["format"]) != "local-guide/v1")
            throw new Exception("公司模块未启用，请让 Codex 导入公司提供的引导文件。");
        string payloadId = Convert.ToString(record["payloadId"]);
        if (!Regex.IsMatch(payloadId, "^[a-f0-9]{32}$")) throw new Exception("公司激活记录无效。");
        string expectedRoot = Path.GetFullPath(Path.Combine(stateRoot, "payloads", payloadId)).TrimEnd(Path.DirectorySeparatorChar);
        if (!string.Equals(expectedRoot, Path.GetFullPath(Root).TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
            throw new Exception("请使用已激活的公司模块入口。");
        var files = (Dictionary<string, object>)record["files"];
        foreach (string name in new[] { "NasRemoteConnect.exe", "nas-drives.json" }) {
            using (var hash = SHA256.Create()) using (var file = File.OpenRead(Path.Combine(Root, name))) {
                string digest = BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "");
                if (!string.Equals(digest, Convert.ToString(files[name]), StringComparison.OrdinalIgnoreCase)) throw new Exception("公司模块校验失败。");
            }
        }
    }
    static bool WithConfirmedCredentials(Func<CredentialSet> request, Action<CredentialSet> map)
    {
        using (var credentials = request()) {
            if (credentials == null) return false;
            map(credentials);
            return true;
        }
    }
    static void CredentialWorkflowTest()
    {
        var steps = new List<string>();
        if (WithConfirmedCredentials(delegate { steps.Add("cancel"); return null; }, delegate { steps.Add("map"); })) throw new Exception("Cancellation was accepted");
        if (!steps.SequenceEqual(new[] { "cancel" })) throw new Exception("Mapping occurred after cancellation");
        steps.Clear();
        if (!WithConfirmedCredentials(delegate { steps.Add("both-confirmed"); return new CredentialSet(); }, delegate { steps.Add("map"); })) throw new Exception("Confirmation was rejected");
        if (!steps.SequenceEqual(new[] { "both-confirmed", "map" })) throw new Exception("Credential/mapping order invalid");
        steps.Clear(); bool failed = false;
        try { WithConfirmedCredentials(delegate { steps.Add("prompt-failed"); throw new Exception("test"); }, delegate { steps.Add("map"); }); } catch { failed = true; }
        if (!failed || steps.Contains("map")) throw new Exception("Mapping occurred after prompt failure");
        using (var dialog = new CredentialDialog(new[] { "nas-one.example", "nas-two.example" }, "ExampleUser")) {
            if (dialog.CredentialsComplete()) throw new Exception("Empty passwords were accepted");
        }
    }
    sealed class CredentialSet : IDisposable
    {
        readonly Dictionary<string, Tuple<string, SecureString>> entries = new Dictionary<string, Tuple<string, SecureString>>();
        public void Add(string host, string user, SecureString password) { entries.Add(host, Tuple.Create(user, password)); }
        public int Map(string host, ref Resource resource)
        {
            var entry = entries[host];
            IntPtr pointer = Marshal.SecureStringToGlobalAllocUnicode(entry.Item2);
            try { return WNetAddSecure(ref resource, pointer, entry.Item1, 1); }
            finally { Marshal.ZeroFreeGlobalAllocUnicode(pointer); }
        }
        public void Dispose() { foreach (var entry in entries.Values) entry.Item2.Dispose(); entries.Clear(); }
    }
    sealed class CredentialDialog : Form
    {
        readonly string[] hosts;
        readonly TextBox[] users, passwords;
        public CredentialDialog(string[] servers, string defaultUser)
        {
            hosts = servers; users = new TextBox[hosts.Length]; passwords = new TextBox[hosts.Length];
            Text = "确认 NAS 登录信息"; ClientSize = new Size(590, 180 + hosts.Length * 114);
            StartPosition = FormStartPosition.CenterParent; FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false; Font = new Font("Microsoft YaHei UI", 10);
            BackColor = Color.FromArgb(13, 18, 29); ForeColor = Color.White;
            Controls.Add(new Label { Text = "确认本次连接的 NAS 账号", AutoSize = true, Location = new Point(25,23), Font = new Font(Font.FontFamily, 15, FontStyle.Bold), ForeColor = Color.White });
            Controls.Add(new Label { Text = "全部确认后才更改盘符；密码仅用于本次连接，不保存。", AutoSize = true, Location = new Point(27,58), ForeColor = Color.FromArgb(153,168,190) });
            for (int i = 0; i < hosts.Length; i++) {
                int y = 100 + i * 114;
                Controls.Add(new Label { Text = "NAS " + (i + 1) + " · " + hosts[i], AutoSize = true, Location = new Point(27,y), Font = new Font(Font.FontFamily, 10, FontStyle.Bold), ForeColor = Color.FromArgb(205,217,233) });
                Controls.Add(new Label { Text = "用户名", AutoSize = true, Location = new Point(27,y+39), ForeColor = Color.FromArgb(153,168,190) });
                Controls.Add(new Label { Text = "密码", AutoSize = true, Location = new Point(305,y+39), ForeColor = Color.FromArgb(153,168,190) });
                users[i] = new TextBox { Text = defaultUser, Location = new Point(88,y+34), Width = 185, BackColor = Color.FromArgb(28,39,58), ForeColor = Color.White, BorderStyle = BorderStyle.FixedSingle };
                passwords[i] = new TextBox { UseSystemPasswordChar = true, Location = new Point(352,y+34), Width = 206, BackColor = Color.FromArgb(28,39,58), ForeColor = Color.White, BorderStyle = BorderStyle.FixedSingle };
                Controls.Add(users[i]); Controls.Add(passwords[i]);
            }
            var confirm = new Button { Text = "确认并继续连接", Location = new Point(347,ClientSize.Height-58), Size = new Size(211,39) };
            var close = new Button { Text = "取消", DialogResult = DialogResult.Cancel, Location = new Point(238,ClientSize.Height-58), Size = new Size(97,39) };
            StyleButton(confirm, true); StyleButton(close, false);
            confirm.Click += delegate {
                if (!CredentialsComplete()) {
                    MessageBox.Show(this, "请分别填写每台 NAS 的用户名和密码。", Text, MessageBoxButtons.OK, MessageBoxIcon.Information); return;
                }
                DialogResult = DialogResult.OK;
            };
            Controls.Add(confirm); Controls.Add(close); AcceptButton = confirm; CancelButton = close;
        }
        public bool CredentialsComplete()
        {
            for (int i = 0; i < hosts.Length; i++) if (string.IsNullOrWhiteSpace(users[i].Text) || passwords[i].Text.Length == 0) return false;
            return true;
        }
        public CredentialSet ExportCredentials()
        {
            var result = new CredentialSet();
            for (int i = 0; i < hosts.Length; i++) {
                var secret = new SecureString();
                foreach (char c in passwords[i].Text) secret.AppendChar(c);
                secret.MakeReadOnly();
                result.Add(hosts[i], users[i].Text.Trim(), secret);
            }
            ClearPasswords();
            return result;
        }
        public void ClearPasswords() { foreach (var password in passwords) password.Clear(); }
        protected override void Dispose(bool disposing) { if (disposing) ClearPasswords(); base.Dispose(disposing); }
    }
    static void PreviewCredentials()
    {
        Application.EnableVisualStyles();
        using (var dialog = new CredentialDialog(new[] { "nas-one.example", "nas-two.example" }, "ExampleUser")) {
            dialog.Shown += delegate {
                using (var bitmap = new Bitmap(dialog.Width, dialog.Height)) {
                    dialog.DrawToBitmap(bitmap, new Rectangle(0, 0, dialog.Width, dialog.Height));
                    bitmap.Save(Path.Combine(Root, "credentials-preview.png"));
                }
                dialog.Close();
            };
            Application.Run(dialog);
        }
    }
    static void PreviewUi()
    {
        Application.EnableVisualStyles();
        using (var form = new NasRemoteConnect(false, true)) using (var bitmap = new Bitmap(form.Width, form.Height)) {
            form.Opacity = 0.01; form.Show(); Application.DoEvents();
            form.SetDriveCards(new[] { "局域网", "局域网", "Tailscale 地址", "未连接" });
            form.Log("W: 局域网 · 可以打开。");
            form.Log("X: 局域网 · 可以打开。");
            form.Log("Y: Tailscale 地址 · 可以打开。");
            form.Log("Z: 未连接；请选择本次连接方式。");
            form.DrawToBitmap(bitmap, new Rectangle(0, 0, form.Width, form.Height));
            bitmap.Save(Path.Combine(Root, "ui-preview.png"));
            form.Hide();
        }
    }
    static DriveSpec[] LoadDrives()
    {
        var config = Json.Deserialize<ModuleConfig>(File.ReadAllText(Path.Combine(Root, "nas-drives.json"), Encoding.UTF8));
        if (config == null || config.drives == null || config.drives.Length != 4) throw new Exception("四个盘的配置缺失。");
        if (!config.drives.Select(d => d.letter).OrderBy(s => s).SequenceEqual(new[] { "W", "X", "Y", "Z" })) throw new Exception("盘符配置必须为 W、X、Y、Z，且不能重复。");
        foreach (var d in config.drives) {
            if (!ValidRemote(d.remote)) throw new Exception("共享地址格式无效。");
            if (d.lanRemote != null && (!ValidRemote(d.lanRemote) || !string.Equals(Share(d.lanRemote), Share(d.remote), StringComparison.OrdinalIgnoreCase)))
                throw new Exception("局域网备用地址必须是同一共享的完整 UNC 路径。");
        }
        return config.drives;
    }
    static bool ValidRemote(string remote) { return Regex.IsMatch(remote ?? "", @"^\\\\[a-zA-Z0-9.-]+\\[^\\/:*?""<>|\r\n]+$"); }
    static string Share(string remote) { return remote.Substring(remote.LastIndexOf('\\') + 1); }
    static bool MappingMatches(DriveSpec drive, string actual)
    {
        return actual != null && new[] { drive.remote, drive.lanRemote }.Any(r => r != null && string.Equals(actual.TrimEnd('\\'), r.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase));
    }
    static DriveSpec[] SelectConnectionDrives(DriveSpec[] drives, IDictionary<string, string> current, Func<string, bool> reachable)
    {
        return SelectConnectionDrives(drives, current, reachable, ConnectionMode.Auto);
    }
    static DriveSpec[] SelectConnectionDrives(DriveSpec[] drives, IDictionary<string, string> current, Func<string, bool> reachable, ConnectionMode mode)
    {
        Plan(drives, current);
        return drives.Select(d => new DriveSpec { letter = d.letter,
            remote = mode == ConnectionMode.Tailscale ? d.remote
                : mode == ConnectionMode.Lan ? LanTarget(d)
                : current[d.letter] ?? (d.lanRemote != null && reachable(Host(d.lanRemote)) ? d.lanRemote : d.remote),
            lanRemote = d.lanRemote }).ToArray();
    }
    static string LanTarget(DriveSpec drive)
    {
        if (drive.lanRemote == null) throw new Exception(drive.letter + ": 尚未配置局域网地址，不能选择“只用局域网”。");
        return drive.lanRemote;
    }
    static bool NeedsRemoteAccess(DriveSpec[] drives, DriveSpec[] selected, IDictionary<string, string> current)
    {
        return selected.Any(s => !SameRemote(current[s.letter], s.remote) && string.Equals(s.remote, drives.Single(d => d.letter == s.letter).remote, StringComparison.OrdinalIgnoreCase));
    }
    static bool SameRemote(string left, string right) { return string.Equals((left ?? "").TrimEnd('\\'), (right ?? "").TrimEnd('\\'), StringComparison.OrdinalIgnoreCase); }
    static string RouteName(DriveSpec drive, string actual)
    {
        if (actual == null) return "未连接";
        if (drive.lanRemote != null && SameRemote(actual, drive.lanRemote)) return "局域网";
        if (SameRemote(actual, drive.remote)) return "Tailscale 地址";
        return "其他映射";
    }
    static string Host(string remote) { return remote.Substring(2).Split('\\')[0]; }
    static string CurrentRemote(string letter)
    {
        var buffer = new StringBuilder(32768); int size = buffer.Capacity;
        int result = WNetGetConnection(letter + ":", buffer, ref size);
        if (result == 0 || (result == 1201 && buffer.Length > 0)) return buffer.ToString();
        if (result == 2250 || result == 1200) {
            if (Directory.GetLogicalDrives().Any(d => d.StartsWith(letter + ":", StringComparison.OrdinalIgnoreCase))) return "（已被其他驱动器占用）";
            return null;
        }
        throw new Exception("无法检查 " + letter + ": 的已有映射（" + result + "）。");
    }
    static Dictionary<string, string> CurrentMappings(DriveSpec[] drives) { return drives.ToDictionary(d => d.letter, d => CurrentRemote(d.letter)); }
    static List<DriveSpec> Plan(DriveSpec[] drives, IDictionary<string, string> current)
    {
        var todo = new List<DriveSpec>(); var conflicts = new List<string>();
        foreach (var d in drives) {
            string remote = current[d.letter];
            if (remote == null) todo.Add(d);
            else if (!MappingMatches(d, remote)) conflicts.Add(d.letter + ": 已连接 " + remote);
        }
        if (conflicts.Count > 0) throw new Exception("发现未在公司文件中批准的映射，本次不会覆盖：" + string.Join("；", conflicts) + "。请先人工核对该盘符。");
        return todo;
    }
    static bool Reachable(string host)
    {
        using (var client = new TcpClient()) {
            try { var result = client.BeginConnect(host, 445, null, null); using (result.AsyncWaitHandle) { if (!result.AsyncWaitHandle.WaitOne(3500)) return false; } client.EndConnect(result); return true; }
            catch { return false; }
        }
    }
    static string Cli()
    {
        foreach (var root in new[] { Environment.GetEnvironmentVariable("ProgramW6432"), Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86) }) {
            if (!string.IsNullOrEmpty(root)) { string file = Path.Combine(root, "Tailscale", "tailscale.exe"); if (File.Exists(file)) return file; }
        }
        return null;
    }
    static string RunCli(string arguments)
    {
        using (var process = new Process { StartInfo = new ProcessStartInfo(Cli(), arguments) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true } }) {
            process.Start(); var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(15000)) { process.Kill(); throw new Exception("Tailscale 状态检查超时。"); }
            Task.WaitAll(stdout, stderr);
            if (process.ExitCode != 0) throw new Exception("Tailscale 命令未成功（" + process.ExitCode + "）；请检查服务是否运行。");
            return stdout.Result;
        }
    }
    static string BackendState()
    {
        // Parse only the connection state; do not persist user identities or raw status JSON.
        var status = Json.Deserialize<Dictionary<string, object>>(RunCli("status --json"));
        object state; return status.TryGetValue("BackendState", out state) ? Convert.ToString(state) : "Unknown";
    }
    void EnsureInstalled()
    {
        if (Cli() != null) { Log("Tailscale 已安装，沿用现有版本。"); return; }
        string package = Path.Combine(Root, Installer);
        if (!File.Exists(package)) {
            Log("正在从 Tailscale 官方网站下载 Windows 安装器。");
            string temporary = package + ".download";
            try {
                System.Net.ServicePointManager.SecurityProtocol = System.Net.SecurityProtocolType.Tls12;
                using (var client = new System.Net.WebClient()) client.DownloadFile("https://pkgs.tailscale.com/stable/" + Installer, temporary);
                using (var hash = SHA256.Create()) using (var file = File.OpenRead(temporary)) {
                    string actual = BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "");
                    if (!string.Equals(actual, InstallerHash, StringComparison.OrdinalIgnoreCase)) throw new Exception("官方安装器校验失败，未执行安装。");
                }
                File.Move(temporary, package);
            } finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        using (var hash = SHA256.Create()) using (var file = File.OpenRead(package)) {
            string actual = BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "");
            if (!string.Equals(actual, InstallerHash, StringComparison.OrdinalIgnoreCase)) throw new Exception("内置安装包校验失败，未执行安装。");
        }
        Log("正在运行官方 Windows 安装器；请确认 Windows 安装授权，客户端将自动联网下载。");
        using (var process = Process.Start(new ProcessStartInfo(package, "/install /quiet /norestart") { UseShellExecute = true, Verb = "runas", WindowStyle = ProcessWindowStyle.Hidden, WorkingDirectory = Root })) {
            if (process == null) throw new Exception("安装程序未启动。");
            process.WaitForExit();
            if (process.ExitCode != 0 && process.ExitCode != 3010) throw new Exception("Tailscale 安装失败（" + process.ExitCode + "）。");
        }
        if (Cli() == null) throw new Exception("安装结束，但未找到 Tailscale。请检查安装结果。");
        Log("Tailscale 安装完成。");
    }
    void EnsureLogin()
    {
        string state = BackendState();
        if (state == "Running") { Log("Tailscale 已连接，沿用现有授权。"); return; }
        Log("正在连接 Tailscale；需要授权时会打开官方登录页面，请选择 GitHub，并在 github.com 官方页面完成授权；工具箱不接收 GitHub 密码。登录后自动继续。");
        bool browserOpened = false; object guard = new object();
        using (var process = new Process { StartInfo = new ProcessStartInfo(Cli(), state == "Stopped" ? "up" : "login") { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true } }) {
            DataReceivedEventHandler received = delegate(object sender, DataReceivedEventArgs e) {
                if (e.Data == null) return;
                var match = Regex.Match(e.Data, @"https://login\.tailscale\.com/[a-zA-Z0-9/_?=.-]+");
                lock (guard) { if (!match.Success || browserOpened) return; browserOpened = true; }
                BeginInvoke(new Action(delegate { try { Process.Start(new ProcessStartInfo(match.Value) { UseShellExecute = true }); } catch { Log("登录页面未能打开，请从 Tailscale 托盘菜单登录。"); } }));
            };
            process.OutputDataReceived += received; process.ErrorDataReceived += received;
            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
            try {
                var deadline = DateTime.UtcNow.AddMinutes(3);
                while (DateTime.UtcNow < deadline) {
                    Thread.Sleep(2000);
                    if (BackendState() == "Running") { Log("Tailscale 授权完成，继续连接 NAS。"); return; }
                    if (process.HasExited && process.ExitCode != 0) throw new Exception("Tailscale 连接未完成；请从托盘菜单完成登录后重试。");
                }
                throw new Exception("等待登录超时。完成登录后再次点击连接即可。");
            } finally { if (!process.HasExited) process.Kill(); }
        }
    }
    void Check(DriveSpec[] drives)
    {
        try { Log(Cli() == null ? "Tailscale 尚未安装（不影响局域网连接）。" : "Tailscale：" + BackendState()); }
        catch (Exception) { Log("Tailscale 状态暂不可用，继续检查局域网和已有映射。"); }
        foreach (var host in drives.SelectMany(d => new[] { d.remote, d.lanRemote }).Where(r => r != null).Select(Host).Distinct()) Log("NAS " + host + (Reachable(host) ? "：文件共享可达。" : "：文件共享不可达。"));
        foreach (var d in drives) Log(d.letter + ": " + RouteName(d, CurrentRemote(d.letter)) + " · " + (CurrentRemote(d.letter) ?? "未映射"));
        Log("只读检查完成，没有安装、登录或更改映射。");
    }
    static void WriteCheck()
    {
        var drives = LoadDrives(); var data = new Dictionary<string, object>();
        data["installed"] = Cli() != null; data["backendState"] = Cli() == null ? "NotInstalled" : BackendState();
        var current = CurrentMappings(drives);
        data["mappings"] = current;
        data["mappingRoutes"] = drives.ToDictionary(d => d.letter, d => RouteName(d, current[d.letter]));
        data["uacEnabled"] = UacEnabled();
        data["mappingMatches"] = drives.ToDictionary(d => d.letter, d => MappingMatches(d, current[d.letter]));
        data["nasReachable"] = drives.SelectMany(d => new[] { d.remote, d.lanRemote }).Where(r => r != null).Select(Host).Distinct().ToDictionary(h => h, h => Reachable(h));
        try { data["newMappingsNeeded"] = Plan(drives, current).Count; } catch (Exception e) { data["mappingConflict"] = e.Message; }
        File.WriteAllText(Path.Combine(Root, "inspection.json"), Json.Serialize(data), new UTF8Encoding(false));
    }
    static void CompatibilityWorkflowTest()
    {
        if (ShouldRelaunchUnelevated(true, false) || ShouldRelaunchUnelevated(false, true) || !ShouldRelaunchUnelevated(true, true))
            throw new Exception("UAC compatibility failed");
        var drives = new[] { new DriveSpec { letter = "W", remote = @"\\remote.example\share", lanRemote = @"\\lan.example\share" } };
        var existing = new Dictionary<string, string> { { "W", @"\\LAN.example\SHARE" } };
        if (Plan(drives, existing).Count != 0 || SelectConnectionDrives(drives, existing, h => false)[0].remote != existing["W"])
            throw new Exception("Existing approved LAN mapping was changed");
        existing["W"] = @"\\unknown.example\share";
        bool refused = false; try { Plan(drives, existing); } catch { refused = true; }
        if (!refused) throw new Exception("Unknown server was accepted by share name");
        existing["W"] = null;
        var lan = SelectConnectionDrives(drives, existing, h => true);
        var remote = SelectConnectionDrives(drives, existing, h => false);
        if (lan[0].remote != drives[0].lanRemote || NeedsRemoteAccess(drives, lan, existing)
            || remote[0].remote != drives[0].remote || !NeedsRemoteAccess(drives, remote, existing))
            throw new Exception("LAN/remote selection failed");
        existing["W"] = drives[0].lanRemote;
        var forcedRemote = SelectConnectionDrives(drives, existing, h => true, ConnectionMode.Tailscale);
        if (forcedRemote[0].remote != drives[0].remote || !NeedsRemoteAccess(drives, forcedRemote, existing)
            || RouteName(drives[0], existing["W"]) != "局域网")
            throw new Exception("Forced Tailscale route or actual route reporting failed");
        existing["W"] = drives[0].remote;
        var forcedLan = SelectConnectionDrives(drives, existing, h => false, ConnectionMode.Lan);
        if (forcedLan[0].remote != drives[0].lanRemote || RouteName(drives[0], existing["W"]) != "Tailscale 地址")
            throw new Exception("Forced LAN route failed");
    }
    static void SelfTest()
    {
        var drives = LoadDrives();
        var empty = drives.ToDictionary(d => d.letter, d => (string)null);
        if (Plan(drives, empty).Count != 4) throw new Exception("Empty-machine plan failed");
        var same = drives.ToDictionary(d => d.letter, d => d.remote);
        if (Plan(drives, same).Count != 0) throw new Exception("Idempotent plan failed");
        same["X"] = null;
        if (Plan(drives, same).Count != 1) throw new Exception("Partial recovery failed");
        same["W"] = @"\\existing-server\existing-share";
        bool refused = false; try { Plan(drives, same); } catch { refused = true; }
        if (!refused) throw new Exception("Existing LAN mapping was not preserved");
        if (File.Exists(Path.Combine(Root, Installer))) using (var hash = SHA256.Create()) using (var file = File.OpenRead(Path.Combine(Root, Installer))) {
            if (BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "") != InstallerHash) throw new Exception("Installer integrity failed");
        }
        CredentialWorkflowTest();
        CompatibilityWorkflowTest();
        File.WriteAllText(Path.Combine(Root, "self-test.json"), "{\"passed\":14,\"mutatedMappings\":false}", new UTF8Encoding(false));
    }
}
