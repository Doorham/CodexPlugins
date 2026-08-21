# CodexPlugins

CodexPlugins 是面向 Windows 的开源 Codex 插件库，桌面应用名称为 CodexTools Online（Codex工具箱网络版）。源码从 GitHub 公开仓库克隆，之后由 `origin/main` 快进更新。

## 边界

- 不包含公司内网 IP、共享名、网络驱动器映射或 Y 盘发布逻辑。
- 不包含原始第三方二进制、对话授权摘要、内部交接历史或任何本机私人状态。
- 自定义白名单和私人插件始终保存在 `%LOCALAPPDATA%\CompanyAIHelpers` 下，不进入 Git。
- 公开读取和克隆不需要 GitHub 登录；参与者推送代码时使用自己的 Git Credential Manager 或 SSH 身份。仓库不保存 Token、密码或密钥。

## 快速开始

```powershell
git clone https://github.com/Doorham/CodexPlugins.git C:\Works\CodexPlugins
Set-Location C:\Works\CodexPlugins
.\scripts\bootstrap.ps1
.\scripts\build-helpers.ps1
.\scripts\install-desktop-shortcut.ps1
```

双击 `start-plugin-station.vbs` 启动。启动器和界面内“检查更新”都只使用当前克隆的 GitHub `origin/main`。

## 开发

详细中文文档：

- [文档导航](docs/README.md)
- [安装与首次启动](docs/INSTALLATION.md)
- [界面与日常使用](docs/USER-GUIDE.md)
- [全部功能说明](docs/FEATURES.md)
- [GitHub 更新与外网电脑同步](docs/UPDATING.md)
- [安全与隐私边界](docs/SECURITY-PRIVACY.md)
- [常见问题与故障排查](docs/TROUBLESHOOTING.md)

版本和模块边界以 `ONLINE-RELEASE.json` 为准，维护记录见 `docs/DEVLOG.md`。

## 开源许可证

本项目采用 [Apache License 2.0](LICENSE) 开源。使用、修改和分发时请遵守许可证条款；许可证不授予项目名称或商标的额外使用权。
