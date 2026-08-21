# CodexTools Online

CodexTools Online 是不依赖公司网络盘的网络版工具箱。源码从 GitHub 私有仓库克隆，之后由 `origin/main` 快进更新。

## 边界

- 不包含公司内网 IP、共享名、网络驱动器映射或 Y 盘发布逻辑。
- 不包含原始第三方二进制、对话授权摘要、内部交接历史或任何本机私人状态。
- 自定义白名单和私人插件始终保存在 `%LOCALAPPDATA%\CompanyAIHelpers` 下，不进入 Git。
- 私有 GitHub 仓库的身份验证由 Git Credential Manager 或 SSH 负责；仓库不保存 Token、密码或密钥。

## 快速开始

```powershell
git clone https://github.com/Doorham/CodexTools.git C:\Works\CodexTools
Set-Location C:\Works\CodexTools
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
