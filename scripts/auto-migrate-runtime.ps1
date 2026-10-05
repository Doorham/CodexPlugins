[CmdletBinding()]
param([switch]$Dispatch, [Parameter(Mandatory=$true)][string]$RequestId,
      [switch]$NoLaunch, [switch]$NoDialog)

$ErrorActionPreference = 'Stop'
if ($RequestId -notmatch '^[a-f0-9]{32}$') { throw 'Invalid upgrade request.' }
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $repoRoot '.runtime'
$folder = Join-Path $runtime 'runtime-upgrade'
foreach ($path in @($runtime,$folder)) {
    if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Upgrade destination is a reparse point.'
    }
}
$statePath = Join-Path $folder 'active.json'
if ((Get-Item -LiteralPath $statePath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Upgrade state is a reparse point.'
}
$state = [IO.File]::ReadAllText($statePath) | ConvertFrom-Json
if ($state.requestId -ne $RequestId -or $state.backupName -notmatch '^runtime-move-[0-9-]+$') {
    throw 'Upgrade ownership does not match.'
}
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$taskName = 'CompanyAIHelpers.RuntimeMigration.' + $sid + '.' + $RequestId
$source = 'CompanyAIHelpers.RuntimeMigration/v1'
$powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$workerArguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' +
    $PSCommandPath + '" -RequestId ' + $RequestId
if ($NoLaunch) { $workerArguments += ' -NoLaunch' }
if ($NoDialog) { $workerArguments += ' -NoDialog' }
$form = $null
$taskFolder = $null
function Save-State([string]$Phase) {
    $actual = [IO.File]::ReadAllText($statePath) | ConvertFrom-Json
    if ($actual.requestId -ne $RequestId) { throw 'Upgrade ownership changed.' }
    $state.state = $Phase
    $state.updatedAt = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $temporary = Join-Path $folder ($RequestId + '.tmp')
    [IO.File]::WriteAllText($temporary, ($state | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    [IO.File]::Replace($temporary,$statePath,(Join-Path $folder ($RequestId + '.previous.json')))
}
function Show-Failure {
    if (-not $NoDialog) {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show(
            '自动升级未完成，原数据及备份已保留。请联系维护人员，不要卸载或清理旧目录。' + "`n`n" +
            (Join-Path $runtime ('migration-backups\' + $state.backupName)),
            'Codex工具箱升级', 'OK', 'Warning') | Out-Null
    }
}
try {
    $scheduler = New-Object -ComObject Schedule.Service
    $scheduler.Connect()
    $taskFolder = $scheduler.GetFolder('\')
    if ($Dispatch) {
        # A one-shot interactive-user task escapes a packaged caller's AppData
        # virtualization. No password, SYSTEM account, elevation or Codex needed.
        $definition = $scheduler.NewTask(0)
        $definition.RegistrationInfo.Source = $source
        $definition.RegistrationInfo.Description = 'One-time owned toolbox data migration; no recurring trigger.'
        $definition.Principal.UserId = $sid
        $definition.Principal.LogonType = 3
        $definition.Principal.RunLevel = 0
        $definition.Settings.ExecutionTimeLimit = 'PT0S'
        $definition.Settings.DisallowStartIfOnBatteries = $false
        $definition.Settings.StopIfGoingOnBatteries = $false
        $definition.Settings.AllowDemandStart = $true
        $action = $definition.Actions.Create(0)
        $action.Path = $powershell
        $action.Arguments = $workerArguments
        $action.WorkingDirectory = $repoRoot
        $task = $taskFolder.RegisterTaskDefinition($taskName,$definition,2,$sid,$null,3,$null)
        $task.Run($null) | Out-Null
        exit 0
    }
    if ($state.state -ne 'pending') { throw 'Upgrade is not pending.' }
    Save-State 'running'
    if (-not $NoDialog) {
        Add-Type -AssemblyName System.Windows.Forms
        $form = New-Object Windows.Forms.Form
        $form.Text = 'Codex工具箱正在升级'
        $form.Width = 470; $form.Height = 150
        $form.StartPosition = 'CenterScreen'; $form.ControlBox = $false
        $label = New-Object Windows.Forms.Label
        $label.AutoSize = $true; $label.Left = 22; $label.Top = 24
        $label.Text = '正在自动备份并迁移本机配置，请稍候。' + "`n" + '不会关闭 Codex 或 Tailscale，无需输入命令。'
        $form.Controls.Add($label); $form.Show()
        [Windows.Forms.Application]::DoEvents()
    }
    # EnumWindows includes hidden warm windows, unlike MainWindowHandle.
    # WM_CLOSE is graceful: never terminate an unresponsive process.
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ToolboxUpgradeWindows {
    private delegate bool EnumProc(IntPtr window, IntPtr data);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc callback, IntPtr data);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")] private static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
    public static void CloseOwned(uint processId) {
        EnumWindows(delegate(IntPtr window, IntPtr data) {
            uint owner;
            GetWindowThreadProcessId(window, out owner);
            if (owner == processId) PostMessage(window, 0x0010, IntPtr.Zero, IntPtr.Zero);
            return true;
        }, IntPtr.Zero);
    }
}
'@
    # An updating old window may still be warm. Close only a window whose
    # Python executable AND app argument belong to this exact clone/session.
    $app = Join-Path $repoRoot 'apps\plugin-station\app.py'
    $appPattern = '(?:^|\s)"?' + [regex]::Escape($app) + '(?:"|\s|$)'
    $session = (Get-Process -Id $PID).SessionId
    $ownedPython = @((Join-Path $runtime 'venv\Scripts\python.exe'),(Join-Path $runtime 'venv\Scripts\pythonw.exe'))
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    do {
        $windows = @(Get-CimInstance Win32_Process | Where-Object {
            $_.SessionId -eq $session -and $_.ExecutablePath -in $ownedPython -and
            $_.CommandLine -match $appPattern
        })
        foreach ($window in $windows) {
            [ToolboxUpgradeWindows]::CloseOwned([uint32]$window.ProcessId)
        }
        if (-not $windows.Count) { break }
        if ($form) { [Windows.Forms.Application]::DoEvents() }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($windows.Count) { throw 'Owned toolbox did not exit; nothing was migrated.' }
    foreach ($phase in 'Stage','Finalize') {
        $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' +
            (Join-Path $PSScriptRoot 'migrate-workspace-runtime.ps1') + '" -Phase ' + $phase +
            ' -BackupName ' + $state.backupName
        $process = Start-Process -FilePath $powershell -ArgumentList $arguments -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
        while (-not $process.HasExited) {
            if ($form) { [Windows.Forms.Application]::DoEvents() }
            Start-Sleep -Milliseconds 100
            $process.Refresh()
        }
        if ($process.ExitCode -ne 0) { throw ('Migration phase failed: ' + $phase) }
    }
    $resultPath = Join-Path $runtime ('migration-backups\' + $state.backupName + '\result.json')
    $result = [IO.File]::ReadAllText($resultPath) | ConvertFrom-Json
    if ($result.phase -ne 'complete' -or $result.oldRootsRemain -ne 0) { throw 'Migration completion did not verify.' }
    Save-State 'complete'
    if (-not $NoLaunch) {
        Start-Process -FilePath (Join-Path $env:WINDIR 'System32\wscript.exe') -ArgumentList ('"' + (Join-Path $repoRoot 'start-plugin-station.vbs') + '"') -WorkingDirectory $repoRoot -WindowStyle Hidden
    }
} catch {
    try { Save-State 'failed' } catch { }
    Show-Failure
    exit 1
} finally {
    if ($form) { $form.Dispose() }
    if ($taskFolder) {
        try {
            $task = $taskFolder.GetTask($taskName)
            if ($task.Definition.RegistrationInfo.Source -eq $source -and
                $task.Definition.Actions.Item(1).Path -eq $powershell -and
                $task.Definition.Actions.Item(1).Arguments -eq $workerArguments) {
                # Dispatcher leaves it for its worker; worker removes only itself.
                if (-not $Dispatch -or $state.state -eq 'failed') { $taskFolder.DeleteTask($taskName,0) }
            }
        } catch { }
    }
}
