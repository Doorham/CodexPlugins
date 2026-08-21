# Repository instructions

- 本仓库是 CodexTools 网络版，只从 GitHub `origin/main` 更新，不读取或依赖公司网络盘。
- 版本与模块边界以 `ONLINE-RELEASE.json` 为准；每次实质改动在 `docs/DEVLOG.md` 顶部记录开发者、验证和未解决项。
- 不得加入公司内网 IP、共享名、映射盘、Y 盘路径、内部交接文件或提升授权记录。
- 不得加入账号、Token、密钥、Cookie、对话正文、日志、诊断数据库、代理订阅/节点、私人白名单、私人插件或用户目录绝对路径。
- 新的外部二进制默认禁止进入网络版；必须先有可审计来源、明确授权和独立安全评审。
- Python 环境只放在 `.runtime/venv`，构建产物只放在 `artifacts/`，两者都不提交。
- 私人插件只存在 `%LOCALAPPDATA%\CompanyAIHelpers\CodexTools\PrivatePlugins`，不同步、不上传。
- 不得让更新器追踪开发分支、强制覆盖本地改动或从非 GitHub 远程更新。
