# Codex 环境补全

公共自助模块，检测 PowerShell 7、Windows Terminal、UTF-8、Git、FFmpeg/FFprobe、PyYAML 和 yt-dlp。能够明确、安全处理的缺项由工具在用户确认后自动补全；复杂的 Python、PATH、权限、代理或企业策略异常会保留错误详情，供 Codex 继续分析。

UTF-8 修改和恢复均先保存可验证的代码页快照，失败时回滚，并明确提示重启 Windows。该模块不提供 DirectX 或系统 DLL 修复。

补全过程使用启动时的检查结果快照；用户切换到“软件安装检查”页面时任务继续执行，不会因页面切换而取消或重启。
