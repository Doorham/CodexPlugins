using System.Net;
using System.Net.Http.Headers;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace CompanyAIHelpers.UpdreamBridge;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new ConfigWindow());
    }
}

internal sealed class ConfigWindow : Form
{
    private const string ExportCode = "copy(JSON.stringify({access_token:localStorage.getItem('access_token'),refresh_token:localStorage.getItem('refresh_token'),project_id:new URL(location.href).searchParams.get('project')}))";
    private const int WmNcLButtonDown = 0xA1;
    private const int WmNcHitTest = 0x84;
    private const int HtCaption = 0x2;
    private readonly WebView2 browser = new() { Dock = DockStyle.Fill };
    private readonly string htmlPath = Path.Combine(AppContext.BaseDirectory, "index.html");
    private GuideWindow? guideWindow;
    private Rectangle? boundsBeforeGuide;
    private Rectangle? tiledBounds;

    [DllImport("user32.dll")]
    private static extern bool ReleaseCapture();

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr hWnd, int msg, int wParam, int lParam);

    [DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr hWnd);

    public ConfigWindow()
    {
        Text = "UpdreamBridge · 账号配置";
        StartPosition = FormStartPosition.Manual;
        FormBorderStyle = FormBorderStyle.None;
        BackColor = Color.FromArgb(13, 18, 29);
        Padding = Padding.Empty;
        var screen = Screen.FromPoint(Cursor.Position);
        var preset = screen.Bounds.Height >= 2000 ? new Size(2560, 1440)
            : screen.Bounds.Height >= 1300 ? new Size(1920, 1080)
            : new Size(1280, 720);
        int width = Math.Min(preset.Width, screen.WorkingArea.Width - 24);
        int height = Math.Min(preset.Height, screen.WorkingArea.Height - 24);
        MinimumSize = new Size(Math.Min(850, width), Math.Min(620, height));
        Bounds = new Rectangle(
            screen.WorkingArea.Left + (screen.WorkingArea.Width - width) / 2,
            screen.WorkingArea.Top + (screen.WorkingArea.Height - height) / 2,
            width, height);
        Controls.Add(browser);
        Shown += InitializeBrowser;
        DpiChanged += (_, _) => ApplyZoom();
        Resize += (_, _) => ApplyZoom();
    }

    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if (message.Msg != WmNcHitTest || message.Result != (IntPtr)1) return;
        var point = PointToClient(Cursor.Position);
        bool left = point.X < 8, right = point.X >= Width - 8;
        bool top = point.Y < 8, bottom = point.Y >= Height - 8;
        int edge = top && left ? 13 : top && right ? 14 : bottom && left ? 16 : bottom && right ? 17
            : left ? 10 : right ? 11 : top ? 12 : bottom ? 15 : 0;
        if (edge != 0) message.Result = (IntPtr)edge;
    }

    private async void InitializeBrowser(object? sender, EventArgs args)
    {
        try
        {
            if (!File.Exists(htmlPath)) throw new FileNotFoundException("配置界面文件不存在");
            var dataPath = Path.Combine(AppContext.BaseDirectory, "webview2-data");
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: dataPath);
            await browser.EnsureCoreWebView2Async(environment);
            ApplyZoom();
            browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
            browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            browser.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled = false;
            browser.CoreWebView2.Settings.IsStatusBarEnabled = false;
            browser.CoreWebView2.WebMessageReceived += HandleMessage;
            browser.CoreWebView2.NavigationStarting += (_, navigation) =>
            {
                if (!IsLocalPage(navigation.Uri)) navigation.Cancel = true;
            };
            browser.Source = new Uri(htmlPath);
        }
        catch (Exception ex)
        {
            MessageBox.Show("UpdreamBridge 配置界面启动失败：" + ex.Message, "UpdreamBridge", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }
    }

    private void ApplyZoom()
    {
        if (browser.CoreWebView2 == null) return;
        uint dpi = GetDpiForWindow(Handle);
        double contentScale = Math.Clamp(browser.ClientSize.Width / 1280.0, 1.0, 2.0);
        browser.ZoomFactor = (dpi > 0 ? 96.0 / dpi : 1.0) * contentScale;
    }

    private bool IsLocalPage(string source)
    {
        try
        {
            var uri = new Uri(source);
            return uri.IsFile && string.Equals(Path.GetFullPath(uri.LocalPath), Path.GetFullPath(htmlPath), StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    private async void HandleMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs args)
    {
        if (!IsLocalPage(args.Source)) return;
        try
        {
            using var document = JsonDocument.Parse(args.WebMessageAsJson);
            var root = document.RootElement;
            string? action = FieldText(root, "action");
            switch (action)
            {
                case "copy":
                    Clipboard.SetText(ExportCode);
                    SendStatus("代码已复制。回到 UpDream 的 Console 粘贴并回车。", false);
                    break;
                case "save":
                    SendStatus("正在验证 UpDream 登录状态…", false, true);
                    try
                    {
                        var payload = root.GetProperty("payload");
                        string username = await VerifyAndSave(payload);
                        SendStatus("配置成功，账号：" + username + "。现在可以调用 UpDream 生图。", false, false, true);
                    }
                    catch (Exception ex)
                    {
                        SendStatus("验证或保存失败：" + ex.Message, true);
                    }
                    break;
                case "minimize":
                    WindowState = FormWindowState.Minimized;
                    break;
                case "close":
                    Close();
                    break;
                case "openGuide":
                    OpenGuide();
                    break;
                case "drag":
                    ReleaseCapture();
                    SendMessage(Handle, WmNcLButtonDown, HtCaption, 0);
                    break;
                case "resize":
                    int edge = ResizeHitTest(FieldText(root.GetProperty("payload"), "edge"));
                    if (edge != 0)
                    {
                        ReleaseCapture();
                        SendMessage(Handle, WmNcLButtonDown, edge, 0);
                    }
                    break;
            }
        }
        catch (JsonException)
        {
            SendStatus("输入格式有误，请粘贴控制台复制的 JSON。", true);
        }
    }

    internal static int ResizeHitTest(string? edge) => edge switch
    {
        "left" => 10, "right" => 11, "top" => 12, "top-left" => 13,
        "top-right" => 14, "bottom" => 15, "bottom-left" => 16, "bottom-right" => 17,
        _ => 0
    };

    private void OpenGuide()
    {
        if (guideWindow is { IsDisposed: false })
        {
            guideWindow.Activate();
            return;
        }

        var guide = new GuideWindow();
        var work = Screen.FromControl(this).WorkingArea;
        const int margin = 16, gap = 16;
        int guideWidth = Math.Min(1100, Math.Max(480, (int)(work.Width * 0.32)));
        int mainWidth = Math.Min(Width, work.Width - 2 * margin - gap - guideWidth);
        int guideHeight = Math.Min(1500, work.Height - 2 * margin);
        if (mainWidth >= MinimumSize.Width)
        {
            boundsBeforeGuide = Bounds;
            int mainHeight = Math.Min(Height, work.Height - 2 * margin);
            int rowHeight = Math.Max(mainHeight, guideHeight);
            int rowTop = work.Top + (work.Height - rowHeight) / 2;
            Bounds = new Rectangle(work.Left + margin, rowTop + (rowHeight - mainHeight) / 2, mainWidth, mainHeight);
            tiledBounds = Bounds;
            guide.Bounds = new Rectangle(Right + gap, rowTop + (rowHeight - guideHeight) / 2, guideWidth, guideHeight);
        }
        else
        {
            boundsBeforeGuide = null;
            tiledBounds = null;
            var otherScreen = Screen.AllScreens.FirstOrDefault(screen => screen != Screen.FromControl(this) && screen.WorkingArea.Width >= 600);
            var guideWork = otherScreen?.WorkingArea ?? work;
            guideWidth = Math.Min(1100, guideWork.Width - 2 * margin);
            guideHeight = Math.Min(1500, guideWork.Height - 2 * margin);
            guide.Bounds = new Rectangle(
                guideWork.Left + (guideWork.Width - guideWidth) / 2,
                guideWork.Top + (guideWork.Height - guideHeight) / 2,
                guideWidth, guideHeight);
        }

        guide.FormClosed += (_, _) =>
        {
            guideWindow = null;
            if (!IsDisposed && tiledBounds.HasValue && boundsBeforeGuide.HasValue && Bounds == tiledBounds.Value)
                Bounds = boundsBeforeGuide.Value;
            boundsBeforeGuide = null;
            tiledBounds = null;
        };
        guideWindow = guide;
        guide.Show(this);
    }

    private void SendStatus(string message, bool error, bool busy = false, bool clear = false)
    {
        if (browser.CoreWebView2 == null || IsDisposed) return;
        browser.CoreWebView2.PostWebMessageAsJson(JsonSerializer.Serialize(new { type = "status", message, error, busy, clear }));
    }

    private static string? FieldText(JsonElement element, string field)
    {
        if (element.ValueKind != JsonValueKind.Object || !element.TryGetProperty(field, out var value)) return null;
        return value.ValueKind == JsonValueKind.String ? value.GetString()?.Trim() : null;
    }

    private static async Task<string> VerifyAndSave(JsonElement payload)
    {
        if (payload.ValueKind != JsonValueKind.Object || payload.TryGetProperty("cookies", out _) || payload.TryGetProperty("storage", out _))
            throw new InvalidOperationException("请使用此窗口提供的新代码；不要粘贴整份 Cookie 或 localStorage。");
        string access = FieldText(payload, "access_token") ?? "";
        string refresh = FieldText(payload, "refresh_token") ?? "";
        string project = FieldText(payload, "project_id") ?? "";
        if (access.Length == 0) throw new InvalidOperationException("未找到 access_token，请确认已登录 UpDream。");
        if (project.Length == 0) throw new InvalidOperationException("未找到项目 ID，请进入画布页后重新执行代码。");

        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
        using var request = new HttpRequestMessage(HttpMethod.Get, "https://www.updream.cn/api/auth/me");
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", access);
        request.Headers.UserAgent.ParseAdd("Mozilla/5.0");
        request.Headers.Referrer = new Uri("https://www.updream.cn/");
        HttpResponseMessage response;
        try { response = await client.SendAsync(request); }
        catch (HttpRequestException) { throw new InvalidOperationException("无法连接 UpDream，请检查网络后重试。"); }
        catch (TaskCanceledException) { throw new InvalidOperationException("连接 UpDream 超时，请稍后重试。"); }
        using (response)
        {
            if (response.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
                throw new InvalidOperationException("登录信息无效或已过期，请重新登录后复制。");
            if (!response.IsSuccessStatusCode)
                throw new InvalidOperationException("UpDream 验证失败，HTTP " + (int)response.StatusCode);
            using var account = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            string id = AccountField(account.RootElement, "id");
            if (id.Length == 0) throw new InvalidOperationException("UpDream 未返回有效账号信息。");
            string username = AccountField(account.RootElement, "username");
            if (username.Length == 0) username = id;
            var saved = new {
                access_token = access, refresh_token = refresh, project_id = project,
                user_id = id, username, expires_at = TokenExpiry(access)
            };
            string folder = AppContext.BaseDirectory;
            Directory.CreateDirectory(folder);
            string target = Path.Combine(folder, "credentials.json");
            string temporary = Path.Combine(folder, "credentials-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                await File.WriteAllTextAsync(temporary, JsonSerializer.Serialize(saved), new UTF8Encoding(false));
                if (File.Exists(target)) File.Replace(temporary, target, null);
                else File.Move(temporary, target);
            }
            finally
            {
                if (File.Exists(temporary)) File.Delete(temporary);
            }
            return username;
        }
    }

    private static string AccountField(JsonElement root, string field)
    {
        if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty(field, out var value)) return "";
        return value.ValueKind == JsonValueKind.String ? value.GetString()?.Trim() ?? "" : value.ToString();
    }

    private static string TokenExpiry(string token)
    {
        try
        {
            string part = token.Split('.')[1].Replace('-', '+').Replace('_', '/');
            part = part.PadRight(part.Length + ((4 - part.Length % 4) % 4), '=');
            using var payload = JsonDocument.Parse(Convert.FromBase64String(part));
            if (payload.RootElement.TryGetProperty("exp", out var exp))
                return DateTimeOffset.FromUnixTimeSeconds(exp.GetInt64()).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss");
        }
        catch { }
        return "未知";
    }
}

internal sealed class GuideWindow : Form
{
    private const int WmNcLButtonDown = 0xA1;
    private const int WmNcHitTest = 0x84;
    private const int HtCaption = 0x2;
    private readonly WebView2 browser = new() { Dock = DockStyle.Fill };
    private readonly string htmlPath = Path.Combine(AppContext.BaseDirectory, "guide-window.html");

    [DllImport("user32.dll")]
    private static extern bool ReleaseCapture();

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr hWnd, int msg, int wParam, int lParam);

    public GuideWindow()
    {
        Text = "配置指引";
        StartPosition = FormStartPosition.Manual;
        FormBorderStyle = FormBorderStyle.None;
        BackColor = Color.FromArgb(21, 31, 50);
        Padding = Padding.Empty;
        MinimumSize = new Size(450, 480);
        Controls.Add(browser);
        Shown += InitializeBrowser;
    }

    protected override void WndProc(ref Message message)
    {
        base.WndProc(ref message);
        if (message.Msg != WmNcHitTest || message.Result != (IntPtr)1) return;
        var point = PointToClient(Cursor.Position);
        bool left = point.X < 8, right = point.X >= Width - 8;
        bool top = point.Y < 8, bottom = point.Y >= Height - 8;
        int edge = top && left ? 13 : top && right ? 14 : bottom && left ? 16 : bottom && right ? 17
            : left ? 10 : right ? 11 : top ? 12 : bottom ? 15 : 0;
        if (edge != 0) message.Result = (IntPtr)edge;
    }

    private async void InitializeBrowser(object? sender, EventArgs args)
    {
        try
        {
            if (!File.Exists(htmlPath)) throw new FileNotFoundException("配置指引文件不存在");
            var dataPath = Path.Combine(AppContext.BaseDirectory, "webview2-data");
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: dataPath);
            await browser.EnsureCoreWebView2Async(environment);
            browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
            browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            browser.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled = false;
            browser.CoreWebView2.Settings.IsStatusBarEnabled = false;
            browser.CoreWebView2.WebMessageReceived += HandleMessage;
            browser.CoreWebView2.NavigationStarting += (_, navigation) =>
            {
                if (!string.Equals(new Uri(navigation.Uri).LocalPath, htmlPath, StringComparison.OrdinalIgnoreCase))
                    navigation.Cancel = true;
            };
            browser.Source = new Uri(htmlPath);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, "配置指引启动失败：" + ex.Message, "UpdreamBridge", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }
    }

    private void HandleMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs args)
    {
        if (!string.Equals(new Uri(args.Source).LocalPath, htmlPath, StringComparison.OrdinalIgnoreCase)) return;
        try
        {
            using var document = JsonDocument.Parse(args.WebMessageAsJson);
            string? action = document.RootElement.GetProperty("action").GetString();
            switch (action)
            {
                case "close":
                    Close();
                    break;
                case "drag":
                    ReleaseCapture();
                    SendMessage(Handle, WmNcLButtonDown, HtCaption, 0);
                    break;
                case "resize":
                    string? edge = document.RootElement.TryGetProperty("payload", out var payload)
                        && payload.ValueKind == JsonValueKind.Object
                        && payload.TryGetProperty("edge", out var value)
                        && value.ValueKind == JsonValueKind.String ? value.GetString() : null;
                    int hit = ConfigWindow.ResizeHitTest(edge);
                    if (hit != 0)
                    {
                        ReleaseCapture();
                        SendMessage(Handle, WmNcLButtonDown, hit, 0);
                    }
                    break;
            }
        }
        catch (JsonException) { }
    }
}
