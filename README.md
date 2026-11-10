# CodexTools · 正式安装版

Windows 上的 Codex 工具箱。当前版本 **0.32.30**，UpdreamBridge **1.4.0**。

## 下载与更新

**[下载正式安装包](https://github.com/Doorham/CodexPlugins/releases/latest)**

下载 `CodexTools-Setup-0.32.30.exe`，双击安装或更新。工具箱无需自行克隆源码、配置Python环境或编译；使用Windows 10/11，界面需要Microsoft Edge WebView2 Runtime。

这次先更新工具箱，再在“本机”页更新UpdreamBridge至1.4.0；未装的从“插件中心”安装。UDB模型、图片／视频校验和第三方接口归插件，后续同协议业务变更只更新插件。原有登录、配置与任务记录保留。

[本版更新说明](RELEASE-NOTES.md) · [插件库](https://github.com/Doorham/CodexTools-Plugins)

## 主要能力

插件中心按需安装和更新，包含语音监听、完成提示音、环境检测、图片／视频创作等工具。UDB收录绘梦2.1及原图片模型，并支持Seedance2.5、Seedance2.0和Wan3.0对应的视频模式。第三方生成服务按其自身账号、额度与计费规则使用。

程序、插件和个人状态保存在本机 `%LOCALAPPDATA%\CodexTools`，插件更新不要求重新登录；本仓库和安装包不包含个人登录数据。

## 旧散装版

此仓库现用入口已转为正式安装版分发。旧散装源码及启动方法保存在[历史分支](https://github.com/Doorham/CodexPlugins/tree/legacy/scattered-toolbox)，旧提交和版本标签保留。

GitHub的“Download ZIP / Source code”是发布说明，不是安装包；请下载Release里的Setup。散装版用户先退出旧程序，再安装正式版；旧目录和其中的私人状态不会被安装器删除或自动迁移。

维护：Althy、DRHW、Codex；保留Doorham及历史贡献者署名。自有项目许可见[LICENSE](LICENSE)。
