# 界面与日常使用

## 界面结构

工具箱主窗口分为以下区域：

- **顶部栏**：显示网络版名称和版本，包含最小化、最大化和隐藏到后台按钮。
- **检查更新**：从 GitHub `origin/main` 检查并安全快进更新。
- **公共插件**：显示网络版内置功能。
- **私人页面**：显示当前电脑的本地私人插件；这些内容不上传 GitHub。
- **分类筛选**：按系统、网络、剪贴板、开发环境、硬件或 Agent 联动等类别筛选卡片。
- **刷新按钮**：只重新读取本机状态，不修改配置。

## 开启和停用后台功能

带有“点我开启 / 点我停用”的卡片使用统一行为：

- **开启**：如果本地程序尚未安装，先从 `artifacts\helpers` 安全安装；然后启动程序并添加当前用户自启。
- **停用**：精确停止该功能的进程，并删除它自己的自启项。
- 不会根据模糊的进程名删除其他软件，也不会扫描或清理无关目录。

如果点击开启时提示“构建产物不存在”，先在仓库根目录运行：

```powershell
.\scripts\build-helpers.ps1
```

## 窗口右上角的关闭按钮

右上角 `×` 的默认行为是**隐藏窗口**，而不是结束工具箱进程。这样再次打开桌面快捷方式时会更快。

需要完全退出时，使用界面提供的退出动作，或在确认进程所属后结束工具箱主进程。不要为了关闭工具箱而关闭 Codex、VPN、Clash Verge 或其他无关程序。

## 私人页面

私人插件目录为：

```text
%LOCALAPPDATA%\CompanyAIHelpers\CodexTools\PrivatePlugins
```

特点：

- 不进入 Git 工作树。
- 不上传 GitHub。
- 不随其他电脑克隆或更新。
- 私人插件配置错误不会使公共插件页整体崩溃，而会在私人页面显示错误状态。

点击“打开私人插件目录”仅会用资源管理器打开上述路径。详细格式见 [PRIVATE-PLUGINS.md](PRIVATE-PLUGINS.md)。

## 检查更新

点击“检查更新”后：

1. 验证当前远程是 GitHub。
2. 抓取 `origin/main` 和标签。
3. 比较当前提交与 GitHub 最新提交。
4. 工作树干净、当前分支为 `main`、历史可快进时才会更新。
5. 更新完成后，必要时重建助手、保留本机私人数据，然后重启工具箱。

详细安全机制和命令行方式见 [UPDATING.md](UPDATING.md)。

## 开发环境检查与补全

- **软件安装检查**：只读检查开发工具、Python 3.11+ 的真实运行能力，以及 VS Code、Visual Studio、Cursor 或 PyCharm 与 Python 的集成情况。它不会替用户安装大型编辑器、Python 或 Visual Studio 工作负载。
- **Codex 环境补全**：检查 PowerShell 7、Windows Terminal、Git、FFmpeg/FFprobe、PyYAML、yt-dlp 和 UTF-8。能够明确处理的缺项会在用户确认后补全；复杂的权限、代理、企业策略、Python 或 PATH 异常会显示详情，交由用户或 Codex 继续判断。
- 两张卡片共用一个本地助手。再次点击时会复用现有窗口并切换页面，不会不断打开副窗口；环境补全运行期间也能切到软件检查页，后台任务不会被取消或重启。
- UTF-8 修改或恢复前都会保存代码页快照；操作需要管理员确认，完成后必须重启 Windows 才能让系统范围设置完全生效。

## 本地数据位置

| 数据 | 默认位置 | 是否上传 GitHub |
| --- | --- | --- |
| Python 虚拟环境 | 仓库内 `.runtime\venv` | 否 |
| 构建产物 | 仓库内 `artifacts\helpers` | 否 |
| 私人插件 | `%LOCALAPPDATA%\CompanyAIHelpers\CodexTools\PrivatePlugins` | 否 |
| 自定义直连白名单 | `%LOCALAPPDATA%\CompanyAIHelpers\ProxyOverrideBypass` | 否 |
| Codex 系统代理备份 | `%LOCALAPPDATA%\CompanyAIHelpers\CodexSystemProxy` | 否 |
| Codex/WorkBuddy 任务完成提示音与本地设置 | `%LOCALAPPDATA%\CompanyAIHelpers\CodexAnswerChime` | 否 |
| 环境检查备份与本地状态 | `%LOCALAPPDATA%\CompanyAIHelpers\EnvironmentDetector` | 否 |

详细隐私规则见 [SECURITY-PRIVACY.md](SECURITY-PRIVACY.md)。
