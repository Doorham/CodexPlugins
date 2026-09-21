using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class WinInetProxyBypass
{
    private const int InternetOptionPerConnectionOption = 75;
    private const int InternetPerConnProxyBypass = 3;
    private const int InternetOptionSettingsChanged = 39;
    private const int InternetOptionRefresh = 37;

    [StructLayout(LayoutKind.Explicit)]
    private struct OptionValue
    {
        [FieldOffset(0)] public int DwordValue;
        [FieldOffset(0)] public IntPtr StringValue;
        [FieldOffset(0)] public System.Runtime.InteropServices.ComTypes.FILETIME FileTimeValue;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PerConnectionOption
    {
        public int Option;
        public OptionValue Value;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PerConnectionOptionList
    {
        public int Size;
        public IntPtr Connection;
        public int OptionCount;
        public int OptionError;
        public IntPtr Options;
    }

    [DllImport("wininet.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool InternetSetOption(
        IntPtr internet,
        int option,
        IntPtr buffer,
        int bufferLength);

    public static void Apply(string bypass)
    {
        IntPtr text = IntPtr.Zero;
        IntPtr optionPointer = IntPtr.Zero;
        IntPtr listPointer = IntPtr.Zero;
        try
        {
            text = Marshal.StringToHGlobalUni(bypass ?? string.Empty);
            var option = new PerConnectionOption
            {
                Option = InternetPerConnProxyBypass,
                Value = new OptionValue { StringValue = text },
            };
            optionPointer = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(PerConnectionOption)));
            Marshal.StructureToPtr(option, optionPointer, false);

            var optionList = new PerConnectionOptionList
            {
                Size = Marshal.SizeOf(typeof(PerConnectionOptionList)),
                Connection = IntPtr.Zero,
                OptionCount = 1,
                OptionError = 0,
                Options = optionPointer,
            };
            listPointer = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(PerConnectionOptionList)));
            Marshal.StructureToPtr(optionList, listPointer, false);

            if (!InternetSetOption(IntPtr.Zero, InternetOptionPerConnectionOption, listPointer, optionList.Size))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            if (!InternetSetOption(IntPtr.Zero, InternetOptionSettingsChanged, IntPtr.Zero, 0))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            if (!InternetSetOption(IntPtr.Zero, InternetOptionRefresh, IntPtr.Zero, 0))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
        }
        finally
        {
            if (listPointer != IntPtr.Zero) Marshal.FreeHGlobal(listPointer);
            if (optionPointer != IntPtr.Zero) Marshal.FreeHGlobal(optionPointer);
            if (text != IntPtr.Zero) Marshal.FreeHGlobal(text);
        }
    }
}
