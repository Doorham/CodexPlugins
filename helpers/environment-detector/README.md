# 开发环境检查与补全助手

该助手由两个公共模块共同使用，底层只安装一个 `%LOCALAPPDATA%\CompanyAIHelpers\EnvironmentDetector\EnvironmentDetector.exe`：

- `--mode software`：软件安装检查，只读检查开发工具、Python 3.11+ 真实能力和编辑器集成。
- `--mode codex`：Codex 环境补全，检查并按用户确认补全 PowerShell 7、Windows Terminal、Git、FFmpeg/FFprobe、PyYAML、yt-dlp 与 UTF-8 系统代码页。

同一时间只允许一个窗口实例。再次点击任一模块时，现有窗口会切换到对应页面，不会继续创建副窗口。

首次检测和重新检测会显示 Microsoft Fluent Emoji 3D 官方八个月相图、当前检测范围和已用时间。原始 256×256 PNG 以 MIT 许可嵌入程序，不依赖联网或系统 emoji 字体，因此能与浏览器中显示的 Fluent 3D 月相保持一致，也不会在旧版 WinForms 中退化成黑白线稿。环境补全运行期间则显示同一套动画以及真实的当前处理项目和项目序号。由于 winget 与 pip 不提供统一且可靠的百分比，界面不显示虚假进度条。第三方来源和完整许可见 `THIRD-PARTY-NOTICES.md`。

补全或编码恢复运行期间，工具会阻止“软件安装检查”和“Codex 环境补全”之间切换，并拦截用户主动关闭窗口；两种操作都会显示“正在安装，先不要切换或关闭窗口”的提示，且不会取消、重启或改写后台任务。最小化窗口、切换到其他软件和 Windows 关机流程不受限制。

## 安全边界

- 不读取或上传账号、Cookie、浏览器数据、代理订阅、对话正文或剪贴板内容。
- VS Code、Visual Studio、Cursor、PyCharm 与 Python 等大型软件只检测，不自动安装。
- Python 检查会在 `%TEMP%\EDV` 创建短路径临时虚拟环境，测试完成后立即清理。
- Git 与 FFmpeg 使用临时仓库和临时媒体做真实能力测试，检测结束后清理。
- UTF-8 修改前保存 ACP、OEMCP、MACCP；任一步失败会回滚。恢复原编码同样需要管理员确认和重启 Windows。
- 本工具不检测、不替换、不注册也不修复 DirectX、系统 DLL、Visual C++ 系统组件或 API Sets。

## 构建与非破坏性测试

在仓库根运行：

```powershell
.\scripts\build-helpers.ps1
```

构建结果固定进入 `artifacts\helpers\EnvironmentDetector.exe`，不会提交到 Git。助手内置以下后台验证入口：

```powershell
.\artifacts\helpers\EnvironmentDetector.exe --self-test-scenarios .\artifacts\environment-scenarios.txt
.\artifacts\helpers\EnvironmentDetector.exe --mode software --report .\artifacts\software-environment-report.txt
.\artifacts\helpers\EnvironmentDetector.exe --mode codex --report .\artifacts\codex-environment-report.txt
```

自测只模拟异常分支和备份格式，不安装软件、不修改注册表。

需要验收安装等待界面时，可启动 32 秒的非破坏性可视化模拟：

```powershell
.\artifacts\helpers\EnvironmentDetector.exe --preview-installation
```

模拟只驱动月相动画、项目名称、序号、耗时以及切换/关闭拦截，不会调用 winget、pip、注册表或管理员权限。
