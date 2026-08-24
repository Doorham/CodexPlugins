# 安装与首次启动

## 1. 适用环境

- Windows 10 或 Windows 11。
- 能够访问 `github.com` 和 Python 包索引的网络。
- Python 3.11 或更高版本。
- 建议安装官方 Git for Windows。公开读取和克隆不要求 GitHub 账号；只有参与开发并推送代码时才需要登录授权。
- Microsoft Edge WebView2 Runtime。Windows 10/11 通常已预装。

## 2. 克隆公开仓库

打开 PowerShell，执行：

```powershell
New-Item -ItemType Directory -Path C:\Works -Force
git clone https://github.com/Doorham/CodexPlugins.git C:\Works\CodexPlugins
Set-Location C:\Works\CodexPlugins
```

公开仓库的 clone/pull 不需要密码、验证码或 Token。如果出现 `Repository not found`，先核对仓库地址和网络；不要把凭据写入仓库、脚本、命令行历史或文档。

## 3. 准备 Python 环境

在仓库根目录执行：

```powershell
.\scripts\bootstrap.ps1
```

该脚本会：

- 在 `.runtime\venv` 创建仓库专用 Python 虚拟环境。
- 安装 `pywebview==6.2.1`。
- 幂等保持本机的代理直连规则和 Codex 系统代理设置。
- 不会映射网络驱动器，不会读取 GitHub 密码或代理订阅。

## 4. 构建本地助手

```powershell
.\scripts\build-helpers.ps1
```

构建产物保存在 `artifacts\helpers`，该目录已被 Git 忽略，不会上传 GitHub。当前会从源码构建：

- Updream Clipboard Cleaner
- Codex Answer Chime
- Arctis Nova 5 Battery Monitor
- Arctis Nova 5 Startup Gate
- Environment Detector（“软件安装检查”和“Codex 环境补全”共用）
- Clipboard Verification

## 5. 创建桌面快捷方式

```powershell
.\scripts\install-desktop-shortcut.ps1
```

成功后桌面会出现“Codex工具箱”。脚本只会更新 CodexTools 自己创建的同名快捷方式；如果同名快捷方式属于其他程序，脚本会停止而不覆盖。

## 6. 首次启动

可以双击桌面“Codex工具箱”，或在仓库根目录双击 `start-plugin-station.vbs`。

启动器会先运行 GitHub 更新检查，然后无终端窗口地打开工具箱。如果 GitHub 暂时不可用，更新会失败，但已安装的本地功能不会被删除。

## 7. 安装后建议检查

1. 界面标题为“Codex工具箱网络版”。
2. 版本号与 `ONLINE-RELEASE.json` 一致。
3. 页面中不存在“Codex 网络盘访问”或 Logitech G435 卡片。
4. 右上角“检查更新”使用 GitHub `origin/main`。
5. 用到的后台功能可点击“点我开启”，并在重启 Windows 后确认自启状态。
6. “软件安装检查”和“Codex 环境补全”能分别打开，且同一时间只保留一个工具副窗口。
