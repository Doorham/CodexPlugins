# CodexTools Online 中文文档

CodexPlugins 是面向 Windows 电脑的开源 Codex 插件库。本网络版通过 GitHub 公开仓库同步，不依赖任何公司网络盘或内网服务。

## 我应该先看哪一篇？

| 需求 | 文档 |
| --- | --- |
| 第一次安装 | [安装与首次启动](INSTALLATION.md) |
| 学会操作界面 | [界面与日常使用](USER-GUIDE.md) |
| 了解每个功能做什么 | [全部功能说明](FEATURES.md) |
| 在网段外电脑上同步或更新 | [GitHub 更新与外网电脑同步](UPDATING.md) |
| 了解哪些数据会保存、哪些绝不上传 | [安全与隐私边界](SECURITY-PRIVACY.md) |
| 遇到无法克隆、更新失败或功能异常 | [常见问题与故障排查](TROUBLESHOOTING.md) |

## 版本边界

- 网络版从 `v0.10.0` 开始建立独立的干净 Git 历史。
- 网络版不包含网络驱动器映射功能，也不包含依赖外部 DLL 的 Logitech G435 功能。
- 网络版的客户端更新源固定为当前克隆的 GitHub `origin/main`。
- `ONLINE-RELEASE.json` 是版本、模块列表和更新源的机器可读权威文件。
- 源码采用 Apache License 2.0，具体条款见仓库根目录 `LICENSE`。

## 获取帮助时请提供

只提供以下非敏感信息：

1. 界面右上角显示的版本号。
2. 出问题的功能名和操作步骤。
3. 界面中显示的错误文字。
4. `git status --short --branch` 的输出（不要附带凭据或私人文件）。

不要发送 GitHub 密码、验证码、Token、SSH 私钥、代理订阅、完整配置文件、对话正文或诊断数据库。
