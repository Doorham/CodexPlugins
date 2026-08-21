using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace CompanyAIHelpers.ArctisNova5BatteryMonitor
{
    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            bool created;
            using (var mutex = new Mutex(true, @"Local\Nova5BatteryTrayMutex", out created))
            {
                if (!created) return;
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new TrayContext());
            }
        }
    }

    internal sealed class TrayContext : ApplicationContext
    {
        private readonly NotifyIcon tray;
        private readonly ToolStripMenuItem statusItem;
        private readonly System.Windows.Forms.Timer timer;
        private Icon currentIcon;
        private bool refreshing;

        [DllImport("user32.dll", CharSet = CharSet.Auto)]
        private static extern bool DestroyIcon(IntPtr handle);

        internal TrayContext()
        {
            statusItem = new ToolStripMenuItem("正在读取 Nova 5…") { Enabled = false };
            var refreshItem = new ToolStripMenuItem("立即刷新");
            refreshItem.Click += delegate { RefreshBattery(); };
            var exitItem = new ToolStripMenuItem("退出监控");
            exitItem.Click += delegate { ExitThread(); };
            var menu = new ContextMenuStrip();
            menu.Items.Add(statusItem);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add(refreshItem);
            menu.Items.Add(exitItem);

            currentIcon = ModernIcon.Create("--", Color.FromArgb(51, 65, 85));
            tray = new NotifyIcon
            {
                Visible = true,
                Icon = currentIcon,
                Text = "Arctis Nova 5 电量监控",
                ContextMenuStrip = menu
            };
            tray.DoubleClick += delegate { RefreshBattery(); };
            timer = new System.Windows.Forms.Timer { Interval = 60000 };
            timer.Tick += delegate { RefreshBattery(); };
            timer.Start();
            RefreshBattery();
        }

        private void RefreshBattery()
        {
            if (refreshing) return;
            refreshing = true;
            try
            {
                BatteryReading reading = ArctisHid.ReadBattery();
                if (!reading.Online)
                {
                    statusItem.Text = "Arctis Nova 5 离线";
                    tray.Text = "Arctis Nova 5：离线";
                    SetIcon(ModernIcon.Create("--", Color.FromArgb(51, 65, 85)));
                    return;
                }

                string charging = reading.Charging ? " · 充电中" : string.Empty;
                statusItem.Text = string.Format("Arctis Nova 5：{0}%{1}", reading.Percent, charging);
                tray.Text = Truncate(statusItem.Text);
                Color color = reading.Percent < 15
                    ? Color.FromArgb(220, 38, 38)
                    : reading.Percent < 31
                        ? Color.FromArgb(239, 68, 68)
                        : reading.Charging
                            ? Color.FromArgb(14, 165, 233)
                            : Color.FromArgb(2, 132, 199);
                SetIcon(ModernIcon.Create(reading.Percent.ToString(), color));
            }
            catch
            {
                statusItem.Text = "Arctis Nova 5 离线";
                tray.Text = "Arctis Nova 5：离线";
                SetIcon(ModernIcon.Create("--", Color.FromArgb(51, 65, 85)));
            }
            finally
            {
                refreshing = false;
            }
        }

        private void SetIcon(Icon icon)
        {
            Icon previous = currentIcon;
            currentIcon = icon;
            tray.Icon = currentIcon;
            if (previous != null) previous.Dispose();
        }

        private static string Truncate(string value)
        {
            return value.Length <= 63 ? value : value.Substring(0, 63);
        }

        protected override void ExitThreadCore()
        {
            timer.Stop();
            tray.Visible = false;
            tray.Dispose();
            if (currentIcon != null) currentIcon.Dispose();
            base.ExitThreadCore();
        }
    }

    internal static class ModernIcon
    {
        [DllImport("user32.dll", CharSet = CharSet.Auto)]
        private static extern bool DestroyIcon(IntPtr handle);

        internal static Icon Create(string text, Color accent)
        {
            using (var bitmap = new Bitmap(32, 32, System.Drawing.Imaging.PixelFormat.Format32bppArgb))
            using (var graphics = Graphics.FromImage(bitmap))
            using (var shape = RoundedRectangle(new RectangleF(1, 1, 30, 30), 7))
            using (var fill = new LinearGradientBrush(
                new PointF(2, 2), new PointF(30, 30),
                ControlPaint.Light(accent, 0.08f), ControlPaint.Dark(accent, 0.18f)))
            using (var border = new Pen(Color.FromArgb(150, 255, 255, 255), 1.2f))
            using (var font = new Font("Segoe UI", text.Length >= 3 ? 8.0f : 10.0f, FontStyle.Bold, GraphicsUnit.Point))
            {
                graphics.SmoothingMode = SmoothingMode.AntiAlias;
                graphics.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
                graphics.FillPath(fill, shape);
                graphics.DrawPath(border, shape);
                TextRenderer.DrawText(
                    graphics,
                    text,
                    font,
                    new Rectangle(1, 1, 30, 30),
                    Color.White,
                    Color.Transparent,
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter |
                    TextFormatFlags.NoPadding | TextFormatFlags.SingleLine);
                IntPtr handle = bitmap.GetHicon();
                try { return (Icon)Icon.FromHandle(handle).Clone(); }
                finally { DestroyIcon(handle); }
            }
        }

        private static GraphicsPath RoundedRectangle(RectangleF bounds, float radius)
        {
            float diameter = radius * 2;
            var path = new GraphicsPath();
            path.AddArc(bounds.Left, bounds.Top, diameter, diameter, 180, 90);
            path.AddArc(bounds.Right - diameter, bounds.Top, diameter, diameter, 270, 90);
            path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
            path.AddArc(bounds.Left, bounds.Bottom - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    internal sealed class BatteryReading
    {
        internal bool Online;
        internal int Percent;
        internal bool Charging;
    }

    internal static class ArctisHid
    {
        private const uint DigcfPresent = 0x00000002;
        private const uint DigcfDeviceInterface = 0x00000010;
        private const uint GenericRead = 0x80000000;
        private const uint GenericWrite = 0x40000000;
        private const uint FileShareRead = 0x00000001;
        private const uint FileShareWrite = 0x00000002;
        private const uint OpenExisting = 3;
        private const uint FileFlagOverlapped = 0x40000000;
        private const int ErrorIoPending = 997;
        private const uint WaitObject0 = 0;
        private const uint IoTimeoutMs = 800;
        private const string ReceiverId = "vid_1038&pid_2232&mi_03";
        private static readonly IntPtr InvalidHandleValue = new IntPtr(-1);

        [StructLayout(LayoutKind.Sequential)]
        private struct SpDeviceInterfaceData
        {
            public int CbSize;
            public Guid InterfaceClassGuid;
            public int Flags;
            public IntPtr Reserved;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct NativeOverlapped
        {
            public IntPtr Internal;
            public IntPtr InternalHigh;
            public uint Offset;
            public uint OffsetHigh;
            public IntPtr EventHandle;
        }

        [DllImport("hid.dll")]
        private static extern void HidD_GetHidGuid(out Guid hidGuid);

        [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr SetupDiGetClassDevs(
            ref Guid classGuid, IntPtr enumerator, IntPtr parentWindow, uint flags);

        [DllImport("setupapi.dll", SetLastError = true)]
        private static extern bool SetupDiEnumDeviceInterfaces(
            IntPtr deviceInfoSet, IntPtr deviceInfoData, ref Guid interfaceClassGuid,
            uint memberIndex, ref SpDeviceInterfaceData deviceInterfaceData);

        [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool SetupDiGetDeviceInterfaceDetail(
            IntPtr deviceInfoSet, ref SpDeviceInterfaceData deviceInterfaceData,
            IntPtr deviceInterfaceDetailData, uint deviceInterfaceDetailDataSize,
            out uint requiredSize, IntPtr deviceInfoData);

        [DllImport("setupapi.dll")]
        private static extern bool SetupDiDestroyDeviceInfoList(IntPtr deviceInfoSet);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateFile(
            string fileName, uint desiredAccess, uint shareMode, IntPtr securityAttributes,
            uint creationDisposition, uint flagsAndAttributes, IntPtr templateFile);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr CreateEvent(
            IntPtr eventAttributes, bool manualReset, bool initialState, string name);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool WriteFile(
            IntPtr file, byte[] buffer, uint bytesToWrite, out uint bytesWritten,
            ref NativeOverlapped overlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool ReadFile(
            IntPtr file, byte[] buffer, uint bytesToRead, out uint bytesRead,
            ref NativeOverlapped overlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool GetOverlappedResult(
            IntPtr file, ref NativeOverlapped overlapped, out uint transferred, bool wait);

        [DllImport("kernel32.dll")]
        private static extern bool CancelIo(IntPtr handle);

        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);

        internal static BatteryReading ReadBattery()
        {
            string path = FindDevicePath();
            if (string.IsNullOrEmpty(path)) return new BatteryReading();
            IntPtr device = CreateFile(
                path, GenericRead | GenericWrite, FileShareRead | FileShareWrite,
                IntPtr.Zero, OpenExisting, FileFlagOverlapped, IntPtr.Zero);
            if (device == InvalidHandleValue) return new BatteryReading();
            try
            {
                byte[] outgoing = new byte[65];
                outgoing[1] = 0xB0;
                byte[] incoming = new byte[65];
                if (!Transfer(device, outgoing, true) || !Transfer(device, incoming, false))
                    return new BatteryReading();
                if (incoming.Length < 6 || incoming[2] == 2) return new BatteryReading();
                return new BatteryReading
                {
                    Online = true,
                    Percent = Math.Min((int)incoming[4], 100),
                    Charging = incoming[5] == 1
                };
            }
            finally { CloseHandle(device); }
        }

        private static bool Transfer(IntPtr device, byte[] buffer, bool write)
        {
            IntPtr eventHandle = CreateEvent(IntPtr.Zero, true, false, null);
            if (eventHandle == IntPtr.Zero) return false;
            var overlapped = new NativeOverlapped { EventHandle = eventHandle };
            uint transferred;
            try
            {
                bool completed = write
                    ? WriteFile(device, buffer, (uint)buffer.Length, out transferred, ref overlapped)
                    : ReadFile(device, buffer, (uint)buffer.Length, out transferred, ref overlapped);
                if (!completed && Marshal.GetLastWin32Error() != ErrorIoPending) return false;
                if (!completed)
                {
                    if (WaitForSingleObject(eventHandle, IoTimeoutMs) != WaitObject0)
                    {
                        CancelIo(device);
                        return false;
                    }
                    completed = GetOverlappedResult(device, ref overlapped, out transferred, false);
                }
                return completed && transferred > 0;
            }
            finally { CloseHandle(eventHandle); }
        }

        private static string FindDevicePath()
        {
            Guid hidGuid;
            HidD_GetHidGuid(out hidGuid);
            IntPtr info = SetupDiGetClassDevs(
                ref hidGuid, IntPtr.Zero, IntPtr.Zero, DigcfPresent | DigcfDeviceInterface);
            if (info == IntPtr.Zero || info == InvalidHandleValue) return null;
            try
            {
                for (uint index = 0; ; index++)
                {
                    var interfaceData = new SpDeviceInterfaceData();
                    interfaceData.CbSize = Marshal.SizeOf(typeof(SpDeviceInterfaceData));
                    if (!SetupDiEnumDeviceInterfaces(
                        info, IntPtr.Zero, ref hidGuid, index, ref interfaceData)) return null;
                    uint required;
                    SetupDiGetDeviceInterfaceDetail(
                        info, ref interfaceData, IntPtr.Zero, 0, out required, IntPtr.Zero);
                    if (required == 0) continue;
                    IntPtr detail = Marshal.AllocHGlobal((int)required);
                    try
                    {
                        Marshal.WriteInt32(detail, IntPtr.Size == 8 ? 8 : 6);
                        if (!SetupDiGetDeviceInterfaceDetail(
                            info, ref interfaceData, detail, required, out required, IntPtr.Zero))
                            continue;
                        string path = Marshal.PtrToStringUni(IntPtr.Add(detail, 4));
                        if (path != null && path.IndexOf(
                            ReceiverId, StringComparison.OrdinalIgnoreCase) >= 0) return path;
                    }
                    finally { Marshal.FreeHGlobal(detail); }
                }
            }
            finally { SetupDiDestroyDeviceInfoList(info); }
        }
    }
}
