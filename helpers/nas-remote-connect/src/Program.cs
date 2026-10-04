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

public class DriveSpec { public string letter; public string remote; }
public class ModuleConfig { public DriveSpec[] drives; public string defaultUser; }
public sealed class NasRemoteConnect : Form
{
    const string Installer = "tailscale-setup-1.102.4.exe";
    const string InstallerHash = "DC874BB9DB4A93E1E412F44ED629EC4B432AE24C7322F9D51D445B15A852A9E5";
    static readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    readonly TextBox output = new TextBox();
    readonly Button connect = new Button();
    readonly Button install = new Button();
    readonly Button check = new Button();
    readonly CancellationTokenSource cancel = new CancellationTokenSource();
    bool busy;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct Resource { public int scope, type, displayType, usage; public string local, remote, comment, provider; }
    [DllImport("mpr.dll", CharSet = CharSet.Unicode)] static extern int WNetGetConnection(string local, StringBuilder remote, ref int size);
    [DllImport("mpr.dll", CharSet = CharSet.Unicode)] static extern int WNetAddConnection2(ref Resource resource, string password, string user, int flags);

    [DllImport("mpr.dll", CharSet = CharSet.Unicode, EntryPoint = "WNetAddConnection2W")] static extern int WNetAddSecure(ref Resource resource, IntPtr password, string user, int flags);

    [STAThread] public static void Main(string[] args)
    {
        try {
            if (args.Contains("--preview-credentials")) { PreviewCredentials(); return; }
            if (args.Contains("--self-test")) { SelfTest(); return; }
            RequireActivation();
            if (args.Contains("--check")) { WriteCheck(); return; }
            // Drive mappings must belong to the Explorer user's unelevated session.
            if (new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator)) {
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

    NasRemoteConnect(bool autoConnect)
    {
        Text = "连接公司 NAS · Althy · 1.0.2"; ClientSize = new Size(740, 440);
        MinimumSize = new Size(620, 400); StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 10); BackColor = Color.FromArgb(245, 247, 250);
        var title = new Label { Text = "安装 Tailscale，连接 W / X / Y / Z", AutoSize = true, Location = new Point(20, 18), Font = new Font(Font.FontFamily, 15, FontStyle.Bold) };
        var hint = new Label { Text = "首次可能需要确认 Windows 安装授权和 Tailscale 登录。已有映射将保留。", AutoSize = true, Location = new Point(22, 57) };
        connect.Text = "安装并连接四个盘"; connect.SetBounds(22, 94, 210, 40);
        install.Text = "只安装 Tailscale"; install.SetBounds(244, 94, 190, 40);
        check.Text = "检查连接"; check.SetBounds(446, 94, 140, 40);
        output.Multiline = true; output.ReadOnly = true; output.ScrollBars = ScrollBars.Vertical;
        output.SetBounds(22, 153, 696, 264); output.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        output.BackColor = Color.White; output.BorderStyle = BorderStyle.FixedSingle;
        Controls.AddRange(new Control[] { title, hint, connect, install, check, output });
        connect.Click += async delegate { await RunAsync(false, false); };
        install.Click += async delegate { await RunAsync(true, false); };
        check.Click += async delegate { await RunAsync(false, true); };
        FormClosing += delegate(object sender, FormClosingEventArgs e) {
            if (busy) { e.Cancel = true; Log("操作进行中，请等待结束；安装程序不会被强制中止。"); }
        };
        Shown += async delegate { Log("官方 Windows 安装器已内置（1.33 MB）；安装时仍需联网下载客户端。"); if (autoConnect) await RunAsync(false, false); };
    }

    void Log(string line)
    {
        if (IsDisposed) return;
        if (InvokeRequired) { BeginInvoke(new Action<string>(Log), line); return; }
        output.AppendText(line + Environment.NewLine);
    }

    async Task RunAsync(bool installOnly, bool checkOnly)
    {
        if (busy) return;
        busy = true; connect.Enabled = install.Enabled = check.Enabled = false;
        try {
            await Task.Run(delegate {
                var drives = LoadDrives();
                if (checkOnly) { Check(drives); return; }
                // Check every letter before changing any mapping. No disconnect/delete action exists.
                if (!installOnly) Plan(drives, CurrentMappings(drives));
                EnsureInstalled();
                if (installOnly) { Log("Tailscale 已安装。点击“安装并连接四个盘”继续。"); return; }
                EnsureLogin();
                foreach (string host in drives.Select(d => Host(d.remote)).Distinct()) {
                    if (!Reachable(host)) throw new Exception("NAS " + host + " 的文件共享暂不可达。请核对网络、NAS 在线状态及当前账号的授权。");
                    Log("NAS " + host + " 文件共享可达。");
                }
                // Re-check after login/installation, since mapping state may have changed meanwhile.
                var todo = Plan(drives, CurrentMappings(drives));
                // Always collect both NAS accounts before the first mapping, even with cached SMB credentials.
                bool confirmed = WithConfirmedCredentials(delegate { return (CredentialSet)Invoke(new Func<CredentialSet>(delegate {
                    using (var dialog = new CredentialDialog(drives.Select(d => Host(d.remote)).Distinct().ToArray(), LoadDefaultUser())) {
                        if (dialog.ShowDialog(this) != DialogResult.OK) return null;
                        return dialog.ExportCredentials();
                    }
                })); }, delegate(CredentialSet credentials) {
                    RequireActivation();
                    todo = Plan(drives, CurrentMappings(drives));
                    foreach (DriveSpec d in todo) {
                        var resource = new Resource { type = 1, local = d.letter + ":", remote = d.remote };
                        int result = credentials.Map(Host(d.remote), ref resource);
                        if (result != 0) throw new Exception(d.letter + ": 映射失败（" + result + "）：" + new Win32Exception(result).Message + "。已有成功映射已保留。");
                        Log(d.letter + ": 已建立持久映射。");
                    }
                });
                if (!confirmed) { Log("已取消，未建立任何新映射。"); return; }
                bool complete = true;
                foreach (var d in drives) {
                    try { using (var items = Directory.EnumerateFileSystemEntries(d.letter + @":\").GetEnumerator()) { items.MoveNext(); } Log(d.letter + ": 可以打开。"); }
                    catch (Exception) { complete = false; Log(d.letter + ": 已映射，但打开失败，请检查 NAS 文件权限或连接状态。"); }
                }
                Log(complete ? "完成：四个盘都能打开，资源管理器中可直接使用。" : "部分检查未通过，请查看以上结果。");
            });
        } catch (Exception e) { Log("未完成：" + e.Message); }
        finally { busy = false; connect.Enabled = install.Enabled = check.Enabled = true; }
    }

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
            Text = "确认 NAS 登录信息"; ClientSize = new Size(540, 170 + hosts.Length * 114);
            StartPosition = FormStartPosition.CenterParent; FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false; Font = new Font("Microsoft YaHei UI", 10); BackColor = Color.FromArgb(245,247,250);
            Controls.Add(new Label { Text = "Tailscale 已授权，请分别填写两台 NAS 的账号", AutoSize = true, Location = new Point(22,20) });
            Controls.Add(new Label { Text = "全部确认后才映射四个盘。密码仅用于本次连接，不保存。", AutoSize = true, Location = new Point(22,49) });
            for (int i = 0; i < hosts.Length; i++) {
                int y = 88 + i * 114;
                Controls.Add(new Label { Text = "NAS " + (i + 1) + " · " + hosts[i], AutoSize = true, Location = new Point(22,y) });
                Controls.Add(new Label { Text = "用户名", AutoSize = true, Location = new Point(22,y+37) });
                Controls.Add(new Label { Text = "密码", AutoSize = true, Location = new Point(281,y+37) });
                users[i] = new TextBox { Text = defaultUser, Location = new Point(84,y+32), Width = 170 };
                passwords[i] = new TextBox { UseSystemPasswordChar = true, Location = new Point(329,y+32), Width = 185 };
                Controls.Add(users[i]); Controls.Add(passwords[i]);
            }
            var confirm = new Button { Text = "确认并连接四个盘", Location = new Point(310,ClientSize.Height-59), Size = new Size(204,37) };
            var close = new Button { Text = "取消", DialogResult = DialogResult.Cancel, Location = new Point(202,ClientSize.Height-59), Size = new Size(96,37) };
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
    static DriveSpec[] LoadDrives()
    {
        var config = Json.Deserialize<ModuleConfig>(File.ReadAllText(Path.Combine(Root, "nas-drives.json"), Encoding.UTF8));
        if (config == null || config.drives == null || config.drives.Length != 4) throw new Exception("四个盘的配置缺失。");
        if (!config.drives.Select(d => d.letter).OrderBy(s => s).SequenceEqual(new[] { "W", "X", "Y", "Z" })) throw new Exception("盘符配置必须为 W、X、Y、Z，且不能重复。");
        foreach (var d in config.drives) if (!Regex.IsMatch(d.remote ?? "", @"^\\\\[a-zA-Z0-9.-]+\\[^\\/:*?""<>|\r\n]+$")) throw new Exception("共享地址格式无效。");
        return config.drives;
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
            else if (!string.Equals(remote.TrimEnd('\\'), d.remote.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase)) conflicts.Add(d.letter + ": 已连接 " + remote);
        }
        if (conflicts.Count > 0) throw new Exception("为保留现有映射，本次未更改任何盘符：" + string.Join("；", conflicts) + "。可在尚未映射这些盘符的目标电脑使用此模块。");
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
        Log(Cli() == null ? "Tailscale 尚未安装。" : "Tailscale：" + BackendState());
        foreach (var host in drives.Select(d => Host(d.remote)).Distinct()) Log("NAS " + host + (Reachable(host) ? "：文件共享可达。" : "：文件共享不可达。"));
        foreach (var d in drives) Log(d.letter + ": " + (CurrentRemote(d.letter) ?? "未映射"));
        Log("只读检查完成，没有安装、登录或更改映射。");
    }
    static void WriteCheck()
    {
        var drives = LoadDrives(); var data = new Dictionary<string, object>();
        data["installed"] = Cli() != null; data["backendState"] = Cli() == null ? "NotInstalled" : BackendState();
        data["mappings"] = CurrentMappings(drives);
        data["nasReachable"] = drives.Select(d => Host(d.remote)).Distinct().ToDictionary(h => h, h => Reachable(h));
        try { data["newMappingsNeeded"] = Plan(drives, CurrentMappings(drives)).Count; } catch (Exception e) { data["mappingConflict"] = e.Message; }
        File.WriteAllText(Path.Combine(Root, "inspection.json"), Json.Serialize(data), new UTF8Encoding(false));
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
        using (var hash = SHA256.Create()) using (var file = File.OpenRead(Path.Combine(Root, Installer))) {
            if (BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "") != InstallerHash) throw new Exception("Installer integrity failed");
        }
        CredentialWorkflowTest();
        File.WriteAllText(Path.Combine(Root, "self-test.json"), "{\"passed\":9,\"mutatedMappings\":false}", new UTF8Encoding(false));
    }
}
