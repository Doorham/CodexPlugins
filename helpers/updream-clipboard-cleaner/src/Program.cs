using System;
using System.Collections;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace CompanyAIHelpers.UpdreamClipboardCleaner
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            bool created;
            using (var mutex = new Mutex(true, @"Local\CompanyAIHelpers.UpdreamClipboardCleaner", out created))
            {
                if (!created) return;
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                using (var listener = new ClipboardListener())
                    Application.Run();
            }
        }
    }

    sealed class ClipboardListener : NativeWindow, IDisposable
    {
        const int WM_CLIPBOARDUPDATE = 0x031D;
        const uint CF_TEXT = 1;
        const uint CF_BITMAP = 2;
        const uint CF_DIB = 8;
        const uint CF_UNICODETEXT = 13;
        const uint CF_DIBV5 = 17;
        const uint GMEM_MOVEABLE = 0x0002;
        const uint IMAGE_BITMAP = 0;
        const uint LR_CREATEDIBSECTION = 0x00002000;
        static readonly byte[] PngSignature = { 137, 80, 78, 71, 13, 10, 26, 10 };

        public ClipboardListener()
        {
            CreateHandle(new CreateParams());
            AddClipboardFormatListener(Handle);
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == WM_CLIPBOARDUPDATE) TryCleanClipboard();
            base.WndProc(ref m);
        }

        void TryCleanClipboard()
        {
            for (int attempt = 0; attempt < 8; attempt++)
            {
                if (OpenClipboard(Handle))
                {
                    try { CleanClipboardIfNeeded(); }
                    catch { }
                    finally { CloseClipboard(); }
                    return;
                }
                Thread.Sleep(15);
            }
        }

        void CleanClipboardIfNeeded()
        {
            uint pngFormat;
            byte[] pngBytes;
            if (!TryGetRealPng(out pngFormat, out pngBytes)) return;
            if (!HasCanvasNodesJson()) return;

            // Preserve the original PNG bytes exactly. Many paste targets do not
            // understand the registered PNG format and require derived
            // CF_DIB/CF_DIBV5/CF_BITMAP, even though all represent the same image.
            byte[] dibBytes = ReadGlobalBytes(CF_DIB, 256 * 1024 * 1024);
            byte[] dibV5Bytes = ReadGlobalBytes(CF_DIBV5, 256 * 1024 * 1024);
            try
            {
                byte[] generatedDib;
                byte[] generatedDibV5;
                CreateDibPayloads(pngBytes, out generatedDib, out generatedDibV5);
                dibBytes = generatedDib;
                dibV5Bytes = generatedDibV5;
            }
            catch
            {
                // Keep any source-provided compatibility formats and preserve the exact
                // PNG if an unusual but structurally valid image cannot be decoded.
            }
            IntPtr sourceBitmap = GetClipboardData(CF_BITMAP);
            IntPtr bitmapCopy = sourceBitmap == IntPtr.Zero ? IntPtr.Zero :
                CopyImage(sourceBitmap, IMAGE_BITMAP, 0, 0, LR_CREATEDIBSECTION);

            IntPtr pngCopy = AllocateGlobal(pngBytes);
            IntPtr dibCopy = AllocateGlobal(dibBytes);
            IntPtr dibV5Copy = AllocateGlobal(dibV5Bytes);
            if (pngCopy == IntPtr.Zero)
            {
                FreeOwnedHandles(pngCopy, dibCopy, dibV5Copy, bitmapCopy);
                return;
            }

            if (!EmptyClipboard())
            {
                FreeOwnedHandles(pngCopy, dibCopy, dibV5Copy, bitmapCopy);
                return;
            }
            SetOwnedClipboardData(pngFormat, ref pngCopy, false);
            SetOwnedClipboardData(CF_DIB, ref dibCopy, false);
            SetOwnedClipboardData(CF_DIBV5, ref dibV5Copy, false);
            SetOwnedClipboardData(CF_BITMAP, ref bitmapCopy, true);
            FreeOwnedHandles(pngCopy, dibCopy, dibV5Copy, bitmapCopy);
        }

        static IntPtr AllocateGlobal(byte[] bytes)
        {
            if (bytes == null || bytes.Length == 0) return IntPtr.Zero;
            IntPtr handle = GlobalAlloc(GMEM_MOVEABLE, (UIntPtr)bytes.Length);
            if (handle == IntPtr.Zero) return IntPtr.Zero;
            IntPtr target = GlobalLock(handle);
            if (target == IntPtr.Zero) { GlobalFree(handle); return IntPtr.Zero; }
            Marshal.Copy(bytes, 0, target, bytes.Length);
            GlobalUnlock(handle);
            return handle;
        }

        static void SetOwnedClipboardData(uint format, ref IntPtr handle, bool gdiObject)
        {
            if (handle == IntPtr.Zero) return;
            if (SetClipboardData(format, handle) != IntPtr.Zero) handle = IntPtr.Zero;
        }

        static void FreeOwnedHandles(IntPtr png, IntPtr dib, IntPtr dibV5, IntPtr bitmap)
        {
            if (png != IntPtr.Zero) GlobalFree(png);
            if (dib != IntPtr.Zero) GlobalFree(dib);
            if (dibV5 != IntPtr.Zero) GlobalFree(dibV5);
            if (bitmap != IntPtr.Zero) DeleteObject(bitmap);
        }

        static void CreateDibPayloads(byte[] pngBytes, out byte[] dib, out byte[] dibV5)
        {
            using (var stream = new MemoryStream(pngBytes, false))
            using (var source = Image.FromStream(stream, false, true))
            using (var bitmap = new Bitmap(source.Width, source.Height, PixelFormat.Format32bppArgb))
            {
                using (var graphics = Graphics.FromImage(bitmap))
                {
                    graphics.CompositingMode = CompositingMode.SourceCopy;
                    graphics.DrawImageUnscaled(source, 0, 0);
                }

                int width = bitmap.Width;
                int height = bitmap.Height;
                int rowBytes = checked(width * 4);
                byte[] pixels = new byte[checked(rowBytes * height)];
                var rectangle = new Rectangle(0, 0, width, height);
                BitmapData data = bitmap.LockBits(rectangle, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                try
                {
                    byte[] sourceRow = new byte[rowBytes];
                    for (int y = 0; y < height; y++)
                    {
                        IntPtr pointer = IntPtr.Add(data.Scan0, y * data.Stride);
                        Marshal.Copy(pointer, sourceRow, 0, rowBytes);
                        Buffer.BlockCopy(sourceRow, 0, pixels, (height - 1 - y) * rowBytes, rowBytes);
                    }
                }
                finally
                {
                    bitmap.UnlockBits(data);
                }

                dib = new byte[checked(40 + pixels.Length)];
                WriteBitmapInfoHeader(dib, width, height, pixels.Length, 0);
                Buffer.BlockCopy(pixels, 0, dib, 40, pixels.Length);

                dibV5 = new byte[checked(124 + pixels.Length)];
                WriteBitmapInfoHeader(dibV5, width, height, pixels.Length, 3);
                WriteInt32(dibV5, 0, 124);
                WriteUInt32(dibV5, 40, 0x00FF0000);
                WriteUInt32(dibV5, 44, 0x0000FF00);
                WriteUInt32(dibV5, 48, 0x000000FF);
                WriteUInt32(dibV5, 52, 0xFF000000);
                WriteUInt32(dibV5, 56, 0x73524742); // LCS_sRGB
                WriteUInt32(dibV5, 108, 4); // LCS_GM_IMAGES
                Buffer.BlockCopy(pixels, 0, dibV5, 124, pixels.Length);
            }
        }

        static void WriteBitmapInfoHeader(byte[] destination, int width, int height, int imageBytes, int compression)
        {
            WriteInt32(destination, 0, 40);
            WriteInt32(destination, 4, width);
            WriteInt32(destination, 8, height);
            WriteInt16(destination, 12, 1);
            WriteInt16(destination, 14, 32);
            WriteInt32(destination, 16, compression);
            WriteInt32(destination, 20, imageBytes);
        }

        static void WriteInt16(byte[] bytes, int offset, short value)
        {
            byte[] encoded = BitConverter.GetBytes(value);
            Buffer.BlockCopy(encoded, 0, bytes, offset, encoded.Length);
        }

        static void WriteInt32(byte[] bytes, int offset, int value)
        {
            byte[] encoded = BitConverter.GetBytes(value);
            Buffer.BlockCopy(encoded, 0, bytes, offset, encoded.Length);
        }

        static void WriteUInt32(byte[] bytes, int offset, uint value)
        {
            byte[] encoded = BitConverter.GetBytes(value);
            Buffer.BlockCopy(encoded, 0, bytes, offset, encoded.Length);
        }

        bool TryGetRealPng(out uint foundFormat, out byte[] bytes)
        {
            foundFormat = 0;
            bytes = null;
            uint format = 0;
            while ((format = EnumClipboardFormats(format)) != 0)
            {
                string name = GetFormatName(format);
                if (!string.Equals(name, "PNG", StringComparison.OrdinalIgnoreCase) &&
                    !string.Equals(name, "image/png", StringComparison.OrdinalIgnoreCase)) continue;
                byte[] candidate = ReadGlobalBytes(format, 128 * 1024 * 1024);
                if (!IsStructurallyValidPng(candidate)) continue;
                foundFormat = format;
                bytes = candidate;
                return true;
            }
            return false;
        }

        static bool IsStructurallyValidPng(byte[] bytes)
        {
            if (bytes == null || bytes.Length < 33) return false;
            for (int i = 0; i < PngSignature.Length; i++) if (bytes[i] != PngSignature[i]) return false;

            int offset = 8;
            bool sawHeader = false;
            while (offset + 12 <= bytes.Length)
            {
                uint length = ReadUInt32BigEndian(bytes, offset);
                if (length > int.MaxValue || (long)offset + 12L + length > bytes.Length) return false;
                string type = Encoding.ASCII.GetString(bytes, offset + 4, 4);
                if (!sawHeader)
                {
                    if (type != "IHDR" || length != 13) return false;
                    sawHeader = true;
                }
                offset += checked((int)length + 12);
                if (type == "IEND") return length == 0;
            }
            return false;
        }

        static uint ReadUInt32BigEndian(byte[] bytes, int offset)
        {
            return ((uint)bytes[offset] << 24) |
                   ((uint)bytes[offset + 1] << 16) |
                   ((uint)bytes[offset + 2] << 8) |
                   bytes[offset + 3];
        }

        bool HasCanvasNodesJson()
        {
            uint format = 0;
            while ((format = EnumClipboardFormats(format)) != 0)
            {
                string name = GetFormatName(format);
                bool namedCanvas = name.IndexOf("canvas-nodes", StringComparison.OrdinalIgnoreCase) >= 0;
                bool plausibleJson = name.IndexOf("json", StringComparison.OrdinalIgnoreCase) >= 0;
                string text = null;
                if (format == CF_UNICODETEXT) text = ReadUnicodeText(format);
                else if (format == CF_TEXT) text = ReadAnsiText(format);
                else if (namedCanvas || plausibleJson) text = DecodeText(ReadGlobalBytes(format, 4 * 1024 * 1024));
                if (IsCanvasNodesJson(text)) return true;
            }
            return false;
        }

        static bool IsCanvasNodesJson(string text)
        {
            if (string.IsNullOrWhiteSpace(text) || text.IndexOf("canvas-nodes", StringComparison.OrdinalIgnoreCase) < 0) return false;
            string trimmed = text.Trim();
            if (!(trimmed.StartsWith("{") || trimmed.StartsWith("["))) return false;
            try
            {
                object value = new JavaScriptSerializer { MaxJsonLength = 4 * 1024 * 1024 }.DeserializeObject(trimmed);
                return ContainsCanvasNodes(value);
            }
            catch { return false; }
        }

        static bool ContainsCanvasNodes(object value)
        {
            var dict = value as IDictionary<string, object>;
            if (dict != null)
            {
                foreach (var pair in dict)
                {
                    if (string.Equals(pair.Key, "canvas-nodes", StringComparison.OrdinalIgnoreCase)) return true;
                    if (ContainsCanvasNodes(pair.Value)) return true;
                }
            }
            var list = value as IEnumerable;
            if (list != null && !(value is string)) foreach (object item in list) if (ContainsCanvasNodes(item)) return true;
            string str = value as string;
            return str != null && string.Equals(str, "canvas-nodes", StringComparison.OrdinalIgnoreCase);
        }

        static string GetFormatName(uint format)
        {
            var sb = new StringBuilder(256);
            return GetClipboardFormatName(format, sb, sb.Capacity) > 0 ? sb.ToString() : string.Empty;
        }

        static byte[] ReadGlobalBytes(uint format, int maxBytes)
        {
            IntPtr handle = GetClipboardData(format);
            if (handle == IntPtr.Zero) return null;
            ulong size64 = GlobalSize(handle).ToUInt64();
            if (size64 == 0 || size64 > (ulong)maxBytes || size64 > int.MaxValue) return null;
            IntPtr ptr = GlobalLock(handle);
            if (ptr == IntPtr.Zero) return null;
            try { var result = new byte[(int)size64]; Marshal.Copy(ptr, result, 0, result.Length); return result; }
            finally { GlobalUnlock(handle); }
        }

        static string ReadUnicodeText(uint format)
        {
            IntPtr handle = GetClipboardData(format); if (handle == IntPtr.Zero) return null;
            IntPtr ptr = GlobalLock(handle); if (ptr == IntPtr.Zero) return null;
            try { return Marshal.PtrToStringUni(ptr); } finally { GlobalUnlock(handle); }
        }

        static string ReadAnsiText(uint format)
        {
            IntPtr handle = GetClipboardData(format); if (handle == IntPtr.Zero) return null;
            IntPtr ptr = GlobalLock(handle); if (ptr == IntPtr.Zero) return null;
            try { return Marshal.PtrToStringAnsi(ptr); } finally { GlobalUnlock(handle); }
        }

        static string DecodeText(byte[] bytes)
        {
            if (bytes == null || bytes.Length == 0) return null;
            try
            {
                if (bytes.Length >= 2 && bytes[1] == 0) return Encoding.Unicode.GetString(bytes).TrimEnd('\0');
                return Encoding.UTF8.GetString(bytes).TrimEnd('\0');
            }
            catch { return null; }
        }

        public void Dispose()
        {
            RemoveClipboardFormatListener(Handle);
            DestroyHandle();
        }

        [DllImport("user32.dll", SetLastError = true)] static extern bool AddClipboardFormatListener(IntPtr hwnd);
        [DllImport("user32.dll", SetLastError = true)] static extern bool RemoveClipboardFormatListener(IntPtr hwnd);
        [DllImport("user32.dll", SetLastError = true)] static extern bool OpenClipboard(IntPtr hwnd);
        [DllImport("user32.dll", SetLastError = true)] static extern bool CloseClipboard();
        [DllImport("user32.dll", SetLastError = true)] static extern bool EmptyClipboard();
        [DllImport("user32.dll", SetLastError = true)] static extern uint EnumClipboardFormats(uint format);
        [DllImport("user32.dll", SetLastError = true)] static extern IntPtr GetClipboardData(uint format);
        [DllImport("user32.dll", SetLastError = true)] static extern IntPtr SetClipboardData(uint format, IntPtr handle);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClipboardFormatName(uint format, StringBuilder name, int maxCount);
        [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr GlobalAlloc(uint flags, UIntPtr bytes);
        [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr GlobalFree(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr GlobalLock(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool GlobalUnlock(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError = true)] static extern UIntPtr GlobalSize(IntPtr handle);
        [DllImport("user32.dll", SetLastError = true)] static extern IntPtr CopyImage(IntPtr handle, uint type, int cx, int cy, uint flags);
        [DllImport("gdi32.dll", SetLastError = true)] static extern bool DeleteObject(IntPtr handle);
    }
}
