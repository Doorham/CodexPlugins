# 常见问题与故障排查

## 克隆提示 Repository not found

本项目是公开仓库，正常 clone/pull 不需要账号权限：

1. 确认地址为 `https://github.com/Doorham/CodexPlugins.git`。
2. 确认浏览器和 Git 能访问 `github.com`。
3. 检查命令中没有多余空格、错字或旧仓库名。
4. 如果 Git 强制使用缓存的错误凭据，只在 Windows“凭据管理器”中移除对应的 GitHub 凭据，不要删除无关凭据。

不要把密码或 Token 直接拼进 clone 命令。

## 系统找不到 git

安装 Git for Windows 后重新打开 PowerShell，检查：

```powershell
git --version
```

应用内更新器也会尝试寻找 Codex 随附的 Git 和常见安装位置，但首次克隆仍建议使用完整的 Git for Windows。

## bootstrap.ps1 失败

先确认 Python：

```powershell
python --version
```

需要 Python 3.11 或更高版本。然后在仓库根目录重新运行：

```powershell
.\scripts\bootstrap.ps1
```

常见原因包括 Python 未加入 PATH、Python 包索引无法访问、公司安全软件拦截虚拟环境，或已有 `.runtime\venv` 损坏。不要在不确认路径的情况下递归删除目录；需要重建环境时，只处理当前仓库的 `.runtime\venv`。

## 找不到助手构建产物

运行：

```powershell
.\scripts\build-helpers.ps1
Get-ChildItem .\artifacts\helpers
```

如果编译失败，请保留完整错误文字并确认 Windows 自带 .NET 编译环境可用。`artifacts` 是本机构建目录，不应提交 Git。

## 桌面快捷方式安装失败

如果提示同名快捷方式不属于 CodexTools，脚本是在保护现有快捷方式。请先在桌面检查“Codex工具箱.lnk”的目标；确认确实不再需要后由本人手动重命名或移走，再重新运行：

```powershell
.\scripts\install-desktop-shortcut.ps1
```

## 界面打不开或一闪而过

在仓库根目录使用开发启动脚本查看错误：

```powershell
.\scripts\run-dev.ps1
```

重点检查：

- `.runtime\venv` 是否存在。
- `apps\plugin-station\requirements.txt` 是否安装成功。
- Microsoft Edge WebView2 Runtime 是否可用。
- 是否在正确的网络版仓库目录运行。

不要通过关闭 Codex、VPN、Clash Verge 或 Aurora 来试错。

## 更新提示 wrong_remote

检查：

```powershell
git remote -v
git remote get-url origin
```

网络版 `origin` 应为 GitHub 地址。确认目录无误后执行：

```powershell
git remote set-url origin https://github.com/Doorham/CodexPlugins.git
```

内网源码工区的 Y 盘 `origin` 不属于网络版，不要修改。

## 更新提示 local_changes

查看改动：

```powershell
git status --short
git diff
```

更新器不会覆盖这些内容。若是自己的开发工作，应提交到独立开发分支；若是不需要的改动，也应先确认每个文件再恢复。不要使用 `git reset --hard` 处理不明改动。

## 更新提示 development_branch 或 diverged

`development_branch` 表示当前不在 `main`，这是为了避免自动更新干扰开发。完成或保存开发工作后，再切回干净的 `main`。

`diverged` 表示本地与 GitHub 已有不同提交。请停止自动处理并联系维护人员，不要强推、强拉、硬重置或改写 GitHub `main`。

## GitHub 访问或身份验证失败

只读更新失败时先检查公开仓库地址和网络，不应要求账号密码。只有贡献者推送代码时才需要通过 Git Credential Manager 或 SSH 授权。不要把密码、验证码、Token 或私钥发送给维护人员；报障只提供错误文字和不含秘密的远程地址。

## “国内网站直连”没有生效

1. 输入纯域名，不带协议、路径、查询参数和端口。
2. 点击“刷新网络”。
3. 确认 Windows 系统代理本身已由用户正常配置。
4. 如果使用 Clash Verge Rev，确认其程序可正常运行；工具箱不会为你切换节点或模式。

仍失败时，只提供域名、界面错误文字和系统代理开关状态，不要发送订阅、节点或控制密钥。

## Codex timeout 修复后仍然超时

“修复连接”只确保 Codex 遵循系统代理；它不能证明代理链路、服务端或本地网络都正常。再运行“检测 WebSocket”，以成功握手作为判断依据。如果失败，请记录状态与耗时，不要发送 `.codex` 全目录、对话数据库或代理订阅。

## Updream 剪贴板助手没有动作

确认助手已开启，并且复制内容确实来自支持的 Updream 画布格式。普通图片、文本、JSON、文件拖放或无效 PNG 会被有意忽略。该行为是安全边界，不代表程序故障。

## 提示音不播放

1. 点击“测试声音”。
2. 检查 Windows 当前输出设备和应用音量。
3. 重新选择 WAV、MP3 或 WMA 文件。
4. 自定义文件失败时应回退到系统提示音。

自定义音频只保存在本机，不随 GitHub 同步。

## Arctis Nova 5 卡片不显示

卡片仅在检测到对应 USB 接收器时显示。接收器未插入时，卡片隐藏且监控器不启动是正常行为；接收器存在但耳机关机时，应显示离线而不是电量。

## 仍需报障

请提供：网络版版本号、具体功能、复现步骤、完整错误文字，以及经过检查的 `git status --short --branch`。不要提供任何凭据、私人插件、代理配置、对话正文、日志数据库或整个 `CompanyAIHelpers` 目录。
