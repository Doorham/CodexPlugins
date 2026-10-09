using System;
using System.IO;
using System.Diagnostics;
using System.Security.Principal;
using System.Security.AccessControl;

internal static class RuntimePaths
{
    public static string UserRoot()
    {
        string root = null;
        for (var dir = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory); dir != null; dir = dir.Parent) {
            if (dir.Name == "CompanyAIHelpers" && dir.Parent != null && dir.Parent.Name == ".runtime") { root = dir.FullName; break; }
            if (Directory.Exists(Path.Combine(dir.FullName, "scripts")) && Directory.Exists(Path.Combine(dir.FullName, "apps", "plugin-station"))) {
                root = Path.Combine(dir.FullName, ".runtime", "CompanyAIHelpers"); break;
            }
        }
        if (root == null) {
            var configured = Environment.GetEnvironmentVariable("CODEXTOOLS_DATA_ROOT");
            if (!string.IsNullOrEmpty(configured)) {
                var dir = new DirectoryInfo(configured);
                if (dir.Name == "CompanyAIHelpers" && dir.Parent != null && dir.Parent.Name == ".runtime") root = dir.FullName;
            }
        }
        if (root == null) throw new InvalidOperationException("Cannot locate toolbox installation; personal state was not opened.");
        string sid = WindowsIdentity.GetCurrent().User.Value;
        string user = Path.Combine(root, "Users", sid);
        for (var dir = new DirectoryInfo(user); dir != null; dir = dir.Parent)
            if (dir.Exists && (dir.Attributes & FileAttributes.ReparsePoint) != 0) throw new IOException("User state cannot pass through a link.");
        Directory.CreateDirectory(user);
        var security = new DirectorySecurity();
        security.SetSecurityDescriptorSddlForm("D:P(A;OICI;FA;;;" + sid + ")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)");
        new DirectoryInfo(user).SetAccessControl(security);
        return user;
    }
    public static string ForTool(string component) {
        string path = Path.Combine(UserRoot(), component);
        Directory.CreateDirectory(path);
        return path;
    }
}
