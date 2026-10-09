using System;
using System.IO;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Threading;

internal static class RuntimeControl
{
    static EventWaitHandle stop;
    static string Name {
        get {
            string identity = WindowsIdentity.GetCurrent().User.Value + "|" + Path.GetFullPath(Process.GetCurrentProcess().MainModule.FileName).ToLowerInvariant();
            using (var hash = SHA256.Create())
                return "Local\\CodexTools.Stop." + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(identity))).Replace("-", "");
        }
    }
    // True means this invocation is only a stop request, never a helper instance.
    public static bool HandleStop(string[] args) {
        if (args.Length == 1 && args[0] == "--test-stop-protocol") {
            Initialize();
            using (var child = Process.Start(new ProcessStartInfo(Process.GetCurrentProcess().MainModule.FileName, "--stop") { UseShellExecute=false, CreateNoWindow=true })) {
                child.WaitForExit(5000);
                Environment.ExitCode = stop.WaitOne(5000) ? 0 : 3;
            }
            return true;
        }
        if (args.Length == 1 && args[0] == "--stop") {
            try { using (var existing = EventWaitHandle.OpenExisting(Name)) existing.Set(); }
            catch (WaitHandleCannotBeOpenedException) { }
            return true;
        }
        return false;
    }
    public static void Initialize() { stop = new EventWaitHandle(false, EventResetMode.ManualReset, Name); }
    public static bool StopRequested { get { return stop != null && stop.WaitOne(0); } }
}
