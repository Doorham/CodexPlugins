[CmdletBinding()]
param([ValidateSet('Stage','Finalize')][string]$Phase = 'Stage', [string]$BackupName = '', [switch]$NoForce)

$ErrorActionPreference = 'Stop'
throw '整目录迁移已停用。个人状态保留原处，不参与公共更新、比较或哈希；请使用本机私人状态恢复入口。工具箱可直接打开。'
