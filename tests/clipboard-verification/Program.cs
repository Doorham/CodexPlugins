using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

class ClipboardVerification
{
    const uint CF_UNICODETEXT = 13;
    const uint CF_DIB = 8;
    const uint CF_HDROP = 15;
    const uint CF_DIBV5 = 17;
    const uint GMEM_MOVEABLE = 2;
    static readonly uint PNG = RegisterClipboardFormat("PNG");
    static readonly byte[] PngBytes = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2J1cAAAAASUVORK5CYII=");
    static readonly byte[] DibBytes = CreateOnePixelDib();

    static int Main()
    {
        var results = new List<string>();

        SetClipboard(new Dictionary<uint, byte[]> {
            { PNG, PngBytes },
            { CF_UNICODETEXT, Encoding.Unicode.GetBytes("{\"type\":\"canvas-nodes\",\"nodes\":[]}\0") }
        });
        Thread.Sleep(900);
        var composite = Snapshot();
        bool compositeOk = composite.ContainsKey(PNG) && composite.ContainsKey(CF_DIB) && composite.ContainsKey(CF_DIBV5) &&
            !composite.ContainsKey(CF_UNICODETEXT) && Equal(composite[PNG], PngBytes) &&
            IsCompatibleDib(composite[CF_DIB], 40) && IsCompatibleDib(composite[CF_DIBV5], 124);
        results.Add("CompositePngCanvasNodes=" + (compositeOk ? "PASS" : "FAIL") + ";Formats=" + string.Join(",", composite.Keys));

        string ordinaryText = "ordinary clipboard text 2026-08-17";
        SetClipboard(new Dictionary<uint, byte[]> { { CF_UNICODETEXT, Encoding.Unicode.GetBytes(ordinaryText + "\0") } });
        Thread.Sleep(700);
        var textSnap = Snapshot();
        string returned = textSnap.ContainsKey(CF_UNICODETEXT) ? Encoding.Unicode.GetString(textSnap[CF_UNICODETEXT]).TrimEnd('\0') : null;
        bool textOk = returned == ordinaryText;
        results.Add("OrdinaryText=" + (textOk ? "PASS" : "FAIL") + ";Formats=" + string.Join(",", textSnap.Keys));

        string ordinaryJson = "{\"type\":\"ordinary-json\",\"nodes\":[]}";
        SetClipboard(new Dictionary<uint, byte[]> { { CF_UNICODETEXT, Encoding.Unicode.GetBytes(ordinaryJson + "\0") } });
        Thread.Sleep(700);
        var jsonSnap = Snapshot();
        string returnedJson = jsonSnap.ContainsKey(CF_UNICODETEXT) ? Encoding.Unicode.GetString(jsonSnap[CF_UNICODETEXT]).TrimEnd('\0') : null;
        bool jsonOk = returnedJson == ordinaryJson;
        results.Add("OrdinaryJson=" + (jsonOk ? "PASS" : "FAIL"));

        SetClipboard(new Dictionary<uint, byte[]> { { PNG, PngBytes } });
        Thread.Sleep(700);
        var imageSnap = Snapshot();
        bool imageOk = imageSnap.Count == 1 && imageSnap.ContainsKey(PNG) && Equal(imageSnap[PNG], PngBytes);
        results.Add("OrdinaryPng=" + (imageOk ? "PASS" : "FAIL"));

        byte[] fileDrop = CreateFileDrop();
        SetClipboard(new Dictionary<uint, byte[]> { { CF_HDROP, fileDrop } });
        Thread.Sleep(700);
        var fileSnap = Snapshot();
        bool fileOk = fileSnap.ContainsKey(CF_HDROP) && Equal(fileSnap[CF_HDROP], fileDrop);
        results.Add("OrdinaryFile=" + (fileOk ? "PASS" : "FAIL"));

        byte[] fakePng = { 137, 80, 78, 71, 13, 10, 26, 10, 0, 1, 2, 3 };
        byte[] canvasJson = Encoding.Unicode.GetBytes("{\"type\":\"canvas-nodes\"}\0");
        SetClipboard(new Dictionary<uint, byte[]> { { PNG, fakePng }, { CF_UNICODETEXT, canvasJson } });
        Thread.Sleep(700);
        var fakeSnap = Snapshot();
        bool fakeOk = fakeSnap.ContainsKey(PNG) && fakeSnap.ContainsKey(CF_UNICODETEXT) &&
            Equal(fakeSnap[PNG], fakePng) && Equal(fakeSnap[CF_UNICODETEXT], canvasJson);
        results.Add("InvalidPngWithCanvasJson=" + (fakeOk ? "PASS" : "FAIL"));

        Console.WriteLine(string.Join(Environment.NewLine, results));
        return compositeOk && textOk && jsonOk && imageOk && fileOk && fakeOk ? 0 : 1;
    }

    static void SetClipboard(Dictionary<uint, byte[]> values)
    {
        OpenWithRetry();
        try
        {
            if (!EmptyClipboard()) throw new Exception("EmptyClipboard failed");
            foreach (var item in values)
            {
                IntPtr h = GlobalAlloc(GMEM_MOVEABLE, (UIntPtr)item.Value.Length);
                IntPtr p = GlobalLock(h); Marshal.Copy(item.Value, 0, p, item.Value.Length); GlobalUnlock(h);
                if (SetClipboardData(item.Key, h) == IntPtr.Zero) { GlobalFree(h); throw new Exception("SetClipboardData failed"); }
            }
        }
        finally { CloseClipboard(); }
    }

    static Dictionary<uint, byte[]> Snapshot()
    {
        var result = new Dictionary<uint, byte[]>();
        OpenWithRetry();
        try
        {
            uint f = 0;
            while ((f = EnumClipboardFormats(f)) != 0)
            {
                IntPtr h = GetClipboardData(f); if (h == IntPtr.Zero) continue;
                ulong n = GlobalSize(h).ToUInt64(); if (n == 0 || n > 1024 * 1024) continue;
                IntPtr p = GlobalLock(h); if (p == IntPtr.Zero) continue;
                try { byte[] b = new byte[(int)n]; Marshal.Copy(p, b, 0, b.Length); result[f] = b; }
                finally { GlobalUnlock(h); }
            }
        }
        finally { CloseClipboard(); }
        return result;
    }

    static void OpenWithRetry()
    {
        for (int i = 0; i < 30; i++) { if (OpenClipboard(IntPtr.Zero)) return; Thread.Sleep(20); }
        throw new Exception("OpenClipboard failed");
    }

    static bool Equal(byte[] a, byte[] b) { if (a == null || b == null || a.Length != b.Length) return false; for (int i=0;i<a.Length;i++) if(a[i]!=b[i]) return false; return true; }

    static byte[] CreateOnePixelDib()
    {
        byte[] b = new byte[44];
        WriteInt(b, 0, 40); WriteInt(b, 4, 1); WriteInt(b, 8, 1);
        b[12] = 1; b[14] = 24; WriteInt(b, 20, 4);
        b[40] = 30; b[41] = 120; b[42] = 220; b[43] = 0;
        return b;
    }

    static bool IsCompatibleDib(byte[] bytes, int expectedHeaderSize)
    {
        return bytes != null && bytes.Length >= expectedHeaderSize + 4 &&
            BitConverter.ToInt32(bytes, 0) == expectedHeaderSize &&
            BitConverter.ToInt32(bytes, 4) == 1 && BitConverter.ToInt32(bytes, 8) == 1 &&
            BitConverter.ToInt16(bytes, 12) == 1 && BitConverter.ToInt16(bytes, 14) == 32;
    }

    static byte[] CreateFileDrop()
    {
        byte[] name = Encoding.Unicode.GetBytes("C:\\synthetic-file.txt\0\0");
        byte[] data = new byte[20 + name.Length];
        data[0] = 20;
        data[16] = 1;
        Buffer.BlockCopy(name, 0, data, 20, name.Length);
        return data;
    }

    static void WriteInt(byte[] b, int offset, int value)
    {
        byte[] v = BitConverter.GetBytes(value); Buffer.BlockCopy(v, 0, b, offset, 4);
    }

    [DllImport("user32.dll", SetLastError=true)] static extern bool OpenClipboard(IntPtr h);
    [DllImport("user32.dll", SetLastError=true)] static extern bool CloseClipboard();
    [DllImport("user32.dll", SetLastError=true)] static extern bool EmptyClipboard();
    [DllImport("user32.dll", SetLastError=true)] static extern IntPtr SetClipboardData(uint f, IntPtr h);
    [DllImport("user32.dll", SetLastError=true)] static extern IntPtr GetClipboardData(uint f);
    [DllImport("user32.dll", SetLastError=true)] static extern uint EnumClipboardFormats(uint f);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern uint RegisterClipboardFormat(string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr GlobalAlloc(uint flags, UIntPtr bytes);
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr GlobalFree(IntPtr h);
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr GlobalLock(IntPtr h);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GlobalUnlock(IntPtr h);
    [DllImport("kernel32.dll", SetLastError=true)] static extern UIntPtr GlobalSize(IntPtr h);
}
