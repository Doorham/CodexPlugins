# GitHub 更新与外网电脑同步

## 更新模型

网络版把 GitHub 公开仓库 `Doorham/CodexPlugins` 作为唯一客户端更新源：

- 远程名固定为 `origin`。
- 正式分支固定为 `main`。
- 更新只允许快进，不会自动合并、变基或覆盖本地改动。
- Y 盘只用于维护人员留存网络版的发布副本，不是外网电脑的更新源。

## 日常更新

通常直接启动“Codex工具箱”即可。启动器会先检查 GitHub，再打开界面。也可以在界面右上角点击“检查更新”。

希望先检查、暂不安装时，在仓库根目录运行：

```powershell
.\scripts\update-from-origin.ps1 -Mode Check
```

确认安装更新：

```powershell
.\scripts\update-from-origin.ps1 -Mode Apply
```

脚本返回一行 JSON，常见 `status` 如下：

| 状态 | 含义 | 建议 |
| --- | --- | --- |
| `current` | 已是最新版 | 无需操作 |
| `available` | GitHub 有可快进的新版本 | 使用 `-Mode Apply` |
| `updated` | 已更新完成 | 按提示重启工具箱 |
| `local_changes` | 工作树有本地修改 | 先备份并处理修改 |
| `development_branch` | 当前不在 `main` | 开发完成后切回 `main` |
| `diverged` | 本地历史与 GitHub 分叉 | 不要强推或硬重置，联系维护人员 |
| `wrong_remote` | `origin` 不是 GitHub | 按下文修复远程地址 |
| `error` | 网络、权限或环境错误 | 根据错误文字排查 |

## 手动确认版本

```powershell
git status --short --branch
git remote -v
git log -1 --oneline
git tag --points-at HEAD
Get-Content .\ONLINE-RELEASE.json
```

正常情况下应满足：

1. 当前分支是 `main`。
2. 工作树没有未提交改动。
3. `origin` 指向 `https://github.com/Doorham/CodexPlugins.git` 或对应的 GitHub SSH 地址。
4. `ONLINE-RELEASE.json` 的版本与界面版本一致。

## 修复 origin 地址

先查看当前地址：

```powershell
git remote get-url origin
```

只有在确认当前目录是网络版仓库后，才执行：

```powershell
git remote set-url origin https://github.com/Doorham/CodexPlugins.git
```

不要把内网版 `C:\Works\CodexTools` 的 Y 盘 `origin` 改成 GitHub。建议外网电脑把网络版克隆到独立目录，避免两个版本混用。

## 新电脑安全同步

在新电脑上：

```powershell
New-Item -ItemType Directory -Path C:\Works -Force
git clone https://github.com/Doorham/CodexPlugins.git C:\Works\CodexPlugins
Set-Location C:\Works\CodexPlugins
.\scripts\bootstrap.ps1
.\scripts\build-helpers.ps1
.\scripts\install-desktop-shortcut.ps1
```

公开读取和更新不要求 GitHub 账号。参与开发并推送代码时，每位贡献者应使用自己的 GitHub 身份，不共享密码、验证码、Token、SSH 私钥或 Git Credential Manager 凭据。

## 更新时保留与不保留的内容

更新会保留仓库之外的本机私人状态，包括私人插件、自定义直连白名单、提示音和代理配置备份。`.runtime` 与 `artifacts` 是本地生成目录，不进入 Git。

仓库内自行修改的源码不会被自动覆盖；检测到本地改动时更新会停止。需要开发功能时，请建立开发分支，不要直接修改 `main`。

## 维护人员发布规则

外网电脑只消费 GitHub `main` 和正式标签。维护人员发布前必须完成版本、源码、敏感信息、测试和文档审计；创建语义化标签后，再把 `main` 与必要标签推送到公开仓库。网络版发布不得反向改变内网 Hub 的权威版本或发布状态。
