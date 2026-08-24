# 开发环境检查与补全助手

该助手由两个公共模块共同使用，底层只安装一个 `%LOCALAPPDATA%\CompanyAIHelpers\EnvironmentDetector\EnvironmentDetector.exe`：

- `--mode software`：软件安装检查，只读检查开发工具、Python 3.11+ 真实能力和编辑器集成。
- `--mode codex`：Codex 环境补全，检查并按用户确认补全 PowerShell 7、Windows Terminal、Git、FFmpeg/FFprobe、PyYAML、yt-dlp 与 UTF-8 系统代码页。

同一时间只允许一个窗口实例。再次点击任一模块时，现有窗口会切换到对应页面，不会继续创建副窗口。

环境补全运行期间仍可切换到软件检查页查看编译环境。切页只读取缓存结果，补全任务继续使用启动时的独立快照，不会被取消、重启或改写。

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
