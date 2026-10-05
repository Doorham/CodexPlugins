// Althy · reviewed generic connector · Windows only
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Net.Sockets;
using System.Net.NetworkInformation;
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

// Doorham: exact NAS addresses in the same Local Intranet list as Internet Options.
public static class NasSiteTrust
{
    [ComImport, Guid("79EAC9EE-BAF9-11CE-8C82-00AA004BA90B"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface SecurityManager
    {
        [PreserveSig] int SetSecuritySite(IntPtr site);
        [PreserveSig] int GetSecuritySite(out IntPtr site);
        [PreserveSig] int MapUrlToZone([MarshalAs(UnmanagedType.LPWStr)] string url, out int zone, int flags);
        [PreserveSig] int GetSecurityId(IntPtr url, IntPtr id, ref int size, IntPtr reserved);
        [PreserveSig] int ProcessUrlAction(IntPtr url, int action, IntPtr policy, int size, IntPtr context, int contextSize, int flags, int reserved);
        [PreserveSig] int QueryCustomPolicy(IntPtr url, IntPtr key, out IntPtr policy, out int size, IntPtr context, int contextSize, int reserved);
        [PreserveSig] int SetZoneMapping(int zone, [MarshalAs(UnmanagedType.LPWStr)] string pattern, int flags);
        [PreserveSig] int GetZoneMappings(int zone, out System.Runtime.InteropServices.ComTypes.IEnumString patterns, int flags);
    }
    [DllImport("wininet.dll", SetLastError = true)] static extern bool InternetSetOption(IntPtr handle, int option, IntPtr buffer, int length);
    public sealed class State
    {
        public string remote, host, reason;
        public int uncZone, httpZone, httpsZone;
        public bool listed;
        public bool trusted { get { return listed && Trusted(uncZone) && Trusted(httpZone) && Trusted(httpsZone); } }
        public bool canAdd { get { return !trusted && string.IsNullOrEmpty(reason) && Eligible(uncZone) && Eligible(httpZone) && Eligible(httpsZone); } }
    }
    static SecurityManager CreateManager()
    {
        return (SecurityManager)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("7B8A2D94-0AC9-11D1-896C-00C04FB6BFC4")));
    }
    static bool Trusted(int zone) { return zone == 1 || zone == 2; }
    static bool Eligible(int zone) { return Trusted(zone) || zone == 3; }
    public static string ZoneName(int zone)
    {
        switch (zone) { case 0: return "本机区域"; case 1: return "本地 Intranet"; case 2: return "受信任站点"; case 3: return "Internet 区域"; case 4: return "受限制站点"; default: return "未知区域"; }
    }
    public static string Host(string remote)
    {
        if (!Regex.IsMatch(remote ?? "", @"^\\\\[a-zA-Z0-9.-]+\\[^\\/:*?""<>|\r\n]+$")) throw new Exception("文件共享地址格式无效。");
        string host = remote.Split('\\')[2].ToLowerInvariant();
        if (host.Length > 253 || host.Split('.').Any(p => p.Length == 0 || p.Length > 63 || p.StartsWith("-") || p.EndsWith("-")))
            throw new Exception("NAS 地址格式无效，不能添加信任。");
        System.Net.IPAddress ip;
        if (System.Net.IPAddress.TryParse(host, out ip) && ip.ToString() != host) throw new Exception("NAS 的 IP 地址必须使用标准写法。");
        return host;
    }
    public static string Pattern(string remote) { return "*://" + Host(remote); }
    static string CanonicalPattern(string pattern)
    {
        string text = (pattern ?? "").Replace('\\', '/').ToLowerInvariant().TrimEnd('/');
        // Windows enumerates all-protocol entries as bare addresses, as shown in Internet Options.
        return text.Contains("://") ? text : "*://" + text;
    }
    public static bool SamePattern(string first, string second) { return CanonicalPattern(first) == CanonicalPattern(second); }
    static int Zone(SecurityManager manager, string address, int flags)
    {
        int zone; int result = manager.MapUrlToZone(address, out zone, flags);
        if (result != 0) throw new Exception("Windows 站点信任检查失败（" + result.ToString("X8") + "）。");
        return zone;
    }
    static string ManagedReason()
    {
        foreach (var hive in new[] { Registry.CurrentUser, Registry.LocalMachine }) {
            const string policy = @"Software\Policies\Microsoft\Windows\CurrentVersion\Internet Settings";
            using (var key = hive.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Internet Settings")) {
                if (key != null && Convert.ToInt32(key.GetValue("Security_HKLM_only", 0)) != 0) return "安全区域仅允许系统级管理，请联系管理员。";
            }
            using (var key = hive.OpenSubKey(policy)) {
                if (key != null && (Convert.ToInt32(key.GetValue("Security_HKLM_only", 0)) != 0 || Convert.ToInt32(key.GetValue("Security_Zones_Map_Edit", 0)) != 0))
                    return "安全区域由系统策略管理，请联系管理员。";
            }
            foreach (string suffix in new[] { @"\ZoneMapKey", @"\ZoneMap" }) using (var key = hive.OpenSubKey(policy + suffix)) {
                if (key != null && (key.ValueCount != 0 || key.SubKeyCount != 0)) return "安全区域由系统策略管理，请联系管理员。";
            }
        }
        return null;
    }
    static string[] Mappings(SecurityManager manager, int zone)
    {
        System.Runtime.InteropServices.ComTypes.IEnumString entries;
        int result = manager.GetZoneMappings(zone, out entries, 0);
        if (result < 0) throw new Exception("无法检查现有站点信任条目。");
        if (entries == null) return new string[0];
        try {
            var items = new List<string>(); var item = new string[1];
            while (entries.Next(1, item, IntPtr.Zero) == 0) { if (items.Count >= 10000) throw new Exception("信任条目过多，请由管理员检查。"); items.Add(item[0]); }
            return items.ToArray();
        } finally { Marshal.FinalReleaseComObject(entries); }
    }
    public static bool Applies(string pattern, string host)
    {
        string text = CanonicalPattern(pattern);
        int separator = text.IndexOf("://", StringComparison.Ordinal);
        if (separator < 0) return false;
        string target = text.Substring(separator + 3).Trim('/');
        if (target == host || target == "*") return true;
        if (target.StartsWith("*.") && (host == target.Substring(2) || host.EndsWith(target.Substring(1), StringComparison.Ordinal))) return true;
        byte[] address;
        System.Net.IPAddress parsed;
        if (!System.Net.IPAddress.TryParse(host, out parsed) || (address = parsed.GetAddressBytes()).Length != 4) return false;
        string[] pieces = target.Split('.');
        if (pieces.Length != 4) return false;
        for (int i = 0; i < 4; i++) {
            if (pieces[i] == "*") continue;
            string[] range = pieces[i].Split('-'); int low, high;
            if (!int.TryParse(range[0], out low) || !int.TryParse(range[range.Length - 1], out high) || range.Length > 2 || address[i] < low || address[i] > high) return false;
        }
        return true;
    }
    public static State Inspect(string remote)
    {
        string host = Host(remote); var manager = CreateManager();
        try {
            // Require the address-level list entry and check the effective SMB and web zones.
            // No file content, saved MOTW or NAS permissions are changed.
            var state = new State { remote = remote, host = host,
                uncZone = Zone(manager, remote + @"\", 0x1003),
                httpZone = Zone(manager, "http://" + host + "/", 0x1000),
                httpsZone = Zone(manager, "https://" + host + "/", 0x1000),
                listed = Mappings(manager, 1).Any(p => CanonicalPattern(p) == Pattern(remote)) };
            if (state.trusted) return state;
            state.reason = ManagedReason();
            if (!Eligible(state.uncZone) || !Eligible(state.httpZone) || !Eligible(state.httpsZone)) state.reason = "当前区域受限制或无法确认，保留现有设置。";
            foreach (int zone in new[] { 0, 3, 4 }) {
                if (Mappings(manager, zone).Any(p => Applies(p, host))) state.reason = "已有明确的区域规则，保留现有设置，请人工核对。";
            }
            if (state.listed) state.reason = "地址已在本地 Intranet 列表中，但部分区域判定未生效；请人工核对。";
            return state;
        } finally { Marshal.FinalReleaseComObject(manager); }
    }
    static void NotifySettings()
    {
        InternetSetOption(IntPtr.Zero, 39, IntPtr.Zero, 0);
        InternetSetOption(IntPtr.Zero, 37, IntPtr.Zero, 0);
    }
    // Only remove rules successfully added by this transaction, never a prior mapping.
    public static void ApplyTransaction(string[] patterns, Action backup, Action<string> add, Func<bool> verify, Action<string> remove)
    {
        backup(); var created = new List<string>();
        try {
            foreach (string pattern in patterns) { add(pattern); created.Add(pattern); }
            if (!verify()) throw new Exception("本地 Intranet 地址条目未通过复检，撤回本次添加。");
        } catch (Exception failure) {
            bool rollbackFailed = false;
            foreach (string pattern in created.AsEnumerable().Reverse()) { try { remove(pattern); } catch { rollbackFailed = true; } }
            if (rollbackFailed) throw new Exception(failure.Message + " 部分新增条目无法撤回，请根据本机备份人工核对。");
            throw;
        }
    }
    public static string Add(State[] approved)
    {
        if (approved.Length == 0 || approved.Any(s => !s.canAdd)) throw new Exception("没有可确认添加的 NAS 站点信任条目。");
        foreach (var state in approved) if (!Inspect(state.remote).canAdd) throw new Exception("等待确认期间信任设置发生变化，请重新检查。");
        string[] patterns = approved.Select(s => Pattern(s.remote)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        string directory = Path.Combine(NasRemoteConnect.ModuleStateRoot, "TrustBackups");
        string backup = Path.Combine(directory, "intranet-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N") + ".dpapi");
        var manager = CreateManager();
        try {
            ApplyTransaction(patterns, delegate {
                Directory.CreateDirectory(directory);
                byte[] record = Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(new { format = "codextools-nas-intranet-additions/v1", createdUtc = DateTime.UtcNow, zone = 1, patterns = patterns,
                    previousLocations = approved.Select(s => new { remote = s.remote, listed = s.listed, uncZone = s.uncZone, httpZone = s.httpZone, httpsZone = s.httpsZone }).ToArray() }));
                try { using (var file = new FileStream(backup, FileMode.CreateNew, FileAccess.Write)) {
                    byte[] sealedRecord = ProtectedData.Protect(record, null, DataProtectionScope.CurrentUser); file.Write(sealedRecord, 0, sealedRecord.Length);
                } } finally { Array.Clear(record, 0, record.Length); }
            }, delegate(string pattern) {
                if (ManagedReason() != null) throw new Exception("安全区域策略发生变化，本次停止添加。");
                for (int zone = 0; zone <= 4; zone++) if (Mappings(manager, zone).Any(p => CanonicalPattern(p) == pattern))
                    throw new Exception("已有相同地址的区域条目，本次没有覆盖。");
                int result = manager.SetZoneMapping(1, pattern, 0); // SZM_CREATE; all protocols, exact NAS host only.
                if (result != 0) throw new Exception("Windows 拒绝添加站点信任（" + result.ToString("X8") + "），现有条目保留。");
                NotifySettings();
            }, delegate { return approved.All(s => Inspect(s.remote).trusted); }, delegate(string pattern) {
                if (!Mappings(manager, 1).Any(p => CanonicalPattern(p) == pattern))
                    throw new Exception("新增规则已发生变化，保留供人工检查。");
                int result = manager.SetZoneMapping(1, pattern, 1); // SZM_DELETE of this transaction's exact pattern.
                if (result != 0) throw new Exception("撤回新增规则失败。");
                NotifySettings();
            });
            return backup;
        } finally { Marshal.FinalReleaseComObject(manager); }
    }
}

public class DriveSpec { public string letter; public string remote; public string lanRemote; }
public class ModuleConfig { public DriveSpec[] drives; public string defaultUser; }
public sealed class NasRemoteConnect : Form
{
    enum ConnectionMode { Lan, Tailscale }
    const string Installer = "tailscale-setup-1.102.4.exe";
    const string InstallerHash = "DC874BB9DB4A93E1E412F44ED629EC4B432AE24C7322F9D51D445B15A852A9E5";
    static readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    const string SavedRestoreRunName = "CompanyAIHelpers.NasSavedMappings";
    static readonly string SavedRestoreWakeName = "Local\\CompanyAIHelpers.NasSavedMappings.Wake." + WindowsIdentity.GetCurrent().User.Value;
    static readonly string StateRoot = ResolveStateRoot();
    public static string ModuleStateRoot { get { return StateRoot; } }
    readonly TextBox output = new TextBox();
    readonly Button connect = new DarkButton();
    readonly Button install = new DarkButton();
    readonly Button check = new DarkButton();
    readonly Button remember = new DarkButton();
    readonly RadioButton lanMode = new DarkChoice();
    readonly RadioButton tailscaleMode = new DarkChoice();
    readonly Label[] driveStates = new Label[4];
    readonly CancellationTokenSource cancel = new CancellationTokenSource();
    bool busy;

    static void PaintDarkControl(Control control, PaintEventArgs e, bool hovered, bool focused)
    {
        Color background = control.Enabled ? control.BackColor : Color.FromArgb(29, 39, 57);
        if (control.Enabled && hovered) background = ControlPaint.Light(background, 0.12f);
        Color foreground = control.Enabled ? control.ForeColor : Color.FromArgb(157, 171, 192);
        e.Graphics.Clear(control.Parent == null ? Color.FromArgb(13, 18, 29) : control.Parent.BackColor);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        var bounds = new Rectangle(1, 1, control.Width - 3, control.Height - 3);
        int diameter = Math.Min(16, bounds.Height);
        using (var shape = new GraphicsPath()) {
            shape.AddArc(bounds.Left, bounds.Top, diameter, diameter, 180, 90);
            shape.AddArc(bounds.Right - diameter, bounds.Top, diameter, diameter, 270, 90);
            shape.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
            shape.AddArc(bounds.Left, bounds.Bottom - diameter, diameter, diameter, 90, 90);
            shape.CloseFigure();
            using (var fill = new SolidBrush(background)) e.Graphics.FillPath(fill, shape);
            if (focused && control.Enabled) using (var border = new Pen(Color.FromArgb(148, 176, 255), 2)) e.Graphics.DrawPath(border, shape);
        }
        TextRenderer.DrawText(e.Graphics, control.Text, control.Font, bounds, foreground,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
    }
    sealed class DarkButton : Button
    {
        bool hovered;
        public DarkButton() { SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true); UseVisualStyleBackColor = false; }
        protected override void OnPaint(PaintEventArgs e) { PaintDarkControl(this, e, hovered, Focused && ShowFocusCues); }
        protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); hovered = true; Invalidate(); }
        protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); hovered = false; Invalidate(); }
    }
    sealed class DarkChoice : RadioButton
    {
        bool hovered;
        public DarkChoice() { SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true); UseVisualStyleBackColor = false; }
        protected override void OnPaint(PaintEventArgs e) { PaintDarkControl(this, e, hovered, Focused && ShowFocusCues); }
        protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); hovered = true; Invalidate(); }
        protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); hovered = false; Invalidate(); }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct Resource { public int scope, type, displayType, usage; public string local, remote, comment, provider; }
    [DllImport("mpr.dll", CharSet = CharSet.Unicode)] static extern int WNetGetConnection(string local, StringBuilder remote, ref int size);
    [DllImport("mpr.dll", CharSet = CharSet.Unicode)] static extern int WNetAddConnection2(ref Resource resource, string password, string user, int flags);
    [DllImport("mpr.dll", CharSet = CharSet.Unicode)] static extern int WNetCancelConnection2(string name, int flags, bool force);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern uint GetFileAttributes(string path);

    [DllImport("mpr.dll", CharSet = CharSet.Unicode, EntryPoint = "WNetAddConnection2W")] static extern int WNetAddSecure(ref Resource resource, IntPtr password, string user, int flags);
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

    static void ApplyWindowTheme(Form form)
    {
        if (!form.IsHandleCreated || SystemInformation.HighContrast) return;
        try {
            int dark = 1, rounded = 2;
            int caption = ColorTranslator.ToWin32(form.BackColor);
            int text = ColorTranslator.ToWin32(Color.FromArgb(235, 241, 250));
            int border = ColorTranslator.ToWin32(Color.FromArgb(39, 51, 72));
            // Native Windows 11 caption styling keeps resize, Snap and accessibility intact.
            DwmSetWindowAttribute(form.Handle, 20, ref dark, sizeof(int));
            DwmSetWindowAttribute(form.Handle, 33, ref rounded, sizeof(int));
            DwmSetWindowAttribute(form.Handle, 34, ref border, sizeof(int));
            DwmSetWindowAttribute(form.Handle, 35, ref caption, sizeof(int));
            DwmSetWindowAttribute(form.Handle, 36, ref text, sizeof(int));
        } catch (DllNotFoundException) { } catch (EntryPointNotFoundException) { }
        // Unsupported attributes leave the OS frame usable on older Windows versions.
    }
    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e); ApplyWindowTheme(this);
    }
    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if (message.Msg == 0x031A) ApplyWindowTheme(this); // WM_THEMECHANGED
    }

    [STAThread] public static void Main(string[] args)
    {
        bool savedRestore = args.Contains("--restore-saved") || args.Contains("--restore-saved-once") || args.Contains("--enable-saved-restore");
        try {
            if (args.Contains("--preview-credentials")) { PreviewCredentials(); return; }
            if (args.Contains("--preview-trust")) { PreviewSiteTrust(); return; }
            if (args.Contains("--preview-window")) { PreviewUi(true); return; }
            if (args.Contains("--preview-ui")) { PreviewUi(); return; }
            if (args.Contains("--self-test")) { SelfTest(); return; }
            // An old, retained startup payload follows the current validated activation.
            // This reads only our activation/config hashes, never Windows credentials.
            if (savedRestore) {
                string activeRoot = VerifiedActivationRoot();
                if (!SameLocalPath(activeRoot, Root)) {
                    Process.Start(new ProcessStartInfo(Path.Combine(activeRoot, "NasRemoteConnect.exe"), SavedRestoreArguments(args)) {
                        UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden
                    });
                    return;
                }
            }
            RequireActivation();
            if (args.Contains("--check")) { WriteCheck(); return; }
            // Drive mappings must belong to the Explorer user's unelevated session.
            if (ShouldRelaunchUnelevated(new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator), UacEnabled())) {
                if (args.Contains("--unelevated")) throw new Exception("当前仍是管理员会话，请从普通桌面启动连接模块。");
                Type shellType = Type.GetTypeFromProgID("Shell.Application");
                object shell = Activator.CreateInstance(shellType);
                shellType.InvokeMember("ShellExecute", System.Reflection.BindingFlags.InvokeMethod, null, shell,
                    new object[] { Application.ExecutablePath, savedRestore ? SavedRestoreArguments(args) + " --unelevated" : "--unelevated", Root, "open", savedRestore ? 0 : 1 });
                Marshal.FinalReleaseComObject(shell);
                return;
            }
            if (savedRestore) {
                if (args.Contains("--enable-saved-restore")) ConfigureSavedRestore();
                using (var restoreGate = new Mutex(false, "Local\\CompanyAIHelpers.NasSavedMappingRestore")) {
                    if (!restoreGate.WaitOne(0)) return;
                    try { RunSavedRestore(args.Contains("--restore-saved-once") || args.Contains("--enable-saved-restore")); }
                    finally { restoreGate.ReleaseMutex(); }
                }
                return;
            }
            using (var gate = new Mutex(false, "Local\\CompanyAIHelpers.NasRemoteConnect")) {
                if (!gate.WaitOne(0)) { MessageBox.Show("连接窗口已经打开，请切回该窗口。", "连接公司 NAS"); return; }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new NasRemoteConnect());
                gate.ReleaseMutex();
            }
        } catch (Exception e) {
            if (savedRestore) {
                WriteSavedRestoreStatus(new Dictionary<string, int>(), false, e.GetType().Name);
                Environment.ExitCode = 1;
            } else if (args.Contains("--check") || args.Contains("--self-test")) {
                File.WriteAllText(Path.Combine(Root, "check-error.json"), Json.Serialize(new { error = e.Message }), new UTF8Encoding(false));
                Environment.ExitCode = 1;
            } else MessageBox.Show(e.Message, "连接公司 NAS", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    NasRemoteConnect(bool preview = false)
    {
        Text = "公司 NAS · 连接中心"; ClientSize = new Size(960, 650);
        ShowIcon = false; DoubleBuffered = true;
        MinimumSize = new Size(820, 580); StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 10); BackColor = Color.FromArgb(13, 18, 29); ForeColor = Color.FromArgb(235, 241, 250);
        var title = new Label { Text = "连接公司网络盘", AutoSize = true, Location = new Point(26, 25), Font = new Font(Font.FontFamily, 21, FontStyle.Bold), ForeColor = Color.White };
        var hint = new Label { Text = "先查看每个盘的映射入口，再选择本次连接方式。已有映射不会被悄悄切换。", AutoSize = true, Location = new Point(28, 74), ForeColor = Color.FromArgb(153, 168, 190) };
        var modeTitle = new Label { Text = "本次连接方式", AutoSize = true, Location = new Point(28, 117), Font = new Font(Font.FontFamily, 10, FontStyle.Bold) };
        var modeBar = new TableLayoutPanel { Location = new Point(26, 145), Size = new Size(908, 55), Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
            ColumnCount = 2, RowCount = 1, BackColor = Color.FromArgb(24, 32, 48), Padding = new Padding(5) };
        modeBar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        modeBar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        ConfigureMode(lanMode, "只用局域网");
        ConfigureMode(tailscaleMode, "只用 Tailscale");
        modeBar.Controls.Add(lanMode, 0, 0); modeBar.Controls.Add(tailscaleMode, 1, 0);
        var modeHint = new Label { Text = "必须先选一种连接方式；查看状态不会连接或切换盘符。", AutoSize = true, Location = new Point(28, 211), ForeColor = Color.FromArgb(153, 168, 190) };
        lanMode.CheckedChanged += delegate { if (lanMode.Checked) modeHint.Text = "局域网地址：已有 Tailscale 映射需确认后才能切换。"; if (!busy) connect.Enabled = remember.Enabled = SelectedMode().HasValue; };
        tailscaleMode.CheckedChanged += delegate { if (tailscaleMode.Checked) modeHint.Text = "Tailscale 地址：即使身处局域网也使用此入口；切换已有盘符需确认。"; if (!busy) connect.Enabled = remember.Enabled = SelectedMode().HasValue; };
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
        remember.Text = "记住 NAS 登录"; remember.SetBounds(605, 370, 190, 43);
        StyleButton(connect, true); StyleButton(install, false); StyleButton(check, false); StyleButton(remember, false);
        connect.Enabled = remember.Enabled = false;
        var activity = new Label { Text = "操作记录", AutoSize = true, Location = new Point(28, 432), Font = new Font(Font.FontFamily, 10, FontStyle.Bold) };
        output.Multiline = true; output.ReadOnly = true; output.ScrollBars = ScrollBars.Vertical;
        output.SetBounds(26, 463, 908, 160); output.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        output.BackColor = Color.FromArgb(20, 28, 43); output.ForeColor = Color.FromArgb(205, 217, 233); output.BorderStyle = BorderStyle.None;
        output.Font = new Font("Microsoft YaHei UI", 9);
        Controls.AddRange(new Control[] { title, hint, modeTitle, modeBar, modeHint, driveTitle, driveGrid, connect, install, check, remember, activity, output });
        connect.Click += async delegate { if (!preview) await RunAsync(false, false); };
        install.Click += async delegate { if (!preview) await RunAsync(true, false); };
        check.Click += async delegate { if (!preview) await RunAsync(false, true); };
        remember.Click += async delegate { if (!preview) await RunAsync(false, false, true); };
        FormClosing += delegate(object sender, FormClosingEventArgs e) {
            if (busy) { e.Cancel = true; Log("操作进行中，请等待结束；安装程序不会被强制中止。"); }
        };
        Shown += async delegate { if (preview) return; Log("先选择局域网或 Tailscale；查看状态不会连接或切换盘符。"); await RunAsync(false, true); };
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
    ConnectionMode? SelectedMode() { return tailscaleMode.Checked ? ConnectionMode.Tailscale : lanMode.Checked ? ConnectionMode.Lan : (ConnectionMode?)null; }

    void Log(string line)
    {
        if (IsDisposed) return;
        if (InvokeRequired) { BeginInvoke(new Action<string>(Log), line); return; }
        output.AppendText(line + Environment.NewLine);
    }

    async Task RunAsync(bool installOnly, bool checkOnly, bool rememberOnly = false)
    {
        if (busy) return;
        ConnectionMode? mode = SelectedMode();
        if (!installOnly && !checkOnly && !mode.HasValue) { Log("请先明确选择局域网或 Tailscale。"); return; }
        busy = true; connect.Enabled = install.Enabled = check.Enabled = remember.Enabled = false;
        lanMode.Enabled = tailscaleMode.Enabled = false;
        try {
            await Task.Run(delegate {
                var drives = LoadDrives();
                if (checkOnly) { Check(drives); UpdateDriveCards(drives); return; }
                if (installOnly) { EnsureInstalled(); Log("Tailscale 已安装；选择通道后点击“按所选通道连接”。"); UpdateDriveCards(drives); return; }
                var current = CurrentMappings(drives);
                var selected = SelectConnectionDrives(drives, current, mode.Value);
                var changes = selected.Where(d => !SameRemote(current[d.letter], d.remote)).ToArray();
                foreach (var d in drives) Log(d.letter + ": 当前" + RouteName(d, current[d.letter]) + "，本次选择" + RouteName(d, selected.Single(s => s.letter == d.letter).remote) + "。");
                int switches = changes.Count(d => current[d.letter] != null);
                if (!rememberOnly && switches > 0) {
                    bool approved = (bool)Invoke(new Func<bool>(delegate {
                        return MessageBox.Show(this, "将切换 " + switches + " 个已有盘符到所选通道。打开的文件可能中断；若文件正在使用，切换会停止，不会强制断开。是否继续？",
                            "确认切换连接通道", MessageBoxButtons.YesNo, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) == DialogResult.Yes;
                    }));
                    if (!approved) { Log("已取消：现有映射保持不变。"); return; }
                }
                if (mode.Value == ConnectionMode.Tailscale) {
                    ConnectionStage("1/4 · 检查 Tailscale 安装"); EnsureInstalled();
                    ConnectionStage("2/4 · 检查 Tailscale 登录"); EnsureLogin();
                }
                else Log("所选新连接使用局域网地址，无需 Tailscale 授权。");
                foreach (string host in selected.Select(d => Host(d.remote)).Distinct()) {
                    if (!Reachable(host)) throw new Exception("NAS " + host + " 的文件共享暂不可达。请核对网络、NAS 在线状态及当前账号的授权。");
                    Log("NAS " + host + " 文件共享可达。");
                }
                if (rememberOnly) {
                    bool saved = WithConfirmedCredentials(delegate { return (CredentialSet)Invoke(new Func<CredentialSet>(delegate {
                        using (var dialog = new CredentialDialog(selected.Select(d => Host(d.remote)).Distinct().ToArray(), LoadDefaultUser(), 0, true)) {
                            if (dialog.ShowDialog(this) != DialogResult.OK) return null;
                            return dialog.ExportCredentials();
                        }
                    })); }, delegate(CredentialSet credentials) {
                        RequireActivation();
                        AuthenticateAndRemember(selected, credentials, delegate(DriveSpec target) {
                            var resource = new Resource { type = 1, remote = target.remote };
                            return credentials.Map(Host(target.remote), ref resource, 0);
                        }, credentials.Save, Log);
                        EnableRememberedRestore(credentials);
                    });
                    Log(saved ? "登录验证完成；现有盘符和连接通道保持不变。" : "已取消：没有保存登录或更改映射。");
                    return;
                }
                ConnectionStage((mode.Value == ConnectionMode.Tailscale ? "3/4" : "1/2") + " · 检查网络站点信任");
                EnsureSiteTrust(selected);
                RequireActivation();
                RestoreRememberedPass(selected, PersistedRemote, CurrentRemote, DriveReadError, Reachable, MapUsingWindowsLogin, Log);
                current = CurrentMappings(drives);
                ConnectionStage((mode.Value == ConnectionMode.Tailscale ? "4/4" : "2/2") + " · 确认 NAS 连接");
                changes = ConnectionWork(drives, selected, current, delegate(DriveSpec drive) {
                    int error = DriveReadError(drive);
                    if (error != 0) Log(drive.letter + ": 旧映射无法打开（" + error + "）· " + NasError(error) + " 需要重新确认 NAS 账号。");
                    return error;
                });
                if (changes.Length == 0) { SignalSavedRestore(); CheckExisting(drives); Log("现有盘符已符合所选通道且可打开，没有断开或新建映射。"); UpdateDriveCards(drives); return; }
                int repairs = changes.Count(d => SameRemote(current[d.letter], d.remote));
                if (repairs > 0) Log("需要恢复 " + repairs + " 个失效映射：先确认并验证 NAS 账号，再重建对应盘符；不会强制断开正在使用的文件。");
                // Only failed saved-login recovery, new mappings or explicit route switches need a password dialog.
                bool confirmed = WithConfirmedCredentials(delegate { return (CredentialSet)Invoke(new Func<CredentialSet>(delegate {
                    using (var dialog = new CredentialDialog(changes.Select(d => Host(d.remote)).Distinct().ToArray(), LoadDefaultUser(), repairs)) {
                        if (dialog.ShowDialog(this) != DialogResult.OK) return null;
                        return dialog.ExportCredentials();
                    }
                })); }, delegate(CredentialSet credentials) {
                    RequireActivation();
                    var fresh = CurrentMappings(drives); Plan(drives, fresh);
                    if (drives.Any(d => !SameRemote(current[d.letter], fresh[d.letter]))) throw new Exception("等待确认期间盘符发生变化，请刷新后重试；本次没有修改映射。");
                    AuthenticateAndRemember(changes, credentials, delegate(DriveSpec target) {
                        var resource = new Resource { type = 1, remote = target.remote };
                        int result = credentials.Map(Host(target.remote), ref resource, 0);
                        if (result == 0) Log("NAS " + Host(target.remote) + " 账号验证通过。");
                        return result;
                    }, credentials.Save, Log);
                    EnableRememberedRestore(credentials);
                    var afterLogin = CurrentMappings(drives); Plan(drives, afterLogin);
                    if (drives.Any(d => !SameRemote(current[d.letter], afterLogin[d.letter]))) throw new Exception("验证账号期间盘符入口发生变化，已停止重建，请刷新后重试。");
                    // Authentication can restore a remembered drive by itself. Recheck only the
                    // targets the user approved; never disturb mappings which have recovered.
                    var remaining = ConnectionWork(drives, changes, afterLogin, DriveReadError);
                    if (remaining.Length == 0) Log("NAS 登录已恢复原映射，保持现有盘符与通道，没有断开或重建。");
                    else ApplyChanges(remaining, afterLogin, credentials);
                });
                if (!confirmed) { Log("已取消，未建立任何新映射。"); return; }
                bool complete = CheckExisting(drives);
                Log(complete ? "完成：四个盘都能打开，资源管理器中可直接使用。" : "部分检查未通过，请查看以上结果。");
                UpdateDriveCards(drives);
            });
        } catch (OperationCanceledException) { Log("已取消：尚未建立新的 NAS 映射，可再次点击连接继续。"); }
        catch (Exception e) { Log("未完成：" + e.Message); }
        finally {
            try { UpdateDriveCards(LoadDrives()); } catch (Exception) { }
            busy = false; install.Enabled = check.Enabled = true;
            lanMode.Enabled = tailscaleMode.Enabled = true;
            connect.Enabled = remember.Enabled = SelectedMode().HasValue;
            connect.Text = "按所选通道连接";
        }
    }

    void ConnectionStage(string stage)
    {
        Invoke(new Action(delegate { connect.Text = stage; }));
        Log("步骤 " + stage + "。");
    }
    bool ConfirmNextStep(string message, string title)
    {
        return (bool)Invoke(new Func<bool>(delegate {
            return MessageBox.Show(this, message, title, MessageBoxButtons.OKCancel, MessageBoxIcon.Information) == DialogResult.OK;
        }));
    }

    static bool TrustWorkflow(NasSiteTrust.State[] states, Func<NasSiteTrust.State[], DialogResult> confirm, Action<NasSiteTrust.State[]> add)
    {
        // Keep every share for final verification, but ask once for each unique NAS host.
        var candidates = states.Where(s => s.canAdd).ToArray();
        if (candidates.Length == 0) return false;
        DialogResult choice = confirm(candidates);
        if (choice == DialogResult.Cancel) throw new OperationCanceledException();
        if (choice != DialogResult.Yes) return false;
        add(candidates); return true;
    }
    void EnsureSiteTrust(DriveSpec[] selected)
    {
        var states = new List<NasSiteTrust.State>();
        foreach (string remote in selected.Select(d => d.remote).Distinct(StringComparer.OrdinalIgnoreCase)) {
            try {
                var state = NasSiteTrust.Inspect(remote); states.Add(state);
                Log("NAS " + state.host + (state.listed ? "：已在本地 Intranet 地址列表。" : "：未加入本地 Intranet 地址列表。") + (state.reason ?? ""));
            } catch (Exception e) { Log("站点信任检查未完成：" + e.Message + " 仍可继续 NAS 连接，未更改信任设置。"); }
        }
        // Do not trust a host if any of its selected shares was uncheckable or restricted.
        var expected = selected.Select(d => d.remote).Distinct(StringComparer.OrdinalIgnoreCase).GroupBy(r => Host(r).ToLowerInvariant()).ToDictionary(g => g.Key, g => g.Count());
        var allowed = states.Where(s => states.Count(t => t.host == s.host) == expected[s.host]
            && !states.Any(t => t.host == s.host && !t.trusted && !t.canAdd)).ToArray();
        try {
            bool added = TrustWorkflow(allowed, delegate(NasSiteTrust.State[] candidates) {
                return (DialogResult)Invoke(new Func<DialogResult>(delegate {
                    using (var dialog = new SiteTrustDialog(candidates)) return dialog.ShowDialog(this);
                }));
            }, delegate(NasSiteTrust.State[] candidates) {
                string backup = NasSiteTrust.Add(candidates);
                Log("站点信任已添加并通过 Windows 复检。本机撤回记录：" + backup);
            });
            if (!added && allowed.Any(s => s.canAdd)) Log("已跳过站点信任配置，继续 NAS 连接；打开部分文件仍可能出现安全提示。");
        } catch (OperationCanceledException) { throw; }
        catch (Exception e) { Log("站点信任未配置成功：" + e.Message + " 继续 NAS 连接；可稍后在 Internet 属性中核对。"); }
    }
    sealed class SiteTrustDialog : Form
    {
        public SiteTrustDialog(NasSiteTrust.State[] states)
        {
            Text = "确认 NAS 站点信任"; ClientSize = new Size(680, 375); StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = MinimizeBox = false; ShowIcon = false;
            Font = new Font("Microsoft YaHei UI", 10); BackColor = Color.FromArgb(13, 18, 29); ForeColor = Color.White;
            Controls.Add(new Label { Text = "将这些 NAS 地址加入本地 Intranet？", AutoSize = true, Location = new Point(24,24), Font = new Font(Font.FontFamily, 14, FontStyle.Bold) });
            Controls.Add(new Label { Text = "添加到 Internet 属性 → 安全 → 本地 Intranet → 站点。", AutoSize = true, Location = new Point(26,66), ForeColor = Color.FromArgb(153,168,190) });
            Controls.Add(new TextBox { Text = string.Join(Environment.NewLine, states.Select(s => s.host).Distinct(StringComparer.OrdinalIgnoreCase)),
                ReadOnly = true, Multiline = true, ScrollBars = ScrollBars.Vertical, BorderStyle = BorderStyle.None,
                BackColor = Color.FromArgb(24,33,49), ForeColor = Color.FromArgb(220,230,245), Location = new Point(26,99), Size = new Size(628,95) });
            Controls.Add(new Label { Text = "局域网连接添加局域网地址，Tailscale 连接添加 TS 地址。\n只信任以上具体地址，不信任整个网段；这会影响这些地址下的\n网页、文件和脚本的安全处理。添加前备份，现有条目保留。", Location = new Point(26,211), Size = new Size(630,78), ForeColor = Color.FromArgb(174,190,213) });
            var yes = new DarkButton { Text = "添加信任", DialogResult = DialogResult.Yes, Location = new Point(26,310), Size = new Size(150,42), BackColor = Color.FromArgb(83,109,239), ForeColor = Color.White };
            var skip = new DarkButton { Text = "跳过并继续连接", DialogResult = DialogResult.No, Location = new Point(191,310), Size = new Size(205,42), BackColor = Color.FromArgb(35,46,65), ForeColor = Color.FromArgb(220,230,245) };
            var stop = new DarkButton { Text = "取消", DialogResult = DialogResult.Cancel, Location = new Point(511,310), Size = new Size(143,42), BackColor = Color.FromArgb(35,46,65), ForeColor = Color.FromArgb(220,230,245) };
            Controls.Add(yes); Controls.Add(skip); Controls.Add(stop); AcceptButton = skip; CancelButton = stop;
        }
        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); ApplyWindowTheme(this); }
        protected override void WndProc(ref Message message) { base.WndProc(ref message); if (message.Msg == 0x031A) ApplyWindowTheme(this); }
    }
    static void PreviewSiteTrust()
    {
        Application.EnableVisualStyles();
        using (var form = new SiteTrustDialog(new[] {
            new NasSiteTrust.State { host = "nas-a.example" }, new NasSiteTrust.State { host = "nas-b.example" }
        })) {
            form.Opacity = 0.01; form.Show(); Application.DoEvents();
            using (var bitmap = new Bitmap(form.Width, form.Height)) {
                form.DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size));
                bitmap.Save(Path.Combine(Root, "preview-trust.png"), System.Drawing.Imaging.ImageFormat.Png);
            }
            form.Close();
        }
    }

    void ApplyChanges(DriveSpec[] changes, IDictionary<string, string> original, CredentialSet credentials)
    {
        var completed = new List<DriveSpec>();
        try {
            foreach (var target in changes) {
                string prior = original[target.letter];
                if (!SameRemote(prior, CurrentRemote(target.letter))) throw new Exception(target.letter + ": 盘符入口在连接期间发生变化，已停止；没有覆盖其他连接。");
                if (KeepRecoveredMapping(target, prior, DriveReadError)) {
                    Log(target.letter + ": 原映射已恢复，保持当前连接，不断开或重建。"); continue;
                }
                if (prior != null) {
                    int removed = WNetCancelConnection2(target.letter + ":", 1, false);
                    if (!DisconnectedOrAbsent(removed)) throw new Exception(target.letter + ": 原映射正在使用或无法断开（" + removed + "）；未强制关闭文件。");
                }
                var resource = new Resource { type = 1, local = target.letter + ":", remote = target.remote };
                int result = credentials.Map(Host(target.remote), ref resource);
                if (result != 0) {
                    if (prior != null) RestorePrior(target, prior, credentials);
                    throw new Exception(target.letter + ": 新映射失败（" + result + "）：" + NasError(result));
                }
                completed.Add(target);
                Log(target.letter + ": 已通过" + RouteName(target, target.remote) + "建立映射。");
            }
        } catch {
            foreach (var target in completed.AsEnumerable().Reverse()) {
                if (SameRemote(original[target.letter], target.remote)) {
                    Log(target.letter + ": 已恢复原入口的连接继续保留。" ); continue;
                }
                if (!SameRemote(target.remote, CurrentRemote(target.letter))) {
                    Log(target.letter + ": 盘符已被其他操作改变，跳过回退，不断开其他连接。"); continue;
                }
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
            string actual = CurrentRemote(d.letter);
            int error = DriveReadError(new DriveSpec { letter = d.letter, remote = MappingMatches(d, actual) ? actual : d.remote });
            if (error == 0) Log(d.letter + ": " + RouteName(d, CurrentRemote(d.letter)) + " · 可以打开。");
            else { complete = false; Log(d.letter + ": 映射记录存在，但打开失败（" + error + "）· " + NasError(error)); }
        }
        return complete;
    }
    static int DriveReadError(DriveSpec drive)
    {
        try { using (var items = Directory.EnumerateFileSystemEntries(drive.letter + @":\").GetEnumerator()) { items.MoveNext(); } return 0; }
        catch (Exception failure) {
            // Drive roots often report path-not-found for stale mappings. Query the approved share
            // to expose the underlying SMB error without reading or logging directory contents.
            uint attributes = GetFileAttributes(drive.remote + @"\");
            int sharedError = attributes == uint.MaxValue ? Marshal.GetLastWin32Error() : 0;
            return sharedError != 0 ? sharedError : (failure.HResult & 0xffff);
        }
    }
    static string NasError(int error)
    {
        if (error == 1326 || error == 86 || error == 2202) return "NAS 登录未通过，请重新确认 NAS 用户名、所属域及密码。";
        if (error == 5) return "NAS 共享访问被拒绝，请确认该 NAS 账号具有共享访问权限。";
        if (error == 1219) return "Windows 对这台 NAS 已有其他账号的连接；未自动清理会话或强制断开文件，请关闭相关连接后重试。";
        return new Win32Exception(error).Message;
    }
    static bool DisconnectedOrAbsent(int result) { return result == 0 || result == 2250; }
    static bool KeepRecoveredMapping(DriveSpec target, string prior, Func<DriveSpec, int> readExisting)
    {
        return SameRemote(prior, target.remote) && readExisting(target) == 0;
    }
    static DriveSpec[] ConnectionWork(DriveSpec[] approved, DriveSpec[] selected, IDictionary<string, string> current, Func<DriveSpec, int> readExisting)
    {
        Plan(approved, current);
        return selected.Where(d => !SameRemote(current[d.letter], d.remote) || readExisting(d) != 0).ToArray();
    }
    static void ValidateAccounts(DriveSpec[] targets, Func<DriveSpec, int> authenticate)
    {
        // Authenticate every affected host before removing any remembered drive mapping.
        foreach (var target in targets.GroupBy(d => Host(d.remote), StringComparer.OrdinalIgnoreCase).Select(g => g.First())) {
            int result = authenticate(target);
            if (result != 0) throw new Exception("NAS 账号验证失败（" + result + "）· " + NasError(result) + " 本次没有重建任何盘符。");
        }
    }

    static bool UacEnabled()
    {
        using (var key = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System")) {
            return key == null || Convert.ToInt32(key.GetValue("EnableLUA", 1)) != 0;
        }
    }
    static bool ShouldRelaunchUnelevated(bool administrator, bool uacEnabled) { return administrator && uacEnabled; }

    static bool SameLocalPath(string first, string second)
    {
        return string.Equals(PhysicalFilePath(Path.Combine(first, "NasRemoteConnect.exe")), PhysicalFilePath(Path.Combine(second, "NasRemoteConnect.exe")), StringComparison.OrdinalIgnoreCase);
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern uint GetFinalPathNameByHandle(Microsoft.Win32.SafeHandles.SafeFileHandle file, StringBuilder path, uint size, uint flags);
    static string PhysicalFilePath(string path)
    {
        using (var file = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete)) {
            var buffer = new StringBuilder(32768);
            uint length = GetFinalPathNameByHandle(file.SafeFileHandle, buffer, (uint)buffer.Capacity, 0);
            if (length == 0 || length >= buffer.Capacity) throw new Win32Exception(Marshal.GetLastWin32Error());
            string actual = buffer.ToString();
            if (actual.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)) return @"\\" + actual.Substring(8);
            return actual.StartsWith(@"\\?\", StringComparison.Ordinal) ? actual.Substring(4) : actual;
        }
    }
    static bool InstalledStatePath(string path, string local)
    {
        return string.Equals(Path.GetFullPath(path), Path.GetFullPath(Path.Combine(local, "CodexTools", "CompanyAccess")), StringComparison.OrdinalIgnoreCase);
    }
    static string ResolveStateRoot()
    {
        for (var directory = new DirectoryInfo(Root); directory != null; directory = directory.Parent) {
            if (directory.Name == "CompanyAIHelpers" && directory.Parent != null && directory.Parent.Name == ".runtime")
                return Path.Combine(directory.FullName, "CodexTools", "CompanyAccess");
        }
        string configured = Environment.GetEnvironmentVariable("CODEXTOOLS_DATA_ROOT");
        if (!string.IsNullOrEmpty(configured)) {
            var directory = new DirectoryInfo(configured);
            if (directory.Name == "CompanyAIHelpers" && directory.Parent != null && directory.Parent.Name == ".runtime")
                return Path.Combine(directory.FullName, "CodexTools", "CompanyAccess");
        }
        return Path.Combine(Root, "state"); // Uninstalled builds do not fall back into AppData.
    }
    static string SavedRestoreArguments(string[] args)
    {
        return args.Contains("--enable-saved-restore") ? "--enable-saved-restore" : args.Contains("--restore-saved-once") ? "--restore-saved-once" : "--restore-saved";
    }
    static string PersistedRemote(string letter)
    {
        using (var key = Registry.CurrentUser.OpenSubKey(@"Network\" + letter)) {
            return key == null ? null : key.GetValue("RemotePath") as string;
        }
    }
    static int MapUsingWindowsLogin(DriveSpec target)
    {
        var resource = new Resource { type = 1, local = target.letter + ":", remote = target.remote };
        // NULL is not an empty password: the Windows network provider uses saved/default login.
        // No interactive flags, credential reads, disconnects or profile changes.
        return WNetAddConnection2(ref resource, null, null, 0);
    }
    static Dictionary<string, int> RestoreRememberedPass(DriveSpec[] approved, Func<string, string> remembered,
        Func<string, string> current, Func<DriveSpec, int> readable, Func<string, bool> reachable,
        Func<DriveSpec, int> map, Action<string> log)
    {
        var results = new Dictionary<string, int>();
        var hosts = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
        foreach (var drive in approved) {
            string remote = remembered(drive.letter);
            if (remote == null) continue; // Never infer a new mapping or an unselected route.
            if (!MappingMatches(drive, remote)) { results[drive.letter] = 1202; continue; }
            string actual = current(drive.letter);
            if (actual != null && !SameRemote(actual, remote)) { results[drive.letter] = 1202; continue; }
            var target = new DriveSpec { letter = drive.letter, remote = remote };
            string host = Host(remote);
            if (!hosts.ContainsKey(host)) hosts[host] = reachable(host);
            if (!hosts[host]) { results[drive.letter] = 1231; continue; }
            // Do not touch disconnected drive roots or authenticate until the NAS SMB port is ready.
            if (SameRemote(actual, remote) && readable(target) == 0) { results[drive.letter] = 0; continue; }
            // Recheck both the persistent route and live device immediately before mapping.
            actual = current(drive.letter);
            if (!SameRemote(remembered(drive.letter), remote) || (actual != null && !SameRemote(actual, remote))) {
                results[drive.letter] = 1202; continue;
            }
            int result = map(target);
            if (result == 0) result = readable(target);
            results[drive.letter] = result;
            log(drive.letter + (result == 0 ? ": 已用 Windows 已保存的登录恢复原映射。" : ": 保存的登录恢复未成功（" + result + "）· " + NasError(result)));
        }
        return results;
    }
    static bool SavedRestoreTerminalError(int error)
    {
        return error == 5 || error == 86 || error == 1326 || error == 2202 || error == 1219 || error == 1202 || error == 85;
    }
    static void ConfigureSavedRestore()
    {
        RequireActivation();
        Directory.CreateDirectory(StateRoot);
        ConfigureSavedRestoreTask();
        using (var key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run")) {
            string previous = key.GetValue(SavedRestoreRunName) as string;
            if (previous != null && (!previous.EndsWith("\" --restore-saved", StringComparison.Ordinal) ||
                !previous.StartsWith("\"" + Path.Combine(StateRoot, "payloads") + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)))
                throw new Exception("自动恢复启动项已被其他配置占用，未覆盖。");
            string backup = Path.Combine(StateRoot, "saved-restore-startup-backup.json");
            if (!File.Exists(backup)) File.WriteAllText(backup, Json.Serialize(new { name = SavedRestoreRunName, previous = previous }), new UTF8Encoding(false));
            key.SetValue(SavedRestoreRunName, "\"" + PhysicalFilePath(Application.ExecutablePath) + "\" --restore-saved", RegistryValueKind.String);
        }
    }
    static object ComInvoke(object instance, string member, params object[] arguments)
    {
        return instance.GetType().InvokeMember(member, System.Reflection.BindingFlags.InvokeMethod |
            System.Reflection.BindingFlags.OptionalParamBinding, null, instance, arguments);
    }
    static object ComProperty(object instance, string member)
    {
        return instance.GetType().InvokeMember(member, System.Reflection.BindingFlags.GetProperty, null, instance, null);
    }
    static void ComProperty(object instance, string member, object value)
    {
        instance.GetType().InvokeMember(member, System.Reflection.BindingFlags.SetProperty, null, instance, new[] { value });
    }
    static void ReleaseCom(object instance)
    {
        if (instance != null && Marshal.IsComObject(instance)) Marshal.FinalReleaseComObject(instance);
    }
    static bool IsCurrentTaskUser(string account, string sid)
    {
        if (string.Equals(account, sid, StringComparison.OrdinalIgnoreCase)) return true;
        try {
            return string.Equals(new NTAccount(account).Translate(typeof(SecurityIdentifier)).Value, sid, StringComparison.OrdinalIgnoreCase);
        } catch (IdentityNotMappedException) { return false; }
        catch (ArgumentException) { return false; }
    }
    static void ConfigureSavedRestoreTask()
    {
        const string source = "CompanyAIHelpers.NasSavedMappings/v1";
        string user = WindowsIdentity.GetCurrent().User.Value;
        string name = SavedRestoreRunName + "." + user;
        object service = null, folder = null, definition = null, registration = null, principal = null,
            triggers = null, trigger = null, settings = null, actions = null, action = null, existing = null, existingDefinition = null,
            existingRegistration = null, existingPrincipal = null, installed = null;
        try {
            service = Activator.CreateInstance(Type.GetTypeFromProgID("Schedule.Service"));
            ComInvoke(service, "Connect"); folder = ComInvoke(service, "GetFolder", "\\");
            try { existing = ComInvoke(folder, "GetTask", name); }
            catch (System.Reflection.TargetInvocationException e) {
                // .NET may translate HRESULT_FILE_NOT_FOUND to FileNotFoundException, not COMException.
                if (e.InnerException == null || e.InnerException.HResult != unchecked((int)0x80070002)) throw;
            } catch (COMException e) { if (e.ErrorCode != unchecked((int)0x80070002)) throw; }
            if (existing != null) {
                existingDefinition = ComProperty(existing, "Definition");
                existingRegistration = ComProperty(existingDefinition, "RegistrationInfo");
                existingPrincipal = ComProperty(existingDefinition, "Principal");
                if (!string.Equals(Convert.ToString(ComProperty(existingRegistration, "Source")), source, StringComparison.Ordinal) ||
                    !IsCurrentTaskUser(Convert.ToString(ComProperty(existingPrincipal, "UserId")), user) ||
                    Convert.ToInt32(ComProperty(existingPrincipal, "LogonType")) != 3)
                    throw new Exception("自动恢复计划任务已被其他配置占用，未覆盖。");
            }
            string backup = Path.Combine(StateRoot, "saved-restore-task-backup.json");
            if (!File.Exists(backup)) File.WriteAllText(backup, Json.Serialize(new {
                name = name, previousXml = existing == null ? null : Convert.ToString(ComProperty(existing, "Xml"))
            }), new UTF8Encoding(false));
            definition = ComInvoke(service, "NewTask", 0);
            registration = ComProperty(definition, "RegistrationInfo");
            ComProperty(registration, "Source", source);
            ComProperty(registration, "Description", "Restore only existing approved NAS mappings after this user's sign-in; no stored passwords or forced disconnections.");
            principal = ComProperty(definition, "Principal");
            ComProperty(principal, "UserId", user);
            ComProperty(principal, "LogonType", 3); // TASK_LOGON_INTERACTIVE_TOKEN; no password, S4U or SYSTEM.
            ComProperty(principal, "RunLevel", 0); // Same ordinary desktop context, not a highest-privilege task.
            triggers = ComProperty(definition, "Triggers"); trigger = ComInvoke(triggers, "Create", 9);
            ComProperty(trigger, "UserId", user); ComProperty(trigger, "Delay", "PT30S");
            settings = ComProperty(definition, "Settings");
            ComProperty(settings, "Enabled", true); ComProperty(settings, "StartWhenAvailable", true);
            ComProperty(settings, "DisallowStartIfOnBatteries", false); ComProperty(settings, "StopIfGoingOnBatteries", false);
            ComProperty(settings, "MultipleInstances", 2); ComProperty(settings, "ExecutionTimeLimit", "PT0S");
            ComProperty(settings, "RestartCount", 3); ComProperty(settings, "RestartInterval", "PT1M");
            actions = ComProperty(definition, "Actions"); action = ComInvoke(actions, "Create", 0);
            string executable = PhysicalFilePath(Application.ExecutablePath);
            ComProperty(action, "Path", executable); ComProperty(action, "Arguments", "--restore-saved");
            ComProperty(action, "WorkingDirectory", Path.GetDirectoryName(executable));
            installed = ComInvoke(folder, "RegisterTaskDefinition", name, definition, 6, user, null, 3, null);
            if (!Convert.ToBoolean(ComProperty(installed, "Enabled"))) throw new Exception("自动恢复计划任务未启用。");
        } finally {
            foreach (object instance in new[] { installed, existingPrincipal, existingRegistration, existingDefinition, existing,
                action, actions, settings, trigger, triggers, principal, registration, definition, folder, service }) ReleaseCom(instance);
        }
    }
    void EnableRememberedRestore(CredentialSet credentials)
    {
        SignalSavedRestore(); // An explicitly confirmed login may unblock an earlier authentication failure.
        if (!credentials.SavedAny) return;
        try { ConfigureSavedRestore(); Log("已启用登录后的网络观察任务；无网等待，有网且 NAS 可达再恢复，不保存 Windows 密码。"); }
        catch (Exception e) { Log("登录已保存，但自动恢复启动项未能设置：" + e.Message); }
    }
    static void SignalSavedRestore()
    {
        using (var wake = new EventWaitHandle(false, EventResetMode.AutoReset, SavedRestoreWakeName)) wake.Set();
    }
    static void WriteSavedRestoreStatus(Dictionary<string, int> results, bool complete, string failure = null, string phase = null)
    {
        Directory.CreateDirectory(StateRoot);
        string path = Path.Combine(StateRoot, "saved-restore-status.json");
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        File.WriteAllText(temporary, Json.Serialize(new { checkedUtc = DateTime.UtcNow.ToString("o"), complete = complete, phase = phase, results = results, failure = failure }), new UTF8Encoding(false));
        if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
    }
    static void RunSavedRestore(bool once)
    {
        var drives = LoadDrives();
        var blocked = new Dictionary<string, int>();
        using (var changed = new AutoResetEvent(false)) using (var confirmedLogin = new EventWaitHandle(false, EventResetMode.AutoReset, SavedRestoreWakeName)) {
            NetworkAvailabilityChangedEventHandler availability = delegate { try { changed.Set(); } catch (ObjectDisposedException) { } };
            NetworkAddressChangedEventHandler address = delegate { try { changed.Set(); } catch (ObjectDisposedException) { } };
            NetworkChange.NetworkAvailabilityChanged += availability;
            NetworkChange.NetworkAddressChanged += address;
            try {
                while (true) {
                    RequireActivation();
                    bool network = NetworkInterface.GetIsNetworkAvailable();
                    var latest = RestoreRememberedPass(drives.Where(d => !blocked.ContainsKey(d.letter)).ToArray(),
                        PersistedRemote, CurrentRemote, DriveReadError, delegate(string host) { return network && Reachable(host); }, MapUsingWindowsLogin, delegate { });
                    foreach (var item in latest) if (SavedRestoreTerminalError(item.Value)) blocked[item.Key] = item.Value;
                    foreach (var item in blocked) latest[item.Key] = item.Value;
                    bool complete = latest.Values.All(value => value == 0);
                    WriteSavedRestoreStatus(latest, complete, null, once ? "one-shot" : !network ? "waiting-for-network" : complete ? "watching-network" : blocked.Count != 0 ? "needs-user-confirmation" : "waiting-for-nas");
                    if (once) { Environment.ExitCode = complete ? 0 : 1; return; }
                    // Logon starts the observer, not a one-time connection attempt. Network events
                    // wake it hours later; periodic checks also cover NAS/TS readiness and wake from sleep.
                    int wake = WaitHandle.WaitAny(new WaitHandle[] { changed, confirmedLogin }, complete ? 180000 : 60000);
                    if (wake == 1) blocked.Clear(); // Never repeatedly submit rejected credentials on network events.
                    if (wake != WaitHandle.WaitTimeout) Thread.Sleep(5000); // Coalesce adapter/TS route changes.
                }
            } finally {
                NetworkChange.NetworkAvailabilityChanged -= availability;
                NetworkChange.NetworkAddressChanged -= address;
            }
        }
    }

    static string LoadDefaultUser()
    {
        return Json.Deserialize<ModuleConfig>(File.ReadAllText(Path.Combine(Root, "nas-drives.json"), Encoding.UTF8)).defaultUser ?? "";
    }
    static void RequireActivation()
    {
        if (!SameLocalPath(VerifiedActivationRoot(), Root)) throw new Exception("请使用已激活的公司模块入口。");
    }
    static string VerifiedActivationRoot()
    {
        byte[] sealedRecord = File.ReadAllBytes(Path.Combine(StateRoot, "activation.dpapi"));
        byte[] plain = ProtectedData.Unprotect(sealedRecord, null, DataProtectionScope.CurrentUser);
        Dictionary<string, object> record;
        try { record = Json.Deserialize<Dictionary<string, object>>(Encoding.UTF8.GetString(plain)); }
        finally { Array.Clear(plain, 0, plain.Length); }
        if (Convert.ToString(record["companyId"]) != "wanling-media" || Convert.ToString(record["format"]) != "local-guide/v1")
            throw new Exception("公司模块未启用，请让 Codex 导入公司提供的引导文件。");
        string payloadId = Convert.ToString(record["payloadId"]);
        if (!Regex.IsMatch(payloadId, "^[a-f0-9]{32}$")) throw new Exception("公司激活记录无效。");
        string expectedRoot = Path.GetFullPath(Path.Combine(StateRoot, "payloads", payloadId)).TrimEnd(Path.DirectorySeparatorChar);
        var files = (Dictionary<string, object>)record["files"];
        foreach (string name in new[] { "NasRemoteConnect.exe", "nas-drives.json" }) {
            using (var hash = SHA256.Create()) using (var file = File.OpenRead(Path.Combine(expectedRoot, name))) {
                string digest = BitConverter.ToString(hash.ComputeHash(file)).Replace("-", "");
                if (!string.Equals(digest, Convert.ToString(files[name]), StringComparison.OrdinalIgnoreCase)) throw new Exception("公司模块校验失败。");
            }
        }
        return expectedRoot;
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
        public bool RememberRequested;
        public bool SavedAny;
        readonly Dictionary<string, Tuple<string, SecureString>> entries = new Dictionary<string, Tuple<string, SecureString>>(StringComparer.OrdinalIgnoreCase);
        public void Add(string host, string user, SecureString password) { entries.Add(host, Tuple.Create(user, password)); }
        public int Map(string host, ref Resource resource, int flags = 1)
        {
            var entry = entries[host];
            IntPtr pointer = Marshal.SecureStringToGlobalAllocUnicode(entry.Item2);
            try { return WNetAddSecure(ref resource, pointer, entry.Item1, flags); }
            finally { Marshal.ZeroFreeGlobalAllocUnicode(pointer); }
        }
        public int Save(string host)
        {
            if (!RememberRequested) throw new InvalidOperationException("未确认记住 NAS 登录。");
            if (!Regex.IsMatch(host ?? "", @"^[a-zA-Z0-9.-]+$")) throw new ArgumentException("NAS 地址无效。");
            var entry = entries[host];
            IntPtr pointer = Marshal.SecureStringToGlobalAllocUnicode(entry.Item2);
            try {
                var credential = new WindowsCredential {
                    Type = 2, TargetName = host, UserName = entry.Item1, Persist = 2,
                    CredentialBlob = pointer, CredentialBlobSize = checked((uint)entry.Item2.Length * 2)
                };
                int result = CredWrite(ref credential, 0) ? 0 : Marshal.GetLastWin32Error();
                if (result == 0) SavedAny = true;
                return result;
            } finally { Marshal.ZeroFreeGlobalAllocUnicode(pointer); }
        }
        public void Dispose() { foreach (var entry in entries.Values) entry.Item2.Dispose(); entries.Clear(); }
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct WindowsCredential
    {
        public uint Flags, Type;
        public string TargetName, Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist, AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias, UserName;
    }
    [DllImport("advapi32.dll", EntryPoint = "CredWriteW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool CredWrite(ref WindowsCredential credential, uint flags);

    static void AuthenticateAndRemember(DriveSpec[] targets, CredentialSet credentials,
        Func<DriveSpec, int> authenticate, Func<string, int> save, Action<string> log)
    {
        // Never save an account until all requested NAS accounts have authenticated.
        ValidateAccounts(targets, authenticate);
        if (!credentials.RememberRequested) { log("未勾选记住登录：没有写入或删除 Windows 凭据。"); return; }
        foreach (string host in targets.Select(d => Host(d.remote)).Distinct(StringComparer.OrdinalIgnoreCase)) {
            int result;
            try { result = save(host); }
            catch { log("NAS " + host + "：登录已验证，但 Windows 未能保存凭据；下次可能需要重新输入。现有连接保持不变。"); continue; }
            log(result == 0 ? "NAS " + host + "：已保存到 Windows 凭据管理器，供此电脑当前用户后续登录使用。"
                : "NAS " + host + "：Windows 未保存凭据（" + result + "），下次可能需要重新输入。现有连接保持不变。");
        }
    }
    sealed class CredentialDialog : Form
    {
        readonly string[] hosts;
        readonly TextBox[] users, passwords;
        readonly CheckBox rememberLogin = new CheckBox();
        public bool RememberSelected { get { return rememberLogin.Checked; } }
        public CredentialDialog(string[] servers, string defaultUser, int repairs = 0, bool rememberOnly = false)
        {
            hosts = servers; users = new TextBox[hosts.Length]; passwords = new TextBox[hosts.Length];
            Text = "确认 NAS 登录信息"; ClientSize = new Size(590, 262 + hosts.Length * 114);
            StartPosition = FormStartPosition.CenterParent; FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false; Font = new Font("Microsoft YaHei UI", 10);
            ShowIcon = false;
            BackColor = Color.FromArgb(13, 18, 29); ForeColor = Color.White;
            Controls.Add(new Label { Text = "确认本次连接的 NAS 账号", AutoSize = true, Location = new Point(25,23), Font = new Font(Font.FontFamily, 15, FontStyle.Bold), ForeColor = Color.White });
            Controls.Add(new Label { Text = rememberOnly ? "验证并保存所选 NAS 地址的登录；不切换或重建现有盘符。" : repairs > 0 ? "验证账号后恢复 " + repairs + " 个失效映射；不强制断开正在使用的文件。" : "全部确认并验证后才更改盘符；不勾选记住时，密码仅用于本次。", AutoSize = true, Location = new Point(27,58), ForeColor = Color.FromArgb(153,168,190) });
            for (int i = 0; i < hosts.Length; i++) {
                int y = 100 + i * 114;
                Controls.Add(new Label { Text = "NAS " + (i + 1) + " · " + hosts[i], AutoSize = true, Location = new Point(27,y), Font = new Font(Font.FontFamily, 10, FontStyle.Bold), ForeColor = Color.FromArgb(205,217,233) });
                Controls.Add(new Label { Text = "用户名", AutoSize = true, Location = new Point(27,y+39), ForeColor = Color.FromArgb(153,168,190) });
                Controls.Add(new Label { Text = "密码", AutoSize = true, Location = new Point(305,y+39), ForeColor = Color.FromArgb(153,168,190) });
                users[i] = new TextBox { Text = defaultUser, Location = new Point(88,y+34), Width = 185, BackColor = Color.FromArgb(28,39,58), ForeColor = Color.White, BorderStyle = BorderStyle.FixedSingle };
                passwords[i] = new TextBox { UseSystemPasswordChar = true, Location = new Point(352,y+34), Width = 206, BackColor = Color.FromArgb(28,39,58), ForeColor = Color.White, BorderStyle = BorderStyle.FixedSingle };
                Controls.Add(users[i]); Controls.Add(passwords[i]);
            }
            rememberLogin.Text = "记住 NAS 登录（Windows 凭据管理器）";
            rememberLogin.AutoSize = true; rememberLogin.Location = new Point(27, 100 + hosts.Length * 114);
            rememberLogin.Checked = rememberOnly; rememberLogin.ForeColor = Color.White;
            Controls.Add(rememberLogin);
            Controls.Add(new Label { Text = "仅保存以上地址，可能更新已有凭据；网络恢复且 NAS 可达后恢复原网盘。\n不勾选不会保存或删除已有凭据，可在 Windows 凭据管理器中管理。", AutoSize = true,
                Location = new Point(27, 132 + hosts.Length * 114), ForeColor = Color.FromArgb(153,168,190), Font = new Font(Font.FontFamily, 9) });
            var confirm = new DarkButton { Text = rememberOnly ? "验证并保存登录" : "确认并继续连接", Location = new Point(347,ClientSize.Height-58), Size = new Size(211,39) };
            var close = new DarkButton { Text = "取消", DialogResult = DialogResult.Cancel, Location = new Point(238,ClientSize.Height-58), Size = new Size(97,39) };
            rememberLogin.CheckedChanged += delegate { if (rememberOnly) confirm.Text = rememberLogin.Checked ? "验证并保存登录" : "仅验证登录"; };
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
            var result = new CredentialSet { RememberRequested = rememberLogin.Checked };
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
        protected override void OnHandleCreated(EventArgs e) { base.OnHandleCreated(e); ApplyWindowTheme(this); }
        protected override void WndProc(ref Message message) { base.WndProc(ref message); if (message.Msg == 0x031A) ApplyWindowTheme(this); }
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
    static void PreviewUi(bool interactive = false)
    {
        Application.EnableVisualStyles();
        using (var form = new NasRemoteConnect(true)) using (var bitmap = new Bitmap(form.Width, form.Height)) {
            if (!interactive) form.Opacity = 0.01;
            form.Show(); Application.DoEvents();
            form.SetDriveCards(new[] { "局域网", "局域网", "Tailscale 地址", "未连接" });
            form.Log("W: 局域网 · 可以打开。");
            form.Log("X: 局域网 · 可以打开。");
            form.Log("Y: Tailscale 地址 · 可以打开。");
            form.Log("Z: 未连接；请选择本次连接方式。");
            if (interactive) {
                Application.Run(form); return;
            }
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
    static DriveSpec[] SelectConnectionDrives(DriveSpec[] drives, IDictionary<string, string> current, ConnectionMode mode)
    {
        Plan(drives, current);
        return drives.Select(d => new DriveSpec { letter = d.letter,
            remote = mode == ConnectionMode.Tailscale ? d.remote : LanTarget(d),
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
            if (!process.WaitForExit(5000)) { process.Kill(); throw new Exception("Tailscale 状态检查超时。"); }
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
        if (!ConfirmNextStep("这台电脑尚未安装 Tailscale。点击“确定”开始官方安装；安装成功后会自动继续检查登录。点击“取消”停止本次连接。", "需要安装 Tailscale")) throw new OperationCanceledException();
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
            if (process.ExitCode == 3010) throw new Exception("Tailscale 已安装，但 Windows 要求重启。请重启电脑后再次点击连接；当前尚未进入 NAS 连接。");
        }
        if (Cli() == null) throw new Exception("安装结束，但未找到 Tailscale。请检查安装结果。");
        Log("Tailscale 安装完成。");
    }
    void EnsureLogin()
    {
        string state = PrepareTailscaleClient(TryBackendState, DesktopClientRunning, StartDesktopClient, Thread.Sleep, Log);
        if (state == "Running") { Log("Tailscale 已连接，沿用现有授权。"); return; }
        if (state == "NeedsMachineAuth") throw new Exception("Tailscale 正在等待网络管理员批准此设备；批准后再点击连接。");
        if (state == "NeedsLogin" && !ConfirmNextStep("Tailscale 尚未登录。点击“确定”打开官方登录流程，请在网页中完成授权。登录成功后自动进入 NAS 账号确认；点击“取消”停止本次连接。", "需要登录 Tailscale")) throw new OperationCanceledException();
        Log("正在连接 Tailscale；需要授权时会打开官方登录页面，请选择 GitHub，并在 github.com 官方页面完成授权；工具箱不接收 GitHub 密码。登录后自动继续。");
        bool browserOpened = false; object guard = new object();
        // Bare up preserves an existing profile and starts authentication only when needed.
        using (var process = new Process { StartInfo = new ProcessStartInfo(Cli(), "up") { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true } }) {
            DataReceivedEventHandler received = delegate(object sender, DataReceivedEventArgs e) {
                if (e.Data == null) return;
                var match = Regex.Match(e.Data, @"https://login\.tailscale\.com/[a-zA-Z0-9/_?=.-]+");
                lock (guard) { if (!match.Success || browserOpened) return; browserOpened = true; }
                BeginInvoke(new Action(delegate { try { Process.Start(new ProcessStartInfo(match.Value) { UseShellExecute = true }); Log("官方登录网页已打开。请完成网页授权，成功后这里会自动继续。"); } catch { Log("登录网页未能打开：请点击系统托盘中的 Tailscale 图标，选择登录；完成后这里会自动继续。"); } }));
            };
            process.OutputDataReceived += received; process.ErrorDataReceived += received;
            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
            try {
                var deadline = DateTime.UtcNow.AddMinutes(3);
                int polls = 0;
                while (DateTime.UtcNow < deadline) {
                    Thread.Sleep(2000);
                    state = BackendState();
                    if (state == "Running") { Log("Tailscale 授权完成，继续连接 NAS。"); return; }
                    string failure = LoginFailure(state, process.HasExited, process.HasExited ? process.ExitCode : 0);
                    if (failure != null) throw new Exception(failure);
                    if (++polls % 5 == 0) {
                        bool opened; lock (guard) { opened = browserOpened; }
                        Log(opened ? "仍在等待官方网页授权完成；请查看已打开的登录网页。" : "尚未收到官方登录链接；正在等待 Tailscale 返回连接状态。当前状态：" + state + "。");
                    }
                }
                throw new Exception("等待登录超时。完成登录后再次点击连接即可。");
            } finally { if (!process.HasExited) process.Kill(); }
        }
    }
    static string TryBackendState()
    {
        try { return BackendState(); } catch (Exception) { return "Unavailable"; }
    }
    static bool DesktopClientRunning()
    {
        int session = Process.GetCurrentProcess().SessionId;
        foreach (var process in Process.GetProcessesByName("tailscale-ipn")) using (process) {
            try { if (process.SessionId == session) return true; } catch (InvalidOperationException) { }
        }
        return false;
    }
    static void StartDesktopClient()
    {
        string cli = Cli();
        string desktop = cli == null ? null : Path.Combine(Path.GetDirectoryName(cli), "tailscale-ipn.exe");
        if (desktop == null || !File.Exists(desktop)) throw new Exception("未找到 Tailscale 官方桌面客户端，请修复 Tailscale 安装后重试。");
        using (var process = Process.Start(new ProcessStartInfo(desktop) { UseShellExecute = true, WindowStyle = ProcessWindowStyle.Hidden })) {
            if (process == null) throw new Exception("Tailscale 客户端未能启动，请从开始菜单打开 Tailscale 后重试。");
        }
    }
    static string PrepareTailscaleClient(Func<string> readState, Func<bool> clientRunning, Action startClient, Action<int> wait, Action<string> log, Func<DateTime> clock = null)
    {
        clock = clock ?? delegate { return DateTime.UtcNow; };
        var deadline = clock().AddSeconds(20);
        string state = readState();
        if (state == "Running") return state;
        if (!clientRunning()) { log("Tailscale 桌面客户端尚未运行，正在启动官方客户端。"); startClient(); }
        for (int polls = 0; clock() < deadline; polls++) {
            state = readState();
            if (state == "Running" || state == "Stopped" || state == "NeedsLogin" || state == "NeedsMachineAuth" || state == "Starting") return state;
            if (polls % 5 == 0) log("正在等待 Tailscale 客户端及服务初始化；当前状态：" + state + "。");
            wait(1000);
        }
        throw new Exception("等待约 20 秒后 Tailscale 客户端或服务仍未就绪；请查看官方托盘状态，检查服务及网络后重试。本次尚未进入 NAS 连接。");
    }
    static string LoginFailure(string state, bool exited, int exitCode)
    {
        if (state == "Running") return null;
        if (state == "NeedsMachineAuth") return "Tailscale 正在等待网络管理员批准此设备；批准后再点击连接。";
        if (!exited) return null;
        return "Tailscale 连接命令已结束（退出码 " + exitCode + "），但尚未连接（状态 " + state + "）；请查看官方托盘状态后重试。";
    }
    static void TailscaleStartupTest()
    {
        int starts = 0, reads = 0, waits = 0;
        string state = PrepareTailscaleClient(delegate { return ++reads == 1 ? "NoState" : "Running"; }, delegate { return false; }, delegate { starts++; }, delegate(int ms) { waits++; }, delegate(string line) { });
        if (state != "Running" || starts != 1) throw new Exception("Missing Tailscale desktop startup failed");
        starts = 0;
        PrepareTailscaleClient(delegate { return "Running"; }, delegate { throw new Exception("Running backend must be reused"); }, delegate { starts++; }, delegate(int ms) { throw new Exception("Running backend must not wait"); }, delegate(string line) { });
        if (starts != 0) throw new Exception("Existing Tailscale authorization not preserved");
        waits = 0; bool refused = false; DateTime time = DateTime.UtcNow;
        try { PrepareTailscaleClient(delegate { return "NoState"; }, delegate { return true; }, delegate { throw new Exception("Do not duplicate desktop"); }, delegate(int ms) { waits++; time = time.AddMilliseconds(ms); }, delegate(string line) { }, delegate { return time; }); } catch (Exception e) { refused = e.Message.Contains("20 秒"); }
        if (!refused || waits != 20) throw new Exception("Tailscale initialization timeout failed");
        refused = false;
        try { PrepareTailscaleClient(delegate { return "Unavailable"; }, delegate { return false; }, delegate { throw new Exception("startup failed"); }, delegate(int ms) { }, delegate(string line) { }); } catch (Exception e) { refused = e.Message == "startup failed"; }
        if (!refused) throw new Exception("Tailscale startup error was hidden");
        if (LoginFailure("NeedsLogin", true, 0) == null || LoginFailure("NeedsLogin", true, 1) == null || LoginFailure("NeedsLogin", false, 0) != null || LoginFailure("Running", true, 1) != null) throw new Exception("Tailscale login exit handling failed");
        if (LoginFailure("NeedsMachineAuth", false, 0) == null) throw new Exception("Device approval not reported");
    }
    void Check(DriveSpec[] drives)
    {
        try { Log(Cli() == null ? "Tailscale 尚未安装（不影响局域网连接）。" : "Tailscale：" + BackendState()); }
        catch (Exception) { Log("Tailscale 状态暂不可用，继续检查局域网和已有映射。"); }
        foreach (var host in drives.SelectMany(d => new[] { d.remote, d.lanRemote }).Where(r => r != null).Select(Host).Distinct()) Log("NAS " + host + (Reachable(host) ? "：文件共享可达。" : "：文件共享不可达。"));
        foreach (var d in drives) Log(d.letter + ": " + RouteName(d, CurrentRemote(d.letter)) + " · " + (CurrentRemote(d.letter) ?? "未映射"));
        foreach (string remote in drives.SelectMany(d => new[] { d.remote, d.lanRemote }).Where(r => r != null).Distinct(StringComparer.OrdinalIgnoreCase)) {
            try {
                var state = NasSiteTrust.Inspect(remote);
                Log("站点信任 " + state.host + (state.listed ? "：已在本地 Intranet 地址列表。" : "：未加入本地 Intranet 地址列表。") + (state.reason ?? ""));
            } catch (Exception e) { Log("站点信任检查未完成：" + e.Message); }
        }
        Log("只读检查完成，没有安装、登录、更改映射或信任设置。");
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
        using (var form = new NasRemoteConnect(true)) {
            if (form.SelectedMode().HasValue || form.connect.Enabled) throw new Exception("Connection was enabled before an explicit route choice");
            form.tailscaleMode.Checked = true;
            if (form.SelectedMode() != ConnectionMode.Tailscale || !form.connect.Enabled) throw new Exception("Explicit Tailscale choice was not enabled");
        }
        if (ShouldRelaunchUnelevated(true, false) || ShouldRelaunchUnelevated(false, true) || !ShouldRelaunchUnelevated(true, true))
            throw new Exception("UAC compatibility failed");
        var drives = new[] { new DriveSpec { letter = "W", remote = @"\\remote.example\share", lanRemote = @"\\lan.example\share" } };
        var existing = new Dictionary<string, string> { { "W", @"\\LAN.example\SHARE" } };
        if (Plan(drives, existing).Count != 0 || SelectConnectionDrives(drives, existing, ConnectionMode.Lan)[0].remote != drives[0].lanRemote)
            throw new Exception("Explicit LAN choice changed an existing approved LAN mapping");
        existing["W"] = @"\\unknown.example\share";
        bool refused = false; try { Plan(drives, existing); } catch { refused = true; }
        if (!refused) throw new Exception("Unknown server was accepted by share name");
        existing["W"] = null;
        var lan = SelectConnectionDrives(drives, existing, ConnectionMode.Lan);
        var remote = SelectConnectionDrives(drives, existing, ConnectionMode.Tailscale);
        if (lan[0].remote != drives[0].lanRemote || NeedsRemoteAccess(drives, lan, existing)
            || remote[0].remote != drives[0].remote || !NeedsRemoteAccess(drives, remote, existing))
            throw new Exception("LAN/remote selection failed");
        existing["W"] = drives[0].lanRemote;
        var forcedRemote = SelectConnectionDrives(drives, existing, ConnectionMode.Tailscale);
        if (forcedRemote[0].remote != drives[0].remote || !NeedsRemoteAccess(drives, forcedRemote, existing)
            || RouteName(drives[0], existing["W"]) != "局域网")
            throw new Exception("Forced Tailscale route or actual route reporting failed");
        existing["W"] = drives[0].remote;
        var forcedLan = SelectConnectionDrives(drives, existing, ConnectionMode.Lan);
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
        TailscaleStartupTest();
        SiteTrustWorkflowTest();
        ReconnectWorkflowTest();
        PreserveConnectionTest();
        RememberLoginTest();
        SavedRestoreWorkflowTest();
        string fakeLocal = @"C:\Example\.runtime\CompanyAIHelpers";
        if (!InstalledStatePath(Path.Combine(fakeLocal, "CodexTools", "CompanyAccess"), fakeLocal)) throw new Exception("Workspace install path rejected");
        if (InstalledStatePath(Path.Combine(fakeLocal, "Packages", "Example.Package", "LocalCache", "Local", "CompanyAIHelpers", "CodexTools", "CompanyAccess"), fakeLocal)) throw new Exception("Packaged cache path accepted");
        if (InstalledStatePath(@"C:\Other\CompanyAIHelpers\CodexTools\CompanyAccess", fakeLocal)) throw new Exception("Foreign state path accepted");
        if (!File.Exists(PhysicalFilePath(Application.ExecutablePath))) throw new Exception("Physical executable path unavailable");
        File.WriteAllText(Path.Combine(Root, "self-test.json"), "{\"passed\":70,\"mutatedMappings\":false,\"mutatedTrustSettings\":false,\"mutatedCredentials\":false,\"mutatedStartup\":false}", new UTF8Encoding(false));
    }
    static void SavedRestoreWorkflowTest()
    {
        var drive = new DriveSpec { letter = "W", remote = @"\\nas.example\share", lanRemote = @"\\lan.example\share" };
        var targets = new[] { drive };
        string saved = drive.remote, actual = drive.remote;
        int readError = 3, mapError = 0, mapped = 0;
        bool online = true;
        Func<DriveSpec[], Dictionary<string, int>> restore = delegate(DriveSpec[] list) {
            return RestoreRememberedPass(list, delegate { return saved; }, delegate { return actual; },
                delegate { return readError; }, delegate { return online; }, delegate(DriveSpec target) {
                    mapped++; actual = target.remote;
                    if (mapError == 0) readError = 0;
                    return mapError;
                }, delegate { });
        };
        if (restore(targets)["W"] != 0 || mapped != 1) throw new Exception("Saved login did not recover stale mapping");
        if (restore(targets)["W"] != 0 || mapped != 1) throw new Exception("Healthy mapping was remapped");
        saved = null; actual = null;
        if (restore(targets).Count != 0 || mapped != 1) throw new Exception("Unremembered mapping was created");
        saved = @"\\other.example\share";
        if (restore(targets)["W"] != 1202 || mapped != 1) throw new Exception("Unknown persisted route was used");
        saved = drive.remote; actual = @"\\other.example\share";
        if (restore(targets)["W"] != 1202 || mapped != 1) throw new Exception("Occupied drive was overwritten");
        actual = null; online = false;
        if (restore(targets)["W"] != 1231 || mapped != 1) throw new Exception("Offline NAS was authenticated");
        online = true; mapError = 1326;
        if (restore(targets)["W"] != 1326 || mapped != 2 || !SavedRestoreTerminalError(1326)) throw new Exception("Failed login was hidden or would be retried");
        mapError = 0; actual = null; saved = drive.lanRemote;
        if (restore(targets)["W"] != 0 || actual != drive.lanRemote) throw new Exception("Remembered LAN route was silently switched");
        saved = drive.remote; actual = null; int before = mapped;
        var result = RestoreRememberedPass(targets, delegate { return saved; }, delegate { return actual; },
            delegate { return 3; }, delegate { actual = @"\\other.example\share"; return true; },
            delegate { mapped++; return 0; }, delegate { });
        if (result["W"] != 1202 || mapped != before) throw new Exception("Mapping race was not protected");
        actual = null; saved = drive.remote;
        result = RestoreRememberedPass(targets, delegate { return saved; }, delegate { return actual; },
            delegate { return 3; }, delegate { saved = drive.lanRemote; return true; },
            delegate { mapped++; return 0; }, delegate { });
        if (result["W"] != 1202 || mapped != before) throw new Exception("Persisted-route race was not protected");
        if (SavedRestoreTerminalError(1231) || !SavedRestoreTerminalError(1219) || !SavedRestoreTerminalError(5)) throw new Exception("Retry policy changed");
        if (SavedRestoreArguments(new[] { "--restore-saved-once", "--untrusted" }) != "--restore-saved-once") throw new Exception("Startup handoff arguments were not restricted");
        saved = drive.remote; actual = drive.remote;
        result = RestoreRememberedPass(targets, delegate { return saved; }, delegate { return actual; },
            delegate { throw new Exception("Offline mapping root was accessed"); }, delegate { return false; },
            delegate { throw new Exception("Offline login was attempted"); }, delegate { });
        if (result["W"] != 1231) throw new Exception("Offline observer did not wait for connectivity");
        online = true; readError = 3; mapError = 0; before = mapped;
        if (restore(targets)["W"] != 0 || mapped != before + 1) throw new Exception("Later network recovery did not reconnect");
        readError = 3; before = mapped;
        if (restore(targets)["W"] != 0 || mapped != before + 1) throw new Exception("Previously restored drive was excluded from later recovery");
    }
    static void RememberLoginTest()
    {
        var targets = new[] {
            new DriveSpec { remote = @"\\nas-a.example\one" }, new DriveSpec { remote = @"\\nas-a.example\two" },
            new DriveSpec { remote = @"\\nas-b.example\three" }
        };
        Action<string> noLog = delegate { };
        using (var credentials = new CredentialSet()) {
            int uncheckedSaves = 0;
            AuthenticateAndRemember(targets, credentials, delegate { return 0; }, delegate { uncheckedSaves++; return 0; }, noLog);
            if (uncheckedSaves != 0) throw new Exception("Unchecked login was saved");
            credentials.RememberRequested = true;
            int authenticated = 0, saved = 0; bool rejected = false;
            try { AuthenticateAndRemember(targets, credentials, delegate { return ++authenticated == 1 ? 0 : 1326; }, delegate { saved++; return 0; }, noLog); }
            catch { rejected = true; }
            if (!rejected || saved != 0) throw new Exception("Credentials saved before all NAS authentication succeeded");
            authenticated = saved = 0;
            AuthenticateAndRemember(targets, credentials, delegate { authenticated++; return 0; }, delegate { if (authenticated != 2) throw new Exception("Save ran before full validation"); saved++; return 0; }, noLog);
            if (saved != 2) throw new Exception("Credentials were saved per share instead of exact NAS host");
            var logs = new List<string>(); saved = 0;
            AuthenticateAndRemember(targets, credentials, delegate { return 0; }, delegate { saved++; return 5; }, logs.Add);
            if (saved != 2 || logs.Count != 2 || logs.Any(s => !s.Contains("未保存"))) throw new Exception("Credential write failure was hidden");
        }
        using (var normal = new CredentialDialog(new[] { "nas.example" }, "ExampleUser"))
        using (var explicitSave = new CredentialDialog(new[] { "nas.example" }, "ExampleUser", 0, true)) {
            if (normal.RememberSelected || !explicitSave.RememberSelected) throw new Exception("Remember login defaults lack explicit intent");
        }
        if (Marshal.SizeOf(typeof(WindowsCredential)) != (IntPtr.Size == 8 ? 80 : 52)
            || Marshal.OffsetOf(typeof(WindowsCredential), "CredentialBlob").ToInt32() != (IntPtr.Size == 8 ? 40 : 28))
            throw new Exception("Windows credential native layout invalid");
    }
    static void PreserveConnectionTest()
    {
        var drive = new DriveSpec { letter = "W", remote = @"\\nas.example\share", lanRemote = @"\\lan.example\share" };
        var drives = new[] { drive }; var current = new Dictionary<string, string> { { "W", drive.remote } };
        var initiallyFailed = ConnectionWork(drives, drives, current, delegate { return 1326; });
        if (initiallyFailed.Length != 1 || ConnectionWork(drives, initiallyFailed, current, delegate { return 0; }).Length != 0)
            throw new Exception("Login-restored drive was scheduled for teardown");
        if (!KeepRecoveredMapping(drive, drive.remote, delegate { return 0; })) throw new Exception("Recovered same-route mapping was not preserved");
        if (KeepRecoveredMapping(drive, drive.lanRemote, delegate { throw new Exception("An approved route switch must remain distinct"); })) throw new Exception("Route switch was mistaken for same-route recovery");
        if (KeepRecoveredMapping(drive, drive.remote, delegate { return 1326; })) throw new Exception("Unreadable mapping was mistaken for healthy");
        using (var form = new NasRemoteConnect(true)) {
            if (form.SelectedMode().HasValue || form.connect.Enabled) throw new Exception("Window construction selected a route or connected by default");
            form.Close();
        }
    }
    static void ReconnectWorkflowTest()
    {
        var drives = new[] {
            new DriveSpec { letter = "W", remote = @"\\nas-a.example\share-w" },
            new DriveSpec { letter = "X", remote = @"\\nas-a.example\share-x" },
            new DriveSpec { letter = "Y", remote = @"\\nas-b.example\share-y" }
        };
        var current = drives.ToDictionary(d => d.letter, d => d.remote);
        if (ConnectionWork(drives, drives, current, delegate { return 0; }).Length != 0) throw new Exception("Healthy mappings were reconnected");
        if (ConnectionWork(drives, drives, current, delegate { return 1326; }).Length != 3) throw new Exception("Stale mappings bypassed credentials");
        var partial = ConnectionWork(drives, drives, current, delegate(DriveSpec d) { return d.letter == "X" ? 1326 : 0; });
        if (partial.Length != 1 || partial[0].letter != "X") throw new Exception("A healthy mapping was included in recovery");
        current["W"] = @"\\unknown.example\share-w";
        bool refused = false;
        try { ConnectionWork(drives, drives, current, delegate { throw new Exception("Unknown mapping was probed"); }); } catch { refused = true; }
        if (!refused) throw new Exception("Unknown mapping was accepted for recovery");
        current = drives.ToDictionary(d => d.letter, d => (string)null);
        if (ConnectionWork(drives, drives, current, delegate { throw new Exception("Missing mapping was probed"); }).Length != 3) throw new Exception("New mapping plan failed");
        int validated = 0, mapped = 0;
        refused = false;
        try {
            WithConfirmedCredentials(delegate { return new CredentialSet(); }, delegate {
                ValidateAccounts(drives, delegate { return ++validated == 1 ? 0 : 1326; });
                mapped++;
            });
        } catch { refused = true; }
        if (!refused || mapped != 0 || validated != 2) throw new Exception("A drive was changed before both NAS accounts validated");
        validated = mapped = 0;
        WithConfirmedCredentials(delegate { return new CredentialSet(); }, delegate {
            ValidateAccounts(drives, delegate { validated++; return 0; }); mapped++;
        });
        if (validated != 2 || mapped != 1) throw new Exception("NAS authentication was repeated per share or omitted");
        if (WithConfirmedCredentials(delegate { return null; }, delegate { throw new Exception("Cancellation authenticated or changed a mapping"); })) throw new Exception("Recovery cancellation was ignored");
        if (!DisconnectedOrAbsent(0) || !DisconnectedOrAbsent(2250) || DisconnectedOrAbsent(2401) || DisconnectedOrAbsent(5)
            || !NasError(1326).Contains("登录") || !NasError(5).Contains("权限") || !NasError(1219).Contains("未自动清理")) throw new Exception("Recovery error safeguards failed");
    }
    static void SiteTrustWorkflowTest()
    {
        var missing = new NasSiteTrust.State { remote = @"\\nas.example\share", host = "nas.example", uncZone = 3, httpZone = 3, httpsZone = 3 };
        if (NasSiteTrust.Pattern(missing.remote) != "*://nas.example" || !NasSiteTrust.Applies("https://nas.example", "nas.example")
            || !NasSiteTrust.Applies("nas.example", "nas.example") || !NasSiteTrust.SamePattern("nas.example", "*://nas.example")
            || !NasSiteTrust.Applies("*://*.example", "nas.example") || NasSiteTrust.Applies("file://other.example", "nas.example")) throw new Exception("Exact NAS address trust scope failed");
        bool rejected = false; try { NasSiteTrust.Pattern(@"\\*.example\share"); } catch { rejected = true; }
        if (!rejected) throw new Exception("Wildcard trust was accepted");
        var fileOnly = new NasSiteTrust.State { uncZone = 1, httpZone = 3, httpsZone = 3 };
        if (fileOnly.trusted || !fileOnly.canAdd) throw new Exception("File-only trust was mistaken for an Intranet address entry");
        Action<NasSiteTrust.State[]> noAdd = delegate { throw new Exception("Unexpected trust write"); };
        if (TrustWorkflow(new[] { missing }, delegate { return DialogResult.No; }, noAdd)) throw new Exception("Skip was ignored");
        rejected = false; try { TrustWorkflow(new[] { missing }, delegate { return DialogResult.Cancel; }, noAdd); } catch (OperationCanceledException) { rejected = true; }
        if (!rejected) throw new Exception("Cancel was ignored");
        var existing = new NasSiteTrust.State { listed = true, uncZone = 1, httpZone = 1, httpsZone = 1 };
        var restricted = new NasSiteTrust.State { uncZone = 4, httpZone = 3, httpsZone = 3 };
        var managed = new NasSiteTrust.State { uncZone = 3, httpZone = 3, httpsZone = 3, reason = "managed" };
        if (TrustWorkflow(new[] { existing, restricted, managed }, delegate { throw new Exception("Protected rule was prompted"); }, noAdd)) throw new Exception("Existing trust was changed");
        var steps = new List<string>();
        if (!TrustWorkflow(new[] { missing }, delegate { steps.Add("confirm"); return DialogResult.Yes; }, delegate { steps.Add("add"); })
            || string.Join(",", steps) != "confirm,add") throw new Exception("Trust was written without confirmation");
        steps.Clear(); rejected = false;
        try { NasSiteTrust.ApplyTransaction(new[] { "one" }, delegate { throw new Exception("backup-failed"); }, delegate(string p) { steps.Add("add"); }, delegate { return true; }, delegate(string p) { steps.Add("remove"); }); } catch { rejected = true; }
        if (!rejected || steps.Count != 0) throw new Exception("Write happened before backup");
        steps.Clear(); rejected = false;
        try { NasSiteTrust.ApplyTransaction(new[] { "one", "two" }, delegate { steps.Add("backup"); }, delegate(string p) { if (p == "two") throw new Exception("add-failed"); steps.Add("add-" + p); }, delegate { throw new Exception("Must not verify partial additions"); }, delegate(string p) { steps.Add("remove-" + p); }); } catch { rejected = true; }
        if (!rejected || string.Join(",", steps) != "backup,add-one,remove-one") throw new Exception("Partial addition rollback changed a prior rule");
        steps.Clear(); rejected = false;
        try { NasSiteTrust.ApplyTransaction(new[] { "one", "two" }, delegate { steps.Add("backup"); }, delegate(string p) { steps.Add("add-" + p); }, delegate { steps.Add("verify"); return false; }, delegate(string p) { steps.Add("remove-" + p); }); } catch { rejected = true; }
        if (!rejected || string.Join(",", steps) != "backup,add-one,add-two,verify,remove-two,remove-one") throw new Exception("Failed verification was reported as success");
        steps.Clear();
        NasSiteTrust.ApplyTransaction(new[] { "one" }, delegate { steps.Add("backup"); }, delegate(string p) { steps.Add("add"); }, delegate { steps.Add("verify"); return true; }, delegate(string p) { throw new Exception("Successful trust removed"); });
        if (string.Join(",", steps) != "backup,add,verify") throw new Exception("Successful addition order failed");
        rejected = false;
        try { NasSiteTrust.ApplyTransaction(new[] { "one" }, delegate { }, delegate(string p) { }, delegate { return false; }, delegate(string p) { throw new Exception("rollback-failed"); }); }
        catch (Exception e) { rejected = e.Message.Contains("无法撤回"); }
        if (!rejected) throw new Exception("Rollback failure was hidden");
    }
}
