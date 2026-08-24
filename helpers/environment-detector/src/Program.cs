using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace EnvironmentDetector
{
    internal enum CheckLevel
    {
        Ready,
        Warning,
        Missing
    }

    internal sealed class CheckResult
    {
        public string Importance;
        public string Group;
        public string Name;
        public CheckLevel Level;
        public string Detail;
        public string Guidance;
    }

    internal sealed class CommandResult
    {
        public int ExitCode;
        public string Output;
    }

    internal sealed class RepairResult
    {
        public string Name;
        public bool Success;
        public string Detail;
    }

    internal sealed class PythonProbe
    {
        public string Executable;
        public string PrefixArguments;
        public string Version;
        public int Major;
        public int Minor;
        public bool Available;
    }

    internal sealed class VisualStudioProbe
    {
        public bool Installed;
        public bool PythonWorkload;
        public string InstallationPath;
        public string Version;
    }

    internal sealed class CodePageSnapshot
    {
        public string CreatedUtc;
        public string ACP;
        public string OEMCP;
        public string MACCP;
    }

    internal static class Detector
    {
        private static readonly List<string> CleanPathDirectories = BuildCleanPathDirectories();

        public static List<CheckResult> ScanAll()
        {
            PythonProbe python;
            VisualStudioProbe visualStudio = FindVisualStudio();
            string vsCode = FindVsCodeExecutable();
            string cursor = FindCursorExecutable();
            string pyCharm = FindPyCharmExecutable();
            List<CheckResult> results = new List<CheckResult>();
            results.Add(CheckPowerShell());
            results.Add(CheckWindowsTerminal());
            results.Add(CheckUtf8());
            results.Add(CheckDevelopmentTool(vsCode, cursor, pyCharm, visualStudio));
            results.Add(CheckPython(out python));
            results.Add(CheckDevelopmentIntegration(python, vsCode, cursor, pyCharm, visualStudio));
            results.Add(CheckGit());
            results.Add(CheckFfmpeg());
            results.Add(CheckPyYaml(python));
            results.Add(CheckYtDlp(python));
            return results;
        }

        private static CheckResult CheckPowerShell()
        {
            List<string> candidates = FindExecutables("pwsh.exe");
            string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            string root = Path.Combine(programFiles, "PowerShell");
            if (Directory.Exists(root))
            {
                foreach (string directory in SafeDirectories(root))
                    AddIfFile(candidates, Path.Combine(directory, "pwsh.exe"));
            }

            string independent = candidates.FirstOrDefault(path => !IsCodexRuntime(path));
            string bundled = candidates.FirstOrDefault(IsCodexRuntime);
            if (!String.IsNullOrEmpty(independent))
            {
                CommandResult run = Run(independent, "-NoProfile -NonInteractive -Command \"$PSVersionTable.PSVersion.ToString()\"");
                string version = FirstLine(run.Output);
                return Ready("终端环境", "PowerShell 7", "已安装 " + version + " · " + independent,
                    "无需处理。");
            }
            if (!String.IsNullOrEmpty(bundled))
            {
                CommandResult run = Run(bundled, "-NoProfile -NonInteractive -Command \"$PSVersionTable.PSVersion.ToString()\"");
                return Warning("终端环境", "PowerShell 7",
                    "仅发现 Codex 随附版本 " + FirstLine(run.Output) + "；普通终端不一定可用。",
                    "可在本工具中一键安装系统独立的 PowerShell 7。");
            }
            return Missing("终端环境", "PowerShell 7", "没有发现 pwsh.exe。",
                "可在本工具中一键安装 PowerShell 7。");
        }

        private static CheckResult CheckWindowsTerminal()
        {
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string alias = Path.Combine(local, "Microsoft", "WindowsApps", "wt.exe");
            string package = Path.Combine(local, "Packages", "Microsoft.WindowsTerminal_8wekyb3d8bbwe");
            string executable = FindExecutables("wt.exe").FirstOrDefault();
            if (File.Exists(alias) || Directory.Exists(package) || !String.IsNullOrEmpty(executable))
            {
                string location = File.Exists(alias) ? alias : (Directory.Exists(package) ? "Microsoft Store 应用包" : executable);
                return Ready("终端环境", "Windows Terminal", "已安装 · " + location, "无需处理。");
            }
            return Missing("终端环境", "Windows Terminal", "没有发现 Windows Terminal。",
                "可在本工具中通过 winget 一键安装。");
        }

        private static CheckResult CheckUtf8()
        {
            try
            {
                using (RegistryKey key = Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Control\Nls\CodePage"))
                {
                    string acp = Convert.ToString(key == null ? null : key.GetValue("ACP"));
                    string oem = Convert.ToString(key == null ? null : key.GetValue("OEMCP"));
                    string mac = Convert.ToString(key == null ? null : key.GetValue("MACCP"));
                    if (acp == "65001" && oem == "65001" && mac == "65001")
                        return Ready("终端环境", "UTF-8 全球语言支持",
                            "系统 ANSI、OEM 与 Mac 代码页均为 65001。" +
                            (Utf8Repair.CanRestore() ? " 已保存修改前编码，可随时恢复。" : ""), "无需处理。");
                    return Warning("终端环境", "UTF-8 全球语言支持",
                        "尚未全局启用 · ACP=" + EmptyAsUnknown(acp) + "，OEMCP=" + EmptyAsUnknown(oem) +
                        "，MACCP=" + EmptyAsUnknown(mac),
                        "可点击“一键自动补全”；设置完成后必须重启 Windows。");
                }
            }
            catch (Exception ex)
            {
                return Warning("终端环境", "UTF-8 全球语言支持", "无法读取系统代码页：" + ex.Message,
                    "请检查 Windows 区域与语言设置。");
            }
        }

        private static CheckResult CheckDevelopmentTool(string vsCode, string cursor, string pyCharm, VisualStudioProbe visualStudio)
        {
            List<string> routes = new List<string>();
            if (!String.IsNullOrEmpty(vsCode))
            {
                string version = FileVersionInfo.GetVersionInfo(vsCode).ProductVersion;
                routes.Add("VS Code " + EmptyAsUnknown(version));
            }
            if (visualStudio.Installed)
                routes.Add("Visual Studio " + EmptyAsUnknown(visualStudio.Version));
            if (!String.IsNullOrEmpty(cursor))
                routes.Add("Cursor " + GetProductVersion(cursor));
            if (!String.IsNullOrEmpty(pyCharm))
                routes.Add("PyCharm " + GetProductVersion(pyCharm));
            if (routes.Count > 0)
                return Ready("开发工具", "开发工具",
                    "已发现：" + String.Join("；", routes.ToArray()) + "。", "无需处理。");
            return Missing("开发工具", "开发工具",
                "没有发现可验证的开发工具。",
                "请用户安装任一种适用的开发工具；当前可验证 VS Code、Visual Studio、Cursor 和 PyCharm。");
        }

        private static CheckResult CheckDevelopmentIntegration(PythonProbe python, string vsCode, string cursor,
            string pyCharm, VisualStudioProbe visualStudio)
        {
            if (!python.Available)
                return EvaluateIntegrationState(python, new List<string>(), "没有可运行的 Python，无法完成编辑器集成。");

            string pythonExtension = FindEditorExtension("ms-python.python-", ".vscode", ".vscode-insiders");
            bool vsCodeRouteReady = false;
            string vsCodeRouteDetail = null;
            if (!String.IsNullOrEmpty(vsCode) && !String.IsNullOrEmpty(pythonExtension))
            {
                bool manifestConfirmed = IsMicrosoftPythonExtension(pythonExtension);
                vsCodeRouteReady = manifestConfirmed;
                vsCodeRouteDetail = manifestConfirmed
                    ? "VS Code 的 Microsoft Python 扩展清单验证通过"
                    : "VS Code 扩展目录存在，但 Microsoft Python 扩展清单验证失败";
            }

            string cursorPythonExtension = FindEditorExtension("ms-python.python-", ".cursor");
            bool cursorRouteReady = !String.IsNullOrEmpty(cursor) && IsMicrosoftPythonExtension(cursorPythonExtension);
            string cursorRouteDetail = null;
            if (!String.IsNullOrEmpty(cursor))
                cursorRouteDetail = cursorRouteReady
                    ? "Cursor 的 Microsoft Python 扩展清单验证通过"
                    : "Cursor 已安装，但没有验证到 Microsoft Python 扩展";

            bool pyCharmRouteReady = !String.IsNullOrEmpty(pyCharm);
            bool visualStudioRouteReady = visualStudio.Installed && visualStudio.PythonWorkload;
            List<string> readyRoutes = new List<string>();
            if (vsCodeRouteReady)
            {
                string pylance = FindEditorExtension("ms-python.vscode-pylance-", ".vscode", ".vscode-insiders");
                readyRoutes.Add(vsCodeRouteDetail + (String.IsNullOrEmpty(pylance) ? "" : "，Pylance 已安装"));
            }
            if (visualStudioRouteReady)
                readyRoutes.Add("Visual Studio Python 开发工作负载已安装");
            if (cursorRouteReady)
                readyRoutes.Add(cursorRouteDetail);
            if (pyCharmRouteReady)
                readyRoutes.Add("PyCharm 自带 Python 项目与解释器集成功能");

            if (readyRoutes.Count == 0)
            {
                string found = !String.IsNullOrEmpty(vsCodeRouteDetail) ? vsCodeRouteDetail + "；" : "";
                if (visualStudio.Installed && !visualStudio.PythonWorkload)
                    found += "Visual Studio 未安装 Python 开发工作负载。";
                if (!String.IsNullOrEmpty(cursorRouteDetail))
                    found += cursorRouteDetail + "。";
                if (String.IsNullOrEmpty(found)) found = "没有发现可用的 Python 编辑器集成路线。";
                return EvaluateIntegrationState(python, readyRoutes, found);
            }

            return EvaluateIntegrationState(python, readyRoutes, null);
        }

        private static CheckResult EvaluateIntegrationState(PythonProbe python, List<string> readyRoutes, string problemDetail)
        {
            if (python == null || !python.Available)
                return Missing("编辑器集成", "编辑器集成",
                    String.IsNullOrWhiteSpace(problemDetail) ? "没有可运行的 Python，无法完成编辑器集成。" : problemDetail,
                    "请先安装 Python 3.11+，再完成所用开发工具的 Python 集成配置。");
            if (readyRoutes == null || readyRoutes.Count == 0)
                return Missing("编辑器集成", "编辑器集成",
                    String.IsNullOrWhiteSpace(problemDetail) ? "没有发现可用的 Python 编辑器集成路线。" : problemDetail,
                    "请为所用开发工具配置 Python 集成；支持验证 VS Code/Cursor 的 Microsoft Python 扩展、Visual Studio Python 工作负载或 PyCharm 内置集成。");
            bool versionReady = python.Major > 3 || (python.Major == 3 && python.Minor >= 11);
            string detail = String.Join("；", readyRoutes.ToArray()) + "；" + python.Version + " 可运行。";
            if (!versionReady)
                return Warning("编辑器集成", "编辑器集成", detail,
                    "基础联动已具备，但 Python 版本低于公司最低要求 3.11，请先升级 Python。");
            return Ready("编辑器集成", "编辑器集成", detail,
                "基础联动条件合格；具体项目首次打开时仍可按工作区选择 Python 解释器。");
        }

        public static CheckResult EvaluateIntegrationForSelfTest(PythonProbe python, bool routeReady)
        {
            return EvaluateIntegrationState(python,
                routeReady ? new List<string> { "模拟编辑器集成验证通过" } : new List<string>(),
                routeReady ? null : "模拟：开发工具存在，但 Python 集成缺失。");
        }

        private static VisualStudioProbe FindVisualStudio()
        {
            VisualStudioProbe probe = new VisualStudioProbe();
            string programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            string vswhere = Path.Combine(programFilesX86, "Microsoft Visual Studio", "Installer", "vswhere.exe");
            if (!File.Exists(vswhere)) return probe;

            CommandResult any = Run(vswhere, "-latest -products * -property installationPath", 15000);
            string installation = FirstExistingDirectory(any.Output);
            if (!String.IsNullOrEmpty(installation))
            {
                string devenv = Path.Combine(installation, "Common7", "IDE", "devenv.exe");
                if (File.Exists(devenv))
                {
                    probe.Installed = true;
                    probe.InstallationPath = installation;
                    probe.Version = FileVersionInfo.GetVersionInfo(devenv).ProductVersion;
                }
            }

            CommandResult python = Run(vswhere,
                "-latest -products * -requires Microsoft.VisualStudio.Workload.Python -property installationPath", 15000);
            string pythonInstallation = FirstExistingDirectory(python.Output);
            if (!String.IsNullOrEmpty(pythonInstallation))
            {
                string devenv = Path.Combine(pythonInstallation, "Common7", "IDE", "devenv.exe");
                if (File.Exists(devenv))
                {
                    probe.Installed = true;
                    probe.PythonWorkload = true;
                    probe.InstallationPath = pythonInstallation;
                    probe.Version = FileVersionInfo.GetVersionInfo(devenv).ProductVersion;
                }
            }
            return probe;
        }

        private static string FindVsCodeExecutable()
        {
            List<string> candidates = new List<string>();
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            string programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            AddIfFile(candidates, Path.Combine(local, "Programs", "Microsoft VS Code", "Code.exe"));
            AddIfFile(candidates, Path.Combine(programFiles, "Microsoft VS Code", "Code.exe"));
            AddIfFile(candidates, Path.Combine(programFilesX86, "Microsoft VS Code", "Code.exe"));
            return DistinctPaths(candidates).FirstOrDefault();
        }

        private static string FindCursorExecutable()
        {
            List<string> candidates = new List<string>();
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            string programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            AddIfFile(candidates, Path.Combine(local, "Programs", "Cursor", "Cursor.exe"));
            AddIfFile(candidates, Path.Combine(local, "Programs", "cursor", "Cursor.exe"));
            AddIfFile(candidates, Path.Combine(programFiles, "Cursor", "Cursor.exe"));
            AddIfFile(candidates, Path.Combine(programFilesX86, "Cursor", "Cursor.exe"));
            return DistinctPaths(candidates).FirstOrDefault();
        }

        private static string FindPyCharmExecutable()
        {
            List<string> candidates = new List<string>();
            AddPyCharmFromUninstallRegistry(candidates, Registry.CurrentUser, @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall");
            AddPyCharmFromUninstallRegistry(candidates, Registry.LocalMachine, @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall");
            AddPyCharmFromUninstallRegistry(candidates, Registry.LocalMachine, @"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall");

            string[] roots =
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "JetBrains"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs")
            };
            foreach (string root in roots)
            {
                foreach (string directory in SafeDirectories(root))
                {
                    string name = Path.GetFileName(directory) ?? "";
                    if (name.IndexOf("PyCharm", StringComparison.OrdinalIgnoreCase) < 0) continue;
                    AddIfFile(candidates, Path.Combine(directory, "bin", "pycharm64.exe"));
                    AddIfFile(candidates, Path.Combine(directory, "bin", "pycharm.exe"));
                }
            }
            return DistinctPaths(candidates).FirstOrDefault();
        }

        private static void AddPyCharmFromUninstallRegistry(List<string> candidates, RegistryKey root, string subKey)
        {
            try
            {
                using (RegistryKey uninstall = root.OpenSubKey(subKey))
                {
                    if (uninstall == null) return;
                    foreach (string childName in uninstall.GetSubKeyNames())
                    {
                        using (RegistryKey child = uninstall.OpenSubKey(childName))
                        {
                            string displayName = Convert.ToString(child == null ? null : child.GetValue("DisplayName"));
                            if (displayName.IndexOf("PyCharm", StringComparison.OrdinalIgnoreCase) < 0) continue;
                            string installLocation = Convert.ToString(child.GetValue("InstallLocation")).Trim().Trim('"');
                            AddIfFile(candidates, Path.Combine(installLocation, "bin", "pycharm64.exe"));
                            AddIfFile(candidates, Path.Combine(installLocation, "bin", "pycharm.exe"));
                            string displayIcon = Convert.ToString(child.GetValue("DisplayIcon"));
                            string iconPath = (displayIcon ?? "").Split(',')[0].Trim().Trim('"');
                            if (Path.GetFileName(iconPath).StartsWith("pycharm", StringComparison.OrdinalIgnoreCase))
                                AddIfFile(candidates, iconPath);
                        }
                    }
                }
            }
            catch { }
        }

        private static string FindEditorExtension(string folderPrefix, params string[] profileDirectories)
        {
            string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            foreach (string profileDirectory in profileDirectories)
            {
                string root = Path.Combine(profile, profileDirectory, "extensions");
                if (!Directory.Exists(root)) continue;
                try
                {
                    string match = Directory.GetDirectories(root)
                        .FirstOrDefault(path => Path.GetFileName(path).StartsWith(folderPrefix, StringComparison.OrdinalIgnoreCase));
                    if (!String.IsNullOrEmpty(match)) return match;
                }
                catch { }
            }
            return null;
        }

        private static bool IsMicrosoftPythonExtension(string extensionDirectory)
        {
            if (String.IsNullOrEmpty(extensionDirectory)) return false;
            try
            {
                string manifestPath = Path.Combine(extensionDirectory, "package.json");
                string manifest = File.Exists(manifestPath) ? File.ReadAllText(manifestPath) : "";
                return Regex.IsMatch(manifest, "\\\"publisher\\\"\\s*:\\s*\\\"ms-python\\\"", RegexOptions.IgnoreCase) &&
                    Regex.IsMatch(manifest, "\\\"name\\\"\\s*:\\s*\\\"python\\\"", RegexOptions.IgnoreCase);
            }
            catch { return false; }
        }

        private static string GetProductVersion(string executable)
        {
            try { return EmptyAsUnknown(FileVersionInfo.GetVersionInfo(executable).ProductVersion); }
            catch { return "未知"; }
        }

        private static CheckResult CheckPython(out PythonProbe probe)
        {
            probe = FindPython();
            if (!probe.Available)
                return EvaluatePythonState(probe, false, false, false);
            CommandResult script = Run(probe.Executable,
                JoinArguments(probe.PrefixArguments, "-c \"import sys; print('SCRIPT_OK:' + sys.executable)\""), 15000);
            CommandResult pip = Run(probe.Executable,
                JoinArguments(probe.PrefixArguments, "-m pip --version"), 20000);
            bool venvReady = false;
            string validationDirectory = CreateValidationDirectory("python-venv");
            try
            {
                CommandResult venv = Run(probe.Executable,
                    JoinArguments(probe.PrefixArguments, "-m venv " + QuoteArgument(validationDirectory)), 90000);
                string venvPython = Path.Combine(validationDirectory, "Scripts", "python.exe");
                if (venv.ExitCode == 0 && File.Exists(venvPython))
                {
                    CommandResult venvRun = Run(venvPython, "-c \"print('VENV_OK')\"", 15000);
                    venvReady = venvRun.ExitCode == 0 && (venvRun.Output ?? "").Contains("VENV_OK");
                }
            }
            finally
            {
                SafeDeleteValidationDirectory(validationDirectory);
            }

            bool scriptReady = script.ExitCode == 0 && (script.Output ?? "").Contains("SCRIPT_OK:");
            bool pipReady = pip.ExitCode == 0;
            return EvaluatePythonState(probe, scriptReady, pipReady, venvReady);
        }

        private static CheckResult EvaluatePythonState(PythonProbe probe, bool scriptReady, bool pipReady, bool venvReady)
        {
            if (probe == null || !probe.Available)
                return Missing("基础开发环境", "基础开发环境", "没有发现可正常运行的 Python 3.11+。",
                    "建议用户自行安装 Python 3.11 或更高版本，并勾选加入 PATH。");
            bool versionReady = probe.Major > 3 || (probe.Major == 3 && probe.Minor >= 11);
            bool capabilityReady = scriptReady && pipReady && venvReady;
            string detail = probe.Version + " · " + probe.Executable;
            if (!versionReady)
                return Warning("基础开发环境", "基础开发环境", detail + "；版本低于最低要求 3.11。",
                    "建议用户自行安装 Python 3.11 或更高版本。");
            if (!capabilityReady)
                return Warning("基础开发环境", "基础开发环境",
                    detail + "；真实测试未全部通过：脚本=" + PassFail(scriptReady) +
                    "，pip=" + PassFail(pipReady) + "，venv=" + PassFail(venvReady) + "。",
                    "请修复当前 Python 安装；本模块不会自动重装 Python。");
            return Ready("基础开发环境", "基础开发环境",
                detail + "；脚本、pip 与临时虚拟环境实测通过。", "无需处理。");
        }

        public static CheckResult EvaluatePythonForSelfTest(PythonProbe probe, bool scriptReady, bool pipReady, bool venvReady)
        {
            return EvaluatePythonState(probe, scriptReady, pipReady, venvReady);
        }

        private static CheckResult CheckGit()
        {
            List<string> candidates = FindExecutables("git.exe");
            string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            AddIfFile(candidates, Path.Combine(programFiles, "Git", "cmd", "git.exe"));
            AddIfFile(candidates, Path.Combine(local, "Programs", "Git", "cmd", "git.exe"));
            candidates = DistinctPaths(candidates);
            string independent = candidates.FirstOrDefault(path => !IsCodexRuntime(path));
            string bundled = candidates.FirstOrDefault(IsCodexRuntime);
            if (!String.IsNullOrEmpty(independent))
            {
                CommandResult versionRun = Run(independent, "--version", 15000);
                string version = FirstLine(versionRun.Output);
                bool repositoryReady = false;
                string validationDirectory = CreateValidationDirectory("git-repository");
                try
                {
                    CommandResult init = Run(independent, "init --quiet " + QuoteArgument(validationDirectory), 30000);
                    CommandResult status = init.ExitCode == 0
                        ? Run(independent, "-C " + QuoteArgument(validationDirectory) + " status --porcelain", 15000)
                        : new CommandResult { ExitCode = -1, Output = "git init 失败" };
                    repositoryReady = init.ExitCode == 0 && status.ExitCode == 0;
                }
                finally
                {
                    SafeDeleteValidationDirectory(validationDirectory);
                }
                if (versionRun.ExitCode == 0 && repositoryReady)
                    return Ready("基础开发环境", "Git", version + " · " + independent + "；临时仓库实测通过。", "无需处理。");
                return Warning("基础开发环境", "Git", version + " · 命令存在，但临时仓库测试失败。",
                    "可在本工具中尝试重新安装 Git for Windows。");
            }
            if (!String.IsNullOrEmpty(bundled))
                return Warning("基础开发环境", "Git", "仅发现 Codex 随附 Git；普通终端不一定可用。",
                    "可在本工具中一键安装系统独立的 Git for Windows。");
            return Missing("基础开发环境", "Git", "没有发现 Git for Windows。",
                "可在本工具中一键安装 Git for Windows。");
        }

        private static CheckResult CheckFfmpeg()
        {
            string ffmpeg = FindExecutables("ffmpeg.exe").FirstOrDefault(path => !IsCodexRuntime(path));
            string ffprobe = FindExecutables("ffprobe.exe").FirstOrDefault(path => !IsCodexRuntime(path));
            if (!String.IsNullOrEmpty(ffmpeg) && !String.IsNullOrEmpty(ffprobe))
            {
                CommandResult versionRun = Run(ffmpeg, "-version", 15000);
                string version = FirstLine(versionRun.Output);
                bool mediaReady = false;
                string validationDirectory = CreateValidationDirectory("ffmpeg-media");
                string mediaFile = Path.Combine(validationDirectory, "probe.wav");
                try
                {
                    Directory.CreateDirectory(validationDirectory);
                    CommandResult encode = Run(ffmpeg,
                        "-hide_banner -loglevel error -f lavfi -i anullsrc=r=8000:cl=mono -t 0.25 -y " + QuoteArgument(mediaFile), 30000);
                    CommandResult probe = encode.ExitCode == 0
                        ? Run(ffprobe, "-v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 " + QuoteArgument(mediaFile), 15000)
                        : new CommandResult { ExitCode = -1, Output = "临时媒体生成失败" };
                    mediaReady = encode.ExitCode == 0 && probe.ExitCode == 0 && File.Exists(mediaFile) && new FileInfo(mediaFile).Length > 0;
                }
                finally
                {
                    SafeDeleteValidationDirectory(validationDirectory);
                }
                if (versionRun.ExitCode == 0 && mediaReady)
                    return Ready("多媒体工具", "FFmpeg（含 FFprobe）", version + " · 临时媒体生成与 FFprobe 读取实测通过。", "无需处理。");
                return Warning("多媒体工具", "FFmpeg（含 FFprobe）", version + " · 命令存在，但临时媒体测试失败。",
                    "可在本工具中一键补装完整的 FFmpeg 套件。");
            }
            if (!String.IsNullOrEmpty(ffmpeg) || !String.IsNullOrEmpty(ffprobe))
                return Warning("多媒体工具", "FFmpeg（含 FFprobe）",
                    "安装不完整：FFmpeg=" + Present(ffmpeg) + "，FFprobe=" + Present(ffprobe),
                    "可在本工具中一键补装完整的 FFmpeg 套件。");
            return Missing("多媒体工具", "FFmpeg（含 FFprobe）", "没有发现 ffmpeg.exe 与 ffprobe.exe。",
                "可在本工具中一键安装完整的 FFmpeg 套件。");
        }

        private static CheckResult CheckPyYaml(PythonProbe python)
        {
            if (!python.Available)
                return Missing("Python 依赖", "PyYAML", "由于 Python 不可用，无法检查 PyYAML。",
                    "请先安装 Python 3.11+，再返回本工具自动安装 PyYAML。");
            CommandResult run = Run(python.Executable, JoinArguments(python.PrefixArguments, "-c \"import yaml; print(yaml.__version__)\""));
            if (run.ExitCode == 0)
                return Ready("Python 依赖", "PyYAML", "已安装 " + FirstLine(run.Output) + " · 归属 " + python.Version, "无需处理。");
            return Missing("Python 依赖", "PyYAML", "当前 Python 无法导入 yaml。",
                "可在本工具中使用当前 Python 自动安装 PyYAML。");
        }

        private static CheckResult CheckYtDlp(PythonProbe python)
        {
            string executable = FindExecutables("yt-dlp.exe").FirstOrDefault(path => !IsCodexRuntime(path));
            if (!String.IsNullOrEmpty(executable))
            {
                CommandResult direct = Run(executable, "--version");
                if (direct.ExitCode == 0)
                    return Ready("Python 依赖", "yt-dlp", "已安装 " + FirstLine(direct.Output) + " · " + executable, "无需处理。");
            }
            if (python.Available)
            {
                CommandResult module = Run(python.Executable, JoinArguments(python.PrefixArguments, "-m yt_dlp --version"));
                if (module.ExitCode == 0)
                    return Ready("Python 依赖", "yt-dlp", "Python 模块可用 " + FirstLine(module.Output) + "。", "无需处理。");
            }
            return Missing("Python 依赖", "yt-dlp", "没有发现 yt-dlp 命令或 Python 模块。",
                "可在本工具中使用当前 Python 自动安装 yt-dlp。");
        }

        private static PythonProbe FindPython()
        {
            List<string> candidates = FindExecutables("python.exe")
                .Where(path => path.IndexOf("WindowsApps", StringComparison.OrdinalIgnoreCase) < 0)
                .Where(path => !IsCodexRuntime(path)).ToList();
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            AddPythonDirectories(candidates, Path.Combine(local, "Python"));
            AddPythonDirectories(candidates, Path.Combine(local, "Programs", "Python"));
            AddPythonDirectories(candidates, programFiles);

            foreach (string executable in DistinctPaths(candidates))
            {
                CommandResult run = Run(executable, "--version");
                Match match = Regex.Match(run.Output ?? "", @"Python\s+(\d+)\.(\d+)(?:\.(\d+))?", RegexOptions.IgnoreCase);
                if (run.ExitCode == 0 && match.Success)
                {
                    return new PythonProbe
                    {
                        Executable = executable,
                        PrefixArguments = "",
                        Version = match.Value,
                        Major = Int32.Parse(match.Groups[1].Value),
                        Minor = Int32.Parse(match.Groups[2].Value),
                        Available = true
                    };
                }
            }

            string launcher = FindExecutables("py.exe").FirstOrDefault(path => !IsCodexRuntime(path));
            if (!String.IsNullOrEmpty(launcher))
            {
                CommandResult run = Run(launcher, "-3 --version");
                Match match = Regex.Match(run.Output ?? "", @"Python\s+(\d+)\.(\d+)(?:\.(\d+))?", RegexOptions.IgnoreCase);
                if (run.ExitCode == 0 && match.Success)
                {
                    return new PythonProbe
                    {
                        Executable = launcher,
                        PrefixArguments = "-3",
                        Version = match.Value,
                        Major = Int32.Parse(match.Groups[1].Value),
                        Minor = Int32.Parse(match.Groups[2].Value),
                        Available = true
                    };
                }
            }
            return new PythonProbe { Available = false };
        }

        public static PythonProbe GetPythonForRepair()
        {
            return FindPython();
        }

        public static string FindIndependentExecutable(string fileName)
        {
            return FindExecutables(fileName).FirstOrDefault(path => !IsCodexRuntime(path));
        }

        public static CommandResult RunRepairCommand(string executable, string arguments)
        {
            return Run(executable, arguments, 1200000);
        }

        private static void AddPythonDirectories(List<string> candidates, string root)
        {
            if (!Directory.Exists(root)) return;
            AddIfFile(candidates, Path.Combine(root, "python.exe"));
            foreach (string directory in SafeDirectories(root))
            {
                string name = Path.GetFileName(directory) ?? "";
                if (name.StartsWith("Python", StringComparison.OrdinalIgnoreCase) ||
                    name.StartsWith("pythoncore", StringComparison.OrdinalIgnoreCase))
                    AddIfFile(candidates, Path.Combine(directory, "python.exe"));
            }
        }

        private static List<string> BuildCleanPathDirectories()
        {
            List<string> paths = new List<string>();
            AddRegistryPath(paths, Registry.LocalMachine, @"SYSTEM\CurrentControlSet\Control\Session Manager\Environment");
            AddRegistryPath(paths, Registry.CurrentUser, @"Environment");
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            paths.Add(Path.Combine(local, "Microsoft", "WindowsApps"));
            paths.Add(Path.Combine(local, "Microsoft", "WinGet", "Links"));
            return paths.Where(Directory.Exists).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        }

        private static void AddRegistryPath(List<string> paths, RegistryKey root, string subKey)
        {
            try
            {
                using (RegistryKey key = root.OpenSubKey(subKey))
                {
                    string value = Convert.ToString(key == null ? null : key.GetValue("Path", "", RegistryValueOptions.DoNotExpandEnvironmentNames));
                    foreach (string entry in (value ?? "").Split(new[] { ';' }, StringSplitOptions.RemoveEmptyEntries))
                    {
                        string expanded = Environment.ExpandEnvironmentVariables(entry.Trim().Trim('"'));
                        if (!String.IsNullOrWhiteSpace(expanded)) paths.Add(expanded);
                    }
                }
            }
            catch { }
        }

        private static List<string> FindExecutables(string fileName)
        {
            List<string> files = new List<string>();
            foreach (string directory in CleanPathDirectories)
                AddIfFile(files, Path.Combine(directory, fileName));
            return DistinctPaths(files);
        }

        private static List<string> DistinctPaths(IEnumerable<string> paths)
        {
            return paths.Where(path => !String.IsNullOrWhiteSpace(path) && File.Exists(path))
                .Select(Path.GetFullPath).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        }

        private static void AddIfFile(List<string> paths, string path)
        {
            try { if (File.Exists(path)) paths.Add(path); } catch { }
        }

        private static IEnumerable<string> SafeDirectories(string path)
        {
            try { return Directory.GetDirectories(path); } catch { return new string[0]; }
        }

        private static bool IsCodexRuntime(string path)
        {
            return path != null && (path.IndexOf(@"\.cache\codex-runtimes\", StringComparison.OrdinalIgnoreCase) >= 0 ||
                path.IndexOf(@"\.codex\", StringComparison.OrdinalIgnoreCase) >= 0);
        }

        private static string FirstExistingDirectory(string output)
        {
            if (String.IsNullOrWhiteSpace(output)) return null;
            foreach (string line in output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                string candidate = line.Trim().Trim('"');
                try { if (Directory.Exists(candidate)) return candidate; } catch { }
            }
            return null;
        }

        private static string CreateValidationDirectory(string prefix)
        {
            // Keep this deliberately short: .NET Framework recursive deletion can still hit
            // the legacy MAX_PATH boundary inside a Python virtual environment.
            string root = Path.Combine(Path.GetTempPath(), "EDV");
            Directory.CreateDirectory(root);
            return Path.Combine(root, prefix + "-" + Guid.NewGuid().ToString("N"));
        }

        private static void SafeDeleteValidationDirectory(string path)
        {
            try
            {
                string root = Path.GetFullPath(Path.Combine(Path.GetTempPath(), "EDV")).TrimEnd('\\') + "\\";
                string target = Path.GetFullPath(path);
                if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase) || target.Length <= root.Length)
                    return;
                if (Directory.Exists(target)) Directory.Delete(target, true);
            }
            catch { }
        }

        private static string QuoteArgument(string value)
        {
            return "\"" + (value ?? "").Replace("\"", "\\\"") + "\"";
        }

        private static string PassFail(bool value)
        {
            return value ? "通过" : "失败";
        }

        private static CommandResult Run(string executable, string arguments)
        {
            return Run(executable, arguments, 6000);
        }

        private static CommandResult Run(string executable, string arguments, int timeoutMilliseconds)
        {
            try
            {
                ProcessStartInfo info = new ProcessStartInfo(executable, arguments ?? "");
                info.UseShellExecute = false;
                info.CreateNoWindow = true;
                info.RedirectStandardOutput = true;
                info.RedirectStandardError = true;
                using (Process process = new Process())
                {
                    process.StartInfo = info;
                    StringBuilder stdout = new StringBuilder();
                    StringBuilder stderr = new StringBuilder();
                    process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e)
                    {
                        if (e.Data != null) lock (stdout) stdout.AppendLine(e.Data);
                    };
                    process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e)
                    {
                        if (e.Data != null) lock (stderr) stderr.AppendLine(e.Data);
                    };
                    process.Start();
                    process.BeginOutputReadLine();
                    process.BeginErrorReadLine();
                    if (!process.WaitForExit(timeoutMilliseconds))
                    {
                        try { process.Kill(); } catch { }
                        return new CommandResult { ExitCode = -2, Output = "检测超时" };
                    }
                    process.WaitForExit();
                    string combined = (stdout.ToString() + Environment.NewLine + stderr.ToString()).Trim();
                    return new CommandResult { ExitCode = process.ExitCode, Output = combined };
                }
            }
            catch (Exception ex)
            {
                return new CommandResult { ExitCode = -1, Output = ex.Message };
            }
        }

        private static string JoinArguments(string prefix, string arguments)
        {
            return String.IsNullOrWhiteSpace(prefix) ? arguments : prefix + " " + arguments;
        }

        private static string FirstLine(string text)
        {
            if (String.IsNullOrWhiteSpace(text)) return "版本未知";
            return text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).FirstOrDefault() ?? "版本未知";
        }

        private static string Present(string path)
        {
            return String.IsNullOrEmpty(path) ? "缺少" : "已发现";
        }

        private static string EmptyAsUnknown(string value)
        {
            return String.IsNullOrWhiteSpace(value) ? "未知" : value;
        }

        private static CheckResult Ready(string group, string name, string detail, string guidance)
        {
            return Result(group, name, CheckLevel.Ready, detail, guidance);
        }

        private static CheckResult Warning(string group, string name, string detail, string guidance)
        {
            return Result(group, name, CheckLevel.Warning, detail, guidance);
        }

        private static CheckResult Missing(string group, string name, string detail, string guidance)
        {
            return Result(group, name, CheckLevel.Missing, detail, guidance);
        }

        private static CheckResult Result(string group, string name, CheckLevel level, string detail, string guidance)
        {
            return new CheckResult
            {
                Importance = ImportanceFor(name),
                Group = group,
                Name = name,
                Level = level,
                Detail = detail,
                Guidance = guidance
            };
        }

        private static string ImportanceFor(string name)
        {
            if (name == "开发工具" || name == "基础开发环境" || name == "编辑器集成" || name == "Git")
                return "必需";
            if (name == "PyYAML" || name == "yt-dlp")
                return "业务可选";
            return "推荐";
        }
    }

    internal static class SingleWindow
    {
        public const string MutexName = @"Local\CompanyAIHelpers.EnvironmentDetector.SingleWindow";
        public const string SoftwareEventName = @"Local\CompanyAIHelpers.EnvironmentDetector.ShowSoftware";
        public const string CodexEventName = @"Local\CompanyAIHelpers.EnvironmentDetector.ShowCodex";

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr FindWindow(string className, string windowName);

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr window, int command);

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr window);

        public static void ActivateExistingWindow()
        {
            string[] titles = { "软件安装检查 · Codex 工具箱", "Codex 环境补全 · Codex 工具箱" };
            foreach (string title in titles)
            {
                IntPtr window = FindWindow(null, title);
                if (window == IntPtr.Zero) continue;
                ShowWindow(window, 9);
                SetForegroundWindow(window);
                return;
            }
        }
    }

    internal static class RepairEngine
    {
        private static readonly Dictionary<string, string> WingetPackages = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { "PowerShell 7", "Microsoft.PowerShell" },
            { "Windows Terminal", "Microsoft.WindowsTerminal" },
            { "Git", "Git.Git" },
            { "FFmpeg（含 FFprobe）", "Gyan.FFmpeg" }
        };

        public static List<string> GetAutomaticItems(IEnumerable<CheckResult> results)
        {
            HashSet<string> names = new HashSet<string>(results.Where(item => item.Level != CheckLevel.Ready).Select(item => item.Name), StringComparer.OrdinalIgnoreCase);
            return names.Where(name => WingetPackages.ContainsKey(name) || name == "PyYAML" || name == "yt-dlp" || name == "UTF-8 全球语言支持").ToList();
        }

        public static List<RepairResult> Repair(IEnumerable<CheckResult> results)
        {
            List<RepairResult> repaired = new List<RepairResult>();
            List<string> targets = GetAutomaticItems(results);
            string winget = Detector.FindIndependentExecutable("winget.exe");
            PythonProbe python = Detector.GetPythonForRepair();

            foreach (string name in targets)
            {
                if (name == "UTF-8 全球语言支持")
                    continue;
                RepairResult prerequisiteFailure = GetPrerequisiteFailure(name, winget, python);
                if (prerequisiteFailure != null)
                {
                    repaired.Add(prerequisiteFailure);
                    continue;
                }
                if (WingetPackages.ContainsKey(name))
                {
                    string packageId = WingetPackages[name];
                    string arguments = "install --id " + packageId + " --exact --accept-source-agreements --accept-package-agreements --silent";
                    CommandResult run = Detector.RunRepairCommand(winget, arguments);
                    repaired.Add(FromCommand(name, run));
                    continue;
                }

                string packageName = name == "PyYAML" ? "PyYAML" : "yt-dlp";
                string pipArguments = JoinArguments(python.PrefixArguments,
                    "-m pip install --upgrade --disable-pip-version-check " + packageName);
                CommandResult pip = Detector.RunRepairCommand(python.Executable, pipArguments);
                repaired.Add(FromCommand(name, pip));
            }
            return repaired;
        }

        private static RepairResult GetPrerequisiteFailure(string name, string winget, PythonProbe python)
        {
            if (WingetPackages.ContainsKey(name) && String.IsNullOrEmpty(winget))
                return Failed(name, "系统未发现 winget，无法自动安装。");
            if ((name == "PyYAML" || name == "yt-dlp") && (python == null || !python.Available))
                return Failed(name, "Python 不可用；请先在‘软件安装检查’中完成 Python 安装。");
            return null;
        }

        public static RepairResult EvaluatePrerequisiteForSelfTest(string name, bool wingetAvailable, bool pythonAvailable)
        {
            return GetPrerequisiteFailure(name, wingetAvailable ? "winget.exe" : null,
                new PythonProbe { Available = pythonAvailable });
        }

        private static RepairResult FromCommand(string name, CommandResult command)
        {
            string detail = command.ExitCode == 0 ? "处理完成。" : "处理失败（退出码 " + command.ExitCode + "）：" + Compact(command.Output);
            return new RepairResult { Name = name, Success = command.ExitCode == 0, Detail = detail };
        }

        private static RepairResult Failed(string name, string detail)
        {
            return new RepairResult { Name = name, Success = false, Detail = detail };
        }

        private static string JoinArguments(string prefix, string arguments)
        {
            return String.IsNullOrWhiteSpace(prefix) ? arguments : prefix + " " + arguments;
        }

        private static string Compact(string text)
        {
            if (String.IsNullOrWhiteSpace(text)) return "没有返回错误详情。";
            string compact = Regex.Replace(text, @"\s+", " ").Trim();
            return compact.Length <= 300 ? compact : compact.Substring(0, 300) + "…";
        }
    }

    internal static class Utf8Repair
    {
        private const string CodePageRegistryPath = @"SYSTEM\CurrentControlSet\Control\Nls\CodePage";

        private static string BackupRoot
        {
            get
            {
                return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "CompanyAIHelpers", "EnvironmentDetector", "Backups");
            }
        }

        public static bool StartElevated()
        {
            try
            {
                ProcessStartInfo info = new ProcessStartInfo(Application.ExecutablePath, "--enable-utf8");
                info.UseShellExecute = true;
                info.Verb = "runas";
                using (Process process = Process.Start(info))
                {
                    if (process == null) return false;
                    process.WaitForExit();
                    return process.ExitCode == 0;
                }
            }
            catch
            {
                return false;
            }
        }

        public static bool StartElevatedRestore()
        {
            try
            {
                ProcessStartInfo info = new ProcessStartInfo(Application.ExecutablePath, "--restore-utf8");
                info.UseShellExecute = true;
                info.Verb = "runas";
                using (Process process = Process.Start(info))
                {
                    if (process == null) return false;
                    process.WaitForExit();
                    return process.ExitCode == 0;
                }
            }
            catch
            {
                return false;
            }
        }

        public static bool CanRestore()
        {
            try
            {
                CodePageSnapshot backup = LoadSnapshot(GetLatestOriginalBackup());
                CodePageSnapshot current = ReadCurrent();
                return backup != null && current != null &&
                    (backup.ACP != current.ACP || backup.OEMCP != current.OEMCP || backup.MACCP != current.MACCP);
            }
            catch { return false; }
        }

        public static int Apply()
        {
            CodePageSnapshot original = null;
            string backupPath = null;
            try
            {
                original = ReadCurrent();
                if (original == null) throw new InvalidOperationException("无法读取系统代码页设置。");
                if (original.ACP == "65001" && original.OEMCP == "65001" && original.MACCP == "65001") return 0;
                backupPath = SaveSnapshot(original, "utf8-original");
                WriteSnapshot(new CodePageSnapshot
                {
                    CreatedUtc = DateTime.UtcNow.ToString("o"),
                    ACP = "65001",
                    OEMCP = "65001",
                    MACCP = "65001"
                });
                return 0;
            }
            catch (Exception ex)
            {
                string rollback = "";
                if (original != null)
                {
                    try
                    {
                        WriteSnapshot(original);
                        rollback = " 已自动恢复修改前编码。";
                    }
                    catch (Exception rollbackError)
                    {
                        rollback = " 自动恢复也失败：" + rollbackError.Message;
                    }
                }
                MessageBox.Show("UTF-8 设置失败：" + ex.Message + rollback +
                    (String.IsNullOrEmpty(backupPath) ? "" : "\r\n备份：" + backupPath),
                    "UTF-8 设置失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }

        public static int Restore()
        {
            CodePageSnapshot beforeRestore = null;
            try
            {
                string backupPath = GetLatestOriginalBackup();
                CodePageSnapshot original = LoadSnapshot(backupPath);
                if (original == null) throw new InvalidOperationException("没有找到有效的修改前编码备份。");
                beforeRestore = ReadCurrent();
                if (beforeRestore == null) throw new InvalidOperationException("无法读取当前系统代码页设置。");
                SaveSnapshot(beforeRestore, "restore-safety");
                WriteSnapshot(original);
                return 0;
            }
            catch (Exception ex)
            {
                string rollback = "";
                if (beforeRestore != null)
                {
                    try
                    {
                        WriteSnapshot(beforeRestore);
                        rollback = " 已恢复到执行本次操作前的状态。";
                    }
                    catch (Exception rollbackError)
                    {
                        rollback = " 恢复本次操作前状态也失败：" + rollbackError.Message;
                    }
                }
                MessageBox.Show("恢复原编码失败：" + ex.Message + rollback,
                    "恢复原编码失败", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }

        public static bool RunFileFormatSelfTest(string reportPath)
        {
            string testRoot = Path.Combine(Path.GetTempPath(), "CompanyAIHelpers", "EnvironmentDetectorSelfTest", Guid.NewGuid().ToString("N"));
            try
            {
                Directory.CreateDirectory(testRoot);
                CodePageSnapshot expected = new CodePageSnapshot
                {
                    CreatedUtc = "2026-01-02T03:04:05.0000000Z",
                    ACP = "936",
                    OEMCP = "936",
                    MACCP = "10000"
                };
                string validPath = Path.Combine(testRoot, "valid.ini");
                WriteSnapshotFile(expected, validPath);
                CodePageSnapshot actual = LoadSnapshot(validPath);
                bool roundTrip = actual != null && actual.ACP == expected.ACP &&
                    actual.OEMCP == expected.OEMCP && actual.MACCP == expected.MACCP;

                string invalidPath = Path.Combine(testRoot, "invalid.ini");
                File.WriteAllText(invalidPath, "schemaVersion=1\r\nACP=not-a-codepage\r\nOEMCP=936\r\nMACCP=10000", new UTF8Encoding(false));
                bool invalidRejected = LoadSnapshot(invalidPath) == null;
                string report = "UTF8_BACKUP_ROUNDTRIP=" + (roundTrip ? "PASS" : "FAIL") + Environment.NewLine +
                    "UTF8_INVALID_BACKUP_REJECTED=" + (invalidRejected ? "PASS" : "FAIL") + Environment.NewLine +
                    "REGISTRY_WRITES=0" + Environment.NewLine;
                File.WriteAllText(reportPath, report, new UTF8Encoding(false));
                return roundTrip && invalidRejected;
            }
            finally
            {
                try { if (Directory.Exists(testRoot)) Directory.Delete(testRoot, true); } catch { }
            }
        }

        private static CodePageSnapshot ReadCurrent()
        {
            using (RegistryKey key = Registry.LocalMachine.OpenSubKey(CodePageRegistryPath))
            {
                if (key == null) return null;
                CodePageSnapshot snapshot = new CodePageSnapshot
                {
                    CreatedUtc = DateTime.UtcNow.ToString("o"),
                    ACP = Convert.ToString(key.GetValue("ACP")),
                    OEMCP = Convert.ToString(key.GetValue("OEMCP")),
                    MACCP = Convert.ToString(key.GetValue("MACCP"))
                };
                return IsValidSnapshot(snapshot) ? snapshot : null;
            }
        }

        private static void WriteSnapshot(CodePageSnapshot snapshot)
        {
            if (!IsValidSnapshot(snapshot)) throw new InvalidDataException("代码页数据无效，已拒绝写入注册表。");
            using (RegistryKey key = Registry.LocalMachine.OpenSubKey(CodePageRegistryPath, true))
            {
                if (key == null) throw new InvalidOperationException("无法打开系统代码页设置。");
                key.SetValue("ACP", snapshot.ACP, RegistryValueKind.String);
                key.SetValue("OEMCP", snapshot.OEMCP, RegistryValueKind.String);
                key.SetValue("MACCP", snapshot.MACCP, RegistryValueKind.String);
            }
        }

        private static string SaveSnapshot(CodePageSnapshot snapshot, string prefix)
        {
            Directory.CreateDirectory(BackupRoot);
            string path = Path.Combine(BackupRoot, prefix + "-" + DateTime.Now.ToString("yyyyMMdd-HHmmss-fff") + ".ini");
            WriteSnapshotFile(snapshot, path);
            return path;
        }

        private static void WriteSnapshotFile(CodePageSnapshot snapshot, string path)
        {
            if (!IsValidSnapshot(snapshot)) throw new InvalidDataException("代码页备份数据无效。");
            string[] lines =
            {
                "schemaVersion=1",
                "createdUtc=" + (snapshot.CreatedUtc ?? DateTime.UtcNow.ToString("o")),
                "ACP=" + snapshot.ACP,
                "OEMCP=" + snapshot.OEMCP,
                "MACCP=" + snapshot.MACCP
            };
            File.WriteAllLines(path, lines, new UTF8Encoding(false));
        }

        private static CodePageSnapshot LoadSnapshot(string path)
        {
            if (String.IsNullOrEmpty(path) || !File.Exists(path)) return null;
            try
            {
                Dictionary<string, string> values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                foreach (string line in File.ReadAllLines(path))
                {
                    int separator = line.IndexOf('=');
                    if (separator <= 0) continue;
                    values[line.Substring(0, separator).Trim()] = line.Substring(separator + 1).Trim();
                }
                string schema;
                if (!values.TryGetValue("schemaVersion", out schema) || schema != "1") return null;
                CodePageSnapshot snapshot = new CodePageSnapshot();
                values.TryGetValue("createdUtc", out snapshot.CreatedUtc);
                values.TryGetValue("ACP", out snapshot.ACP);
                values.TryGetValue("OEMCP", out snapshot.OEMCP);
                values.TryGetValue("MACCP", out snapshot.MACCP);
                return IsValidSnapshot(snapshot) ? snapshot : null;
            }
            catch { return null; }
        }

        private static string GetLatestOriginalBackup()
        {
            try
            {
                if (!Directory.Exists(BackupRoot)) return null;
                return Directory.GetFiles(BackupRoot, "utf8-original-*.ini")
                    .OrderByDescending(path => path, StringComparer.OrdinalIgnoreCase).FirstOrDefault();
            }
            catch { return null; }
        }

        private static bool IsValidSnapshot(CodePageSnapshot snapshot)
        {
            return snapshot != null && IsValidCodePage(snapshot.ACP) &&
                IsValidCodePage(snapshot.OEMCP) && IsValidCodePage(snapshot.MACCP);
        }

        private static bool IsValidCodePage(string value)
        {
            return !String.IsNullOrWhiteSpace(value) && Regex.IsMatch(value, @"^\d{1,5}$");
        }
    }

    internal static class CandidateSelfTest
    {
        public static bool Run(string reportPath)
        {
            List<string> lines = new List<string>();
            bool allPassed = true;
            Action<string, bool> record = delegate(string name, bool passed)
            {
                lines.Add(name + "=" + (passed ? "PASS" : "FAIL"));
                if (!passed) allPassed = false;
            };

            PythonProbe missingPython = new PythonProbe { Available = false };
            PythonProbe oldPython = new PythonProbe
            {
                Available = true,
                Major = 3,
                Minor = 10,
                Version = "Python 3.10.0",
                Executable = "mock-python.exe"
            };
            PythonProbe readyPython = new PythonProbe
            {
                Available = true,
                Major = 3,
                Minor = 11,
                Version = "Python 3.11.0",
                Executable = "mock-python.exe"
            };

            record("PYTHON_MISSING", Detector.EvaluatePythonForSelfTest(missingPython, false, false, false).Level == CheckLevel.Missing);
            record("PYTHON_TOO_OLD", Detector.EvaluatePythonForSelfTest(oldPython, true, true, true).Level == CheckLevel.Warning);
            record("PYTHON_PIP_BROKEN", Detector.EvaluatePythonForSelfTest(readyPython, true, false, true).Level == CheckLevel.Warning);
            record("PYTHON_VENV_BROKEN", Detector.EvaluatePythonForSelfTest(readyPython, true, true, false).Level == CheckLevel.Warning);
            record("PYTHON_READY", Detector.EvaluatePythonForSelfTest(readyPython, true, true, true).Level == CheckLevel.Ready);
            record("INTEGRATION_WITHOUT_PYTHON", Detector.EvaluateIntegrationForSelfTest(missingPython, true).Level == CheckLevel.Missing);
            record("INTEGRATION_MISSING", Detector.EvaluateIntegrationForSelfTest(readyPython, false).Level == CheckLevel.Missing);
            record("INTEGRATION_READY", Detector.EvaluateIntegrationForSelfTest(readyPython, true).Level == CheckLevel.Ready);
            record("WINGET_MISSING", RepairEngine.EvaluatePrerequisiteForSelfTest("Git", false, true) != null);
            record("PYTHON_FOR_PACKAGE_MISSING", RepairEngine.EvaluatePrerequisiteForSelfTest("PyYAML", true, false) != null);
            record("REPAIR_PREREQUISITES_READY", RepairEngine.EvaluatePrerequisiteForSelfTest("Git", true, true) == null);

            string utf8Report = Path.Combine(Path.GetTempPath(), "EnvironmentDetectorUtf8SelfTest-" + Guid.NewGuid().ToString("N") + ".txt");
            try
            {
                record("UTF8_BACKUP_FORMAT", Utf8Repair.RunFileFormatSelfTest(utf8Report));
            }
            finally
            {
                try { if (File.Exists(utf8Report)) File.Delete(utf8Report); } catch { }
            }
            lines.Add("SYSTEM_CHANGES=0");
            string parent = Path.GetDirectoryName(Path.GetFullPath(reportPath));
            if (!String.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);
            File.WriteAllLines(reportPath, lines.ToArray(), new UTF8Encoding(false));
            return allPassed;
        }
    }

    internal static class ModernUi
    {
        public static GraphicsPath RoundedRectangle(Rectangle bounds, int radius)
        {
            int diameter = Math.Max(2, radius * 2);
            GraphicsPath path = new GraphicsPath();
            path.AddArc(bounds.Left, bounds.Top, diameter, diameter, 180, 90);
            path.AddArc(bounds.Right - diameter, bounds.Top, diameter, diameter, 270, 90);
            path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
            path.AddArc(bounds.Left, bounds.Bottom - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    internal sealed class ModernButton : Button
    {
        public ModernButton(string text, Color color)
        {
            Text = text;
            BackColor = color;
            ForeColor = Color.White;
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            FlatAppearance.MouseOverBackColor = ControlPaint.Light(color, 0.08F);
            FlatAppearance.MouseDownBackColor = ControlPaint.Dark(color, 0.08F);
            Cursor = Cursors.Hand;
            Font = new Font("Microsoft YaHei UI", 9.5F, FontStyle.Bold);
            Height = 42;
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            if (Width <= 0 || Height <= 0) return;
            using (GraphicsPath path = ModernUi.RoundedRectangle(new Rectangle(0, 0, Width, Height), 9))
                Region = new Region(path);
        }
    }

    internal sealed class ResultCard : Panel
    {
        private readonly Label detail;
        private readonly Label status;

        public ResultCard(CheckResult result)
        {
            Height = 118;
            Margin = new Padding(0, 0, 0, 12);
            Padding = new Padding(0);
            BackColor = Color.FromArgb(22, 28, 39);
            DoubleBuffered = true;

            Color accent = result.Level == CheckLevel.Ready
                ? Color.FromArgb(34, 197, 94)
                : (result.Level == CheckLevel.Warning ? Color.FromArgb(245, 158, 11) : Color.FromArgb(239, 68, 68));
            string statusText = result.Level == CheckLevel.Ready ? "✓  合格" : (result.Level == CheckLevel.Warning ? "!  需处理" : "×  缺少");

            Label accentDot = new Label
            {
                Text = "●",
                ForeColor = accent,
                BackColor = Color.Transparent,
                AutoSize = true,
                Font = new Font("Microsoft YaHei UI", 8F, FontStyle.Bold),
                Location = new Point(22, 14)
            };
            Label group = new Label
            {
                Text = result.Importance + " · " + result.Group,
                ForeColor = Color.FromArgb(139, 151, 169),
                Font = new Font("Microsoft YaHei UI", 8.5F, FontStyle.Regular),
                AutoSize = true,
                Location = new Point(40, 15),
                BackColor = Color.Transparent
            };
            Label name = new Label
            {
                Text = result.Name,
                ForeColor = Color.FromArgb(244, 247, 252),
                Font = new Font("Microsoft YaHei UI", 12F, FontStyle.Bold),
                AutoEllipsis = true,
                Location = new Point(22, 42),
                Size = new Size(520, 28),
                BackColor = Color.Transparent
            };
            status = new Label
            {
                Text = statusText,
                ForeColor = accent,
                BackColor = Color.FromArgb(31, 38, 51),
                Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Bold),
                TextAlign = ContentAlignment.MiddleCenter,
                Size = new Size(102, 28)
            };
            detail = new Label
            {
                Text = result.Detail + (result.Level == CheckLevel.Ready ? "" : "   " + result.Guidance),
                ForeColor = Color.FromArgb(190, 199, 213),
                Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular),
                AutoEllipsis = true,
                Location = new Point(22, 79),
                Height = 26,
                BackColor = Color.Transparent
            };

            Controls.Add(accentDot);
            Controls.Add(group);
            Controls.Add(name);
            Controls.Add(status);
            Controls.Add(detail);
            Resize += delegate { LayoutCard(name); };
        }

        private void LayoutCard(Label name)
        {
            status.Left = Math.Max(220, ClientSize.Width - status.Width - 22);
            status.Top = 11;
            name.Width = Math.Max(180, ClientSize.Width - name.Left - 22);
            detail.Width = Math.Max(300, ClientSize.Width - detail.Left - 22);
            using (GraphicsPath statusPath = ModernUi.RoundedRectangle(new Rectangle(0, 0, status.Width, status.Height), 9))
                status.Region = new Region(statusPath);
            using (GraphicsPath cardPath = ModernUi.RoundedRectangle(new Rectangle(0, 0, Width, Height), 14))
                Region = new Region(cardPath);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            base.OnPaint(e);
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (GraphicsPath path = ModernUi.RoundedRectangle(new Rectangle(0, 0, Width - 1, Height - 1), 14))
            using (Pen pen = new Pen(Color.FromArgb(47, 57, 72)))
                e.Graphics.DrawPath(pen, path);
        }
    }

    internal sealed class MainForm : Form
    {
        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

        private bool codexMode;
        private readonly Label titleLabel;
        private readonly Label summary;
        private readonly Label note;
        private readonly FlowLayoutPanel resultsPanel;
        private readonly ModernButton refreshButton;
        private readonly ModernButton copyButton;
        private readonly ModernButton repairButton;
        private readonly ModernButton restoreUtf8Button;
        private readonly EventWaitHandle softwareRequest;
        private readonly EventWaitHandle codexRequest;
        private readonly System.Windows.Forms.Timer requestTimer;
        private bool scanRunning;
        private List<CheckResult> lastResults = new List<CheckResult>();

        public MainForm(bool useCodexMode, EventWaitHandle softwareEvent, EventWaitHandle codexEvent)
        {
            codexMode = useCodexMode;
            softwareRequest = softwareEvent;
            codexRequest = codexEvent;
            string moduleName = codexMode ? "Codex 环境补全" : "软件安装检查";
            Text = moduleName + " · Codex 工具箱";
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(980, 660);
            Size = new Size(1160, 760);
            BackColor = Color.FromArgb(10, 14, 22);
            Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular, GraphicsUnit.Point);
            AutoScaleMode = AutoScaleMode.Dpi;

            Panel header = new Panel { Dock = DockStyle.Top, Height = 154, BackColor = Color.FromArgb(13, 18, 29) };
            Label eyebrow = new Label
            {
                Text = "CODEX TOOLS  ·  开发环境工具",
                ForeColor = Color.FromArgb(96, 165, 250),
                Font = new Font(Font.FontFamily, 8.5F, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(32, 22)
            };
            titleLabel = new Label
            {
                Text = moduleName,
                ForeColor = Color.FromArgb(248, 250, 252),
                Font = new Font(Font.FontFamily, 24F, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(28, 43)
            };
            summary = new Label
            {
                Text = "准备检测…",
                ForeColor = Color.FromArgb(74, 222, 128),
                Font = new Font(Font.FontFamily, 11F, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(32, 94)
            };
            note = new Label
            {
                Text = codexMode
                    ? "检测、补全、复查在同一个窗口完成；需要重启时会明确提示。"
                    : "只检查需要用户亲自安装的软件，不会下载或安装大型应用。",
                ForeColor = Color.FromArgb(148, 163, 184),
                AutoSize = true,
                Location = new Point(32, 122)
            };
            header.Controls.Add(eyebrow);
            header.Controls.Add(titleLabel);
            header.Controls.Add(summary);
            header.Controls.Add(note);

            resultsPanel = new FlowLayoutPanel
            {
                Dock = DockStyle.Fill,
                BackColor = Color.FromArgb(10, 14, 22),
                AutoScroll = true,
                FlowDirection = FlowDirection.TopDown,
                WrapContents = false,
                Padding = new Padding(0, 0, 4, 12)
            };
            resultsPanel.Resize += delegate { ResizeResultCards(); };

            Panel sectionHeader = new Panel { Dock = DockStyle.Top, Height = 50, BackColor = Color.FromArgb(10, 14, 22) };
            Label sectionTitle = new Label
            {
                Text = "环境检查结果",
                ForeColor = Color.FromArgb(226, 232, 240),
                Font = new Font(Font.FontFamily, 11F, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(0, 12)
            };
            Label sectionHint = new Label
            {
                Text = "必需 / 推荐 / 业务可选  ·  绿色合格 · 黄色需处理 · 红色缺少",
                ForeColor = Color.FromArgb(100, 116, 139),
                AutoSize = true,
                Top = 15,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            sectionHeader.Controls.Add(sectionTitle);
            sectionHeader.Controls.Add(sectionHint);
            sectionHeader.Resize += delegate { sectionHint.Left = sectionHeader.ClientSize.Width - sectionHint.Width; };

            Panel content = new Panel { Dock = DockStyle.Fill, BackColor = Color.FromArgb(10, 14, 22), Padding = new Padding(28, 6, 28, 8) };
            content.Controls.Add(resultsPanel);
            content.Controls.Add(sectionHeader);

            Panel footer = new Panel { Dock = DockStyle.Bottom, Height = 86, BackColor = Color.FromArgb(13, 18, 29) };
            refreshButton = new ModernButton("重新检测", Color.FromArgb(37, 99, 235)) { Width = 126, Left = 28, Top = 21 };
            copyButton = new ModernButton("复制报告", Color.FromArgb(51, 65, 85)) { Width = 126, Left = 166, Top = 21, Enabled = false };
            repairButton = new ModernButton("一键自动补全", Color.FromArgb(22, 163, 74)) { Width = 158, Left = 304, Top = 21, Visible = codexMode, Enabled = false };
            restoreUtf8Button = new ModernButton("恢复原编码", Color.FromArgb(71, 85, 105))
            {
                Width = 146,
                Left = 474,
                Top = 21,
                Visible = codexMode && Utf8Repair.CanRestore(),
                Enabled = codexMode && Utf8Repair.CanRestore()
            };
            Label privacy = new Label
            {
                Text = "只读检测 · 报告不保存 · 不上传数据",
                AutoSize = true,
                ForeColor = Color.FromArgb(100, 116, 139),
                Top = 34,
                Anchor = AnchorStyles.Top | AnchorStyles.Right
            };
            footer.Controls.Add(refreshButton);
            footer.Controls.Add(copyButton);
            footer.Controls.Add(repairButton);
            footer.Controls.Add(restoreUtf8Button);
            footer.Controls.Add(privacy);
            footer.Resize += delegate { privacy.Left = footer.ClientSize.Width - privacy.Width - 30; };

            Controls.Add(content);
            Controls.Add(footer);
            Controls.Add(header);

            refreshButton.Click += async delegate { await RunScan(); };
            copyButton.Click += delegate { CopyReport(); };
            repairButton.Click += async delegate { await RunAutomaticRepair(); };
            restoreUtf8Button.Click += async delegate { await RunRestoreUtf8(); };
            requestTimer = new System.Windows.Forms.Timer { Interval = 250 };
            requestTimer.Tick += async delegate
            {
                if (scanRunning) return;
                bool hasRequest = false;
                bool requestedCodexMode = codexMode;
                if (codexRequest.WaitOne(0))
                {
                    hasRequest = true;
                    requestedCodexMode = true;
                }
                if (softwareRequest.WaitOne(0))
                {
                    hasRequest = true;
                    requestedCodexMode = false;
                }
                if (hasRequest) await SwitchMode(requestedCodexMode);
            };
            Shown += async delegate
            {
                requestTimer.Start();
                await RunScan();
            };
        }

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            requestTimer.Stop();
            requestTimer.Dispose();
            base.OnFormClosed(e);
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            try
            {
                int enabled = 1;
                DwmSetWindowAttribute(Handle, 20, ref enabled, sizeof(int));
                int rounded = 2;
                DwmSetWindowAttribute(Handle, 33, ref rounded, sizeof(int));
            }
            catch { }
        }

        private async Task RunScan()
        {
            if (scanRunning) return;
            scanRunning = true;
            refreshButton.Enabled = false;
            copyButton.Enabled = false;
            repairButton.Enabled = false;
            if (codexMode)
            {
                repairButton.Text = "正在检查…";
                repairButton.BackColor = Color.FromArgb(51, 65, 85);
            }
            summary.ForeColor = Color.FromArgb(96, 165, 250);
            summary.Text = codexMode ? "正在检测 7 项可补全环境…" : "正在检测 3 项软件与集成环境…";
            resultsPanel.Controls.Clear();
            try
            {
                List<CheckResult> allResults = await Task.Run(() => Detector.ScanAll());
                HashSet<string> manualItems = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
                {
                    "开发工具", "基础开发环境", "编辑器集成"
                };
                List<CheckResult> results = allResults.Where(item => codexMode != manualItems.Contains(item.Name)).ToList();
                lastResults = results;
                RenderResults(results);
            }
            catch (Exception ex)
            {
                summary.ForeColor = Color.FromArgb(248, 113, 113);
                summary.Text = "检测失败：" + ex.Message;
            }
            finally
            {
                refreshButton.Enabled = true;
                copyButton.Enabled = lastResults.Count > 0;
                scanRunning = false;
                UpdateRepairButtons();
            }
        }

        private async Task SwitchMode(bool useCodexMode)
        {
            if (codexMode != useCodexMode)
            {
                codexMode = useCodexMode;
                string moduleName = codexMode ? "Codex 环境补全" : "软件安装检查";
                Text = moduleName + " · Codex 工具箱";
                titleLabel.Text = moduleName;
                note.Text = codexMode
                    ? "检测、补全、复查在同一个窗口完成；需要重启时会明确提示。"
                    : "检查开发工具、基础开发环境与编辑器集成；不会安装大型应用。";
                repairButton.Visible = codexMode;
                restoreUtf8Button.Visible = codexMode && Utf8Repair.CanRestore();
                lastResults = new List<CheckResult>();
                await RunScan();
            }
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Show();
            Activate();
        }

        private void UpdateRepairButtons()
        {
            repairButton.Visible = codexMode;
            if (codexMode)
            {
                bool needsRepair = RepairEngine.GetAutomaticItems(lastResults).Count > 0;
                repairButton.Text = needsRepair ? "一键自动补全" : "已配置齐全";
                repairButton.BackColor = needsRepair ? Color.FromArgb(22, 163, 74) : Color.FromArgb(51, 65, 85);
                repairButton.Enabled = needsRepair;
            }
            else
            {
                repairButton.Enabled = false;
            }
            restoreUtf8Button.Visible = codexMode && Utf8Repair.CanRestore();
            restoreUtf8Button.Enabled = restoreUtf8Button.Visible;
        }

        private async Task RunRestoreUtf8()
        {
            if (!Utf8Repair.CanRestore())
            {
                MessageBox.Show("没有找到可用的修改前编码备份。", "无法恢复", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            string message = "将把系统代码页恢复为启用 UTF-8 之前保存的值。\r\n\r\n" +
                "恢复完成后必须重启 Windows 才能完整生效。是否继续？";
            if (MessageBox.Show(message, "确认恢复原编码", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
                return;

            scanRunning = true;
            refreshButton.Enabled = false;
            copyButton.Enabled = false;
            repairButton.Enabled = false;
            restoreUtf8Button.Enabled = false;
            summary.ForeColor = Color.FromArgb(96, 165, 250);
            summary.Text = "正在恢复修改前编码…";
            bool success;
            try
            {
                success = await Task.Run(() => Utf8Repair.StartElevatedRestore());
            }
            finally
            {
                scanRunning = false;
            }
            MessageBox.Show(success
                    ? "原编码已恢复。必须重启 Windows 才能完整生效。"
                    : "恢复没有完成；系统已尽力保持执行前状态。",
                success ? "恢复完成" : "恢复失败", MessageBoxButtons.OK,
                success ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
            await RunScan();
        }

        private async Task RunAutomaticRepair()
        {
            List<string> targets = RepairEngine.GetAutomaticItems(lastResults);
            if (targets.Count == 0)
            {
                MessageBox.Show("当前没有可自动补全的项目。", "无需处理", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            bool includesUtf8 = targets.Contains("UTF-8 全球语言支持");
            string message = "本工具将自行补全以下项目：\r\n\r\n• " + String.Join("\r\n• ", targets.ToArray()) +
                (includesUtf8 ? "\r\n\r\nUTF-8 设置需要管理员权限，完成后必须重启 Windows。" : "") +
                "\r\n\r\n过程中可能显示 Windows 权限确认。是否继续？";
            if (MessageBox.Show(message, "确认一键自动补全", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
                return;

            scanRunning = true;
            refreshButton.Enabled = false;
            copyButton.Enabled = false;
            repairButton.Enabled = false;
            summary.ForeColor = Color.FromArgb(96, 165, 250);
            summary.Text = "正在自动补全，请不要关闭窗口…";
            try
            {
                List<RepairResult> results = await Task.Run(() => RepairEngine.Repair(lastResults));
                if (includesUtf8)
                {
                    bool utf8Success = await Task.Run(() => Utf8Repair.StartElevated());
                    results.Add(new RepairResult
                    {
                        Name = "UTF-8 全球语言支持",
                        Success = utf8Success,
                        Detail = utf8Success ? "设置完成；必须重启 Windows 才能完整生效。" : "未完成，可能是管理员权限确认被取消。"
                    });
                }
                StringBuilder report = new StringBuilder();
                foreach (RepairResult result in results)
                    report.AppendLine((result.Success ? "✓ " : "× ") + result.Name + "：" + result.Detail);
                MessageBox.Show(report.ToString(), "自动补全结果", MessageBoxButtons.OK,
                    results.All(item => item.Success) ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
            }
            finally
            {
                scanRunning = false;
            }
            await RunScan();
        }

        private void RenderResults(List<CheckResult> results)
        {
            resultsPanel.SuspendLayout();
            resultsPanel.Controls.Clear();
            foreach (CheckResult result in results)
                resultsPanel.Controls.Add(new ResultCard(result));
            ResizeResultCards();
            resultsPanel.ResumeLayout();

            int ready = results.Count(item => item.Level == CheckLevel.Ready);
            int warning = results.Count(item => item.Level == CheckLevel.Warning);
            int missing = results.Count(item => item.Level == CheckLevel.Missing);
            summary.ForeColor = missing > 0
                ? Color.FromArgb(248, 113, 113)
                : (warning > 0 ? Color.FromArgb(251, 191, 36) : Color.FromArgb(74, 222, 128));
            summary.Text = "检测完成  ·  " + ready + " 项合格  ·  " + warning + " 项需处理  ·  " + missing + " 项缺少";
        }

        private void ResizeResultCards()
        {
            int width = Math.Max(360, resultsPanel.ClientSize.Width - resultsPanel.Padding.Horizontal - SystemInformation.VerticalScrollBarWidth - 6);
            foreach (Control control in resultsPanel.Controls)
                if (control is ResultCard) control.Width = width;
        }

        private void CopyReport()
        {
            Clipboard.SetText(ReportBuilder.Build(lastResults, codexMode));
            copyButton.Text = "已复制";
            System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer { Interval = 1500 };
            timer.Tick += delegate { copyButton.Text = "复制报告"; timer.Stop(); timer.Dispose(); };
            timer.Start();
        }
    }

    internal static class ReportBuilder
    {
        public static string Build(IEnumerable<CheckResult> results, bool codexMode)
        {
            StringBuilder report = new StringBuilder();
            report.AppendLine(codexMode ? "Codex 环境补全 v1.0.0" : "软件安装检查 v1.0.0");
            report.AppendLine("检测时间：" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
            report.AppendLine(codexMode
                ? "范围：可由本工具自行安装或配置的环境"
                : "范围：开发工具、基础开发环境与编辑器集成");
            report.AppendLine();
            foreach (CheckResult result in results)
            {
                string status = result.Level == CheckLevel.Ready ? "合格" : (result.Level == CheckLevel.Warning ? "需处理" : "缺少");
                report.AppendLine("[" + result.Importance + "][" + status + "] " + result.Name);
                report.AppendLine("  检测：" + result.Detail);
                if (result.Level != CheckLevel.Ready) report.AppendLine("  建议：" + result.Guidance);
            }
            report.AppendLine();
            report.AppendLine(codexMode
                ? "可返回本工具点击“一键自动补全”；如处理了 UTF-8，请按完成提示重启 Windows。"
                : "以上软件、工作负载和编辑器扩展只做检测，不会自动安装；请用户完成安装后再重新检测。");
            return report.ToString();
        }
    }

    internal static class Program
    {
        [STAThread]
        private static void Main(string[] args)
        {
            bool codexMode = Path.GetFileNameWithoutExtension(Application.ExecutablePath)
                .IndexOf("CodexEnvironmentHelper", StringComparison.OrdinalIgnoreCase) >= 0;
            List<string> effectiveArguments = new List<string>(args ?? new string[0]);
            if (effectiveArguments.Count >= 2 &&
                String.Equals(effectiveArguments[0], "--mode", StringComparison.OrdinalIgnoreCase))
            {
                string requestedMode = effectiveArguments[1];
                if (!String.Equals(requestedMode, "software", StringComparison.OrdinalIgnoreCase) &&
                    !String.Equals(requestedMode, "codex", StringComparison.OrdinalIgnoreCase))
                {
                    Environment.ExitCode = 2;
                    return;
                }
                codexMode = String.Equals(requestedMode, "codex", StringComparison.OrdinalIgnoreCase);
                effectiveArguments.RemoveRange(0, 2);
                args = effectiveArguments.ToArray();
            }
            if (args.Length == 1 && String.Equals(args[0], "--enable-utf8", StringComparison.OrdinalIgnoreCase))
            {
                Environment.ExitCode = Utf8Repair.Apply();
                return;
            }
            if (args.Length == 1 && String.Equals(args[0], "--restore-utf8", StringComparison.OrdinalIgnoreCase))
            {
                Environment.ExitCode = Utf8Repair.Restore();
                return;
            }
            if (args.Length == 2 && String.Equals(args[0], "--self-test-utf8", StringComparison.OrdinalIgnoreCase))
            {
                Environment.ExitCode = Utf8Repair.RunFileFormatSelfTest(args[1]) ? 0 : 1;
                return;
            }
            if (args.Length == 2 && String.Equals(args[0], "--self-test-scenarios", StringComparison.OrdinalIgnoreCase))
            {
                Environment.ExitCode = CandidateSelfTest.Run(args[1]) ? 0 : 1;
                return;
            }
            if (args.Length == 2 && String.Equals(args[0], "--report", StringComparison.OrdinalIgnoreCase))
            {
                HashSet<string> manualItems = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
                {
                    "开发工具", "基础开发环境", "编辑器集成"
                };
                List<CheckResult> results = Detector.ScanAll()
                    .Where(item => codexMode != manualItems.Contains(item.Name)).ToList();
                File.WriteAllText(args[1], ReportBuilder.Build(results, codexMode), new UTF8Encoding(false));
                return;
            }
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            bool createdNew;
            using (Mutex mutex = new Mutex(true, SingleWindow.MutexName, out createdNew))
            using (EventWaitHandle softwareEvent = new EventWaitHandle(false, EventResetMode.AutoReset, SingleWindow.SoftwareEventName))
            using (EventWaitHandle codexEvent = new EventWaitHandle(false, EventResetMode.AutoReset, SingleWindow.CodexEventName))
            {
                if (!createdNew)
                {
                    if (codexMode) codexEvent.Set(); else softwareEvent.Set();
                    SingleWindow.ActivateExistingWindow();
                    return;
                }
                try
                {
                    Application.Run(new MainForm(codexMode, softwareEvent, codexEvent));
                }
                finally
                {
                    mutex.ReleaseMutex();
                }
            }
        }
    }
}
