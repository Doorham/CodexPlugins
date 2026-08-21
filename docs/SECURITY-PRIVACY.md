# 安全与隐私边界

## 总原则

CodexTools Online 是源码可审计的公司内部私有仓库项目。仓库 Private 只表示访问受限，不代表可以把秘密提交进去。任何密码、验证码、Token、密钥、私人配置或内部数据都不得进入 Git 历史。

## 仓库可以包含什么

- 网络版自身的 Python、PowerShell、JavaScript、HTML、CSS 和 C# 源码。
- 构建、启动、更新和测试脚本。
- 不含秘密的公共功能清单、图标和中文文档。
- 版本、模块、开发者署名与排除边界。

## 仓库明确不包含什么

- GitHub 密码、验证码、Personal Access Token、OAuth 凭据或 SSH 私钥。
- 账号资料、对话正文、日志、诊断数据库或 Codex 的 `.codex` 目录。
- 代理订阅、节点、控制密钥、端口配置或私人白名单。
- 私人插件及整个 `%LOCALAPPDATA%\CompanyAIHelpers`。
- 公司内网 IP、共享名、映射盘凭据、Y 盘路径或内部 Hub 交接历史。
- 原始第三方二进制归档、来历不明的 DLL 或个人下载包。
- 不适合跨电脑传播的本机缓存、虚拟环境、构建产物和备份。

## 本机数据

以下内容只保存在当前 Windows 用户目录或本地工作区，并由 `.gitignore` 排除：

| 内容 | 默认位置 | 用途 |
| --- | --- | --- |
| 私人插件 | `%LOCALAPPDATA%\CompanyAIHelpers\CodexTools\PrivatePlugins` | 单台电脑专用功能 |
| 直连自定义项 | `%LOCALAPPDATA%\CompanyAIHelpers\ProxyOverrideBypass` | 用户自定义域名与备份 |
| Codex 代理备份 | `%LOCALAPPDATA%\CompanyAIHelpers\CodexSystemProxy` | 修改前的本机备份 |
| 回答提示音 | `%LOCALAPPDATA%\CompanyAIHelpers\CodexAnswerChime` | 自定义音频与设置 |
| Python 环境 | 仓库内 `.runtime` | 本地依赖环境 |
| 助手构建产物 | 仓库内 `artifacts` | 当前电脑编译出的程序 |

不要把这些目录手动复制进仓库，也不要为了“方便同步”取消忽略规则。

## GitHub 身份验证

- 推荐使用 Git Credential Manager 的浏览器授权，或由本人管理的 SSH 密钥。
- 登录、密码、验证码和安全验证必须由账号本人完成。
- 不把 Token 写进远程 URL，例如禁止 `https://TOKEN@github.com/...`。
- 不通过聊天、截图、文档、批处理或共享盘传递凭据。
- 员工离开项目或电脑丢失时，应及时撤销其 GitHub 仓库访问权和相关凭据。

## 功能权限边界

- 更新器只接受 GitHub 仓库地址，只做 fetch 与快进更新。
- 网络版不映射网络驱动器，不保存公司共享盘地址或凭据。
- 代理相关功能不关闭、不切换 VPN、Clash Verge、Aurora 或 Codex，也不读取节点和订阅。
- 剪贴板助手只在确认 Updream 画布格式时处理图像表示，不上传或保存剪贴板历史。
- 回答提示音不记录对话正文。
- 私人插件仅允许受限的本机进程型清单，不能把任意命令伪装成插件动作。

## 提交前检查清单

维护人员每次发布前至少检查：

```powershell
git status --short
git diff --check
git diff --cached --stat
git diff --cached
git ls-files
git fsck --full
```

并搜索账号、令牌、私钥头、内网地址、共享路径、日志数据库、代理订阅字段及本机绝对路径。只检查当前文件不够；正式发布还应检查将要推送的全部 Git 对象和历史。

发现秘密已经提交时，不要只在下一次提交中删除。应立即停止推送、撤销或轮换秘密，再由维护人员清理尚未公开的 Git 历史；如果已推送，则按泄露事件处理并通知仓库管理员。

## 报障时可以提供什么

可以提供版本号、功能名、复现步骤、界面错误文字，以及确认不含秘密的 `git status --short --branch` 输出。

不要提供密码、验证码、Token、SSH 私钥、代理订阅、私人配置文件、对话内容、诊断数据库或整个用户目录压缩包。
