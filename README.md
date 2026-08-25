# CodexPlugins

面向 Windows 的开源本地插件库，把常用的 Codex 网络优化、创作辅助、完成提醒和硬件状态功能集中到一个可视化插件站中。所有公共功能都随源码发布，可在本机审计、构建、启停和更新。

## 主要功能

| 插件 | 解决的问题 | 主要特点 |
| --- | --- | --- |
| Codex 对话 timeout 修复 | Codex 首次建立 Responses WebSocket 时未正确使用 Windows 系统代理 | 仅在缺少配置时修正，已配置后独立检测握手，不把线路异常误报为配置问题 |
| 国内网站直连 | 开启系统代理后，常用国内网站出现不必要的绕路 | 管理 Windows 直连规则，可与 Clash Verge Rev 的绕过项安全同步 |
| Updream 剪贴板清理 | 从 Updream 画布复制的图片难以粘贴到部分 Windows 应用 | 保留原始 PNG，只补充兼容的剪贴板图像格式，不保存剪贴板历史 |
| Codex 完成提示音 | 后台等待 Codex 工作时容易错过完成时机 | 支持自定义 WAV、MP3、WMA，失败时回退到系统提示音 |
| Arctis Nova 5 电量监控 | Windows 缺少直观的耳机电量显示 | 检测 USB 接收器、显示托盘电量、区分耳机离线和监控未启用 |
| 软件安装检查 | 不确定电脑是否具备最低开发条件 | 只读检查开发工具、Python 真实能力及编辑器集成 |
| Codex 环境补全 | 常用终端、多媒体和 Python 工具缺失或配置不完整 | 检测后按确认补全可安全处理的项目，UTF-8 支持备份与恢复 |

更详细的行为和安全边界见 [全部功能说明](docs/FEATURES.md)。

## 设计原则

- **本地优先**：私人插件、自定义白名单、提示音和配置备份只保存在当前电脑。
- **源码交付**：仓库不携带 EXE、DLL、压缩包或来历不明的第三方二进制；助手由安装电脑从源码构建。
- **安全更新**：只从 GitHub `origin/main` 获取更新，仅允许快进，不覆盖本地改动或自动合并分叉历史。
- **最小权限**：不读取账号密码、Token、代理订阅、节点或对话正文，也不关闭或切换 VPN 和代理软件。
- **独立运行**：不依赖公司网络盘、共享路径或内网服务。

## 系统要求

- Windows 10 或 Windows 11
- Python 3.11 或更高版本
- Git for Windows
- Microsoft Edge WebView2 Runtime（Windows 通常已预装）
- 能访问 GitHub 和 Python 包索引的网络

## 安装

在 PowerShell 中执行：

```powershell
New-Item -ItemType Directory -Path C:\Works -Force
git clone https://github.com/Doorham/CodexPlugins.git C:\Works\CodexPlugins
Set-Location C:\Works\CodexPlugins
.\scripts\bootstrap.ps1
.\scripts\build-helpers.ps1
.\scripts\install-desktop-shortcut.ps1
```

安装完成后，双击桌面的“Codex工具箱”快捷方式，或运行：

```powershell
.\start-plugin-station.vbs
```

公开仓库的 clone 和 pull 不要求 GitHub 登录。只有参与开发并推送代码时，才需要使用自己的 Git Credential Manager 或 SSH 身份。

## 更新

正常启动时会检查 GitHub 更新。也可以在仓库根目录手动执行：

```powershell
# 只检查
.\scripts\update-from-origin.ps1 -Mode Check

# 安全快进到最新版
.\scripts\update-from-origin.ps1 -Mode Apply
```

检测到本地改动、开发分支或分叉历史时，更新器会停止并保留现场。

## 安全与隐私

本项目明确不包含：

- 网络驱动器映射、公司共享路径或内网端点管理功能
- Logitech G435 外部 DLL 功能
- GitHub 凭据、代理订阅、节点、控制密钥或私人白名单
- 私人插件、对话正文、日志、诊断数据库或 `.codex` 目录
- 本机构建产物、虚拟环境和缓存

完整规则见 [安全与隐私边界](docs/SECURITY-PRIVACY.md)。

## 中文文档

- [文档导航](docs/README.md)
- [安装与首次启动](docs/INSTALLATION.md)
- [界面与日常使用](docs/USER-GUIDE.md)
- [全部功能说明](docs/FEATURES.md)
- [GitHub 更新与外网电脑同步](docs/UPDATING.md)
- [安全与隐私边界](docs/SECURITY-PRIVACY.md)
- [常见问题与故障排查](docs/TROUBLESHOOTING.md)

## 开发与测试

```powershell
python -m unittest discover -s tests -v
git diff --check
```

发布边界和模块版本以 [ONLINE-RELEASE.json](ONLINE-RELEASE.json) 为准，维护记录见 [开发日志](docs/DEVLOG.md)。

## 开源许可证

本项目采用 [Apache License 2.0](LICENSE) 开源。使用、修改和分发时请遵守许可证条款；许可证不授予项目名称或商标的额外使用权。
