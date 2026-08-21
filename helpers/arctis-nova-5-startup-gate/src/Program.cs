using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

namespace CompanyAIHelpers.ArctisNova5StartupGate
{
    internal static class Program
    {
        private const uint DigcfPresent = 0x00000002;
        private const uint DigcfDeviceInterface = 0x00000010;
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

        [DllImport("hid.dll")]
        private static extern void HidD_GetHidGuid(out Guid hidGuid);

        [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr SetupDiGetClassDevs(
            ref Guid classGuid,
            IntPtr enumerator,
            IntPtr parentWindow,
            uint flags);

        [DllImport("setupapi.dll", SetLastError = true)]
        private static extern bool SetupDiEnumDeviceInterfaces(
            IntPtr deviceInfoSet,
            IntPtr deviceInfoData,
            ref Guid interfaceClassGuid,
            uint memberIndex,
            ref SpDeviceInterfaceData deviceInterfaceData);

        [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern bool SetupDiGetDeviceInterfaceDetail(
            IntPtr deviceInfoSet,
            ref SpDeviceInterfaceData deviceInterfaceData,
            IntPtr deviceInterfaceDetailData,
            uint deviceInterfaceDetailDataSize,
            out uint requiredSize,
            IntPtr deviceInfoData);

        [DllImport("setupapi.dll")]
        private static extern bool SetupDiDestroyDeviceInfoList(IntPtr deviceInfoSet);

        [STAThread]
        private static void Main()
        {
            try
            {
                if (!ReceiverPresent())
                {
                    return;
                }

                const string processName = "ArctisNova5BatteryMonitor";
                if (Process.GetProcessesByName(processName).Length != 0)
                {
                    return;
                }

                string monitor = Path.Combine(
                    AppDomain.CurrentDomain.BaseDirectory,
                    processName + ".exe");
                if (!File.Exists(monitor))
                {
                    return;
                }

                ProcessStartInfo startInfo = new ProcessStartInfo(monitor);
                startInfo.WorkingDirectory = Path.GetDirectoryName(monitor);
                startInfo.UseShellExecute = false;
                startInfo.CreateNoWindow = true;
                Process.Start(startInfo);
            }
            catch
            {
                // The startup gate is intentionally silent and writes no logs.
            }
        }

        private static bool ReceiverPresent()
        {
            Guid hidGuid;
            HidD_GetHidGuid(out hidGuid);
            IntPtr info = SetupDiGetClassDevs(
                ref hidGuid,
                IntPtr.Zero,
                IntPtr.Zero,
                DigcfPresent | DigcfDeviceInterface);
            if (info == IntPtr.Zero || info == InvalidHandleValue)
            {
                return false;
            }

            try
            {
                for (uint index = 0; ; index++)
                {
                    SpDeviceInterfaceData interfaceData = new SpDeviceInterfaceData();
                    interfaceData.CbSize = Marshal.SizeOf(typeof(SpDeviceInterfaceData));
                    if (!SetupDiEnumDeviceInterfaces(
                        info,
                        IntPtr.Zero,
                        ref hidGuid,
                        index,
                        ref interfaceData))
                    {
                        return false;
                    }

                    uint required;
                    SetupDiGetDeviceInterfaceDetail(
                        info,
                        ref interfaceData,
                        IntPtr.Zero,
                        0,
                        out required,
                        IntPtr.Zero);
                    if (required == 0)
                    {
                        continue;
                    }

                    IntPtr detail = Marshal.AllocHGlobal((int)required);
                    try
                    {
                        Marshal.WriteInt32(detail, IntPtr.Size == 8 ? 8 : 6);
                        if (!SetupDiGetDeviceInterfaceDetail(
                            info,
                            ref interfaceData,
                            detail,
                            required,
                            out required,
                            IntPtr.Zero))
                        {
                            continue;
                        }

                        string path = Marshal.PtrToStringUni(IntPtr.Add(detail, 4));
                        if (path != null && path.IndexOf(
                            ReceiverId,
                            StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            return true;
                        }
                    }
                    finally
                    {
                        Marshal.FreeHGlobal(detail);
                    }
                }
            }
            finally
            {
                SetupDiDestroyDeviceInfoList(info);
            }
        }
    }
}
