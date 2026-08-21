# 私人插件层

## 定位

私人插件用于保存某位员工或某台电脑独有的小功能，避免为了个人差异修改公共模块。它不是权限隔离机制，也不改变“所有员工均可参与公共开发”的规则。

固定目录：

`%LOCALAPPDATA%\CompanyAIHelpers\CodexTools\PrivatePlugins`

该目录位于 Git 仓库之外，因此默认：

- 不进入 Git；
- 不上传 GitHub；
- 不随网络版同步；
- 不进入发布包。

所有新插件都必须从这里开始，而不是直接进入公共模块。私人插件仍必须有语义化 `moduleVersion` 和非空 `developers` 署名；“私人”只表示传播范围，不表示可以匿名或不做版本管理。

插件站的“私人页面”只读取当前电脑此目录下的 `*/plugin.json`。错误清单不会令公共插件页崩溃，而是记录为私人层错误。

## 开发方式

1. 在私人目录下建立以插件 ID 命名的子目录。
2. 参考 `templates\private-plugin\plugin.json.example` 创建 `plugin.json`。
3. 私人 ID 必须以 `private-` 开头。
4. 当前私人层只接受 `process_app` handler；可执行文件必须位于 `%LOCALAPPDATA%\CompanyAIHelpers` 下，且 `processName` 必须与文件名一致。
5. 重新启动插件站后在“私人页面”查看。

## 进入网络版

私人插件不会自动进入网络版。若需变为共享模块，必须以新源码进行独立审计，确认不含本机数据、内网资料或外部二进制后，才能在新版本中正常提交。不在仓库中保存对话授权摘要。

动作白名单用于防止清单直接结束任意进程、改写任意路径或执行任意 shell。
