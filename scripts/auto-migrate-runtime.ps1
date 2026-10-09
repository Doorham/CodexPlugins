[CmdletBinding()]
param([switch]$Dispatch, [Parameter(Mandatory=$true)][string]$RequestId,
      [switch]$NoLaunch, [switch]$NoDialog, [switch]$ResumePending)

$ErrorActionPreference='Stop'
throw '自动整目录迁移已停用；工具箱可以直接启动，私人状态保留本机。'
