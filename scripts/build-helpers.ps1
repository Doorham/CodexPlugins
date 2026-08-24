$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$output = Join-Path $repoRoot 'artifacts\helpers'
$csc = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $csc)) { throw "C# compiler not found: $csc" }
New-Item -ItemType Directory -Path $output -Force | Out-Null

$clipboardSource = Join-Path $repoRoot 'helpers\updream-clipboard-cleaner\src\Program.cs'
$chimeSource = Join-Path $repoRoot 'helpers\codex-answer-chime\src\Program.cs'
$arctisGateSource = Join-Path $repoRoot 'helpers\arctis-nova-5-startup-gate\src\Program.cs'
$arctisMonitorSource = Join-Path $repoRoot 'helpers\arctis-nova-5-battery-monitor\src\Program.cs'
$environmentDetectorSource = Join-Path $repoRoot 'helpers\environment-detector\src\Program.cs'
$testSource = Join-Path $repoRoot 'tests\clipboard-verification\Program.cs'

& $csc /nologo /optimize+ /target:winexe /platform:anycpu "/out:$output\UpdreamClipboardCleaner.exe" /reference:System.dll /reference:System.Core.dll /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll $clipboardSource
if ($LASTEXITCODE -ne 0) { throw 'Updream Clipboard Cleaner build failed.' }

& $csc /nologo /optimize+ /target:winexe /platform:anycpu "/out:$output\CodexAnswerChime.exe" /reference:System.dll /reference:System.Core.dll /reference:System.Web.Extensions.dll $chimeSource
if ($LASTEXITCODE -ne 0) { throw 'Codex Answer Chime build failed.' }

& $csc /nologo /optimize+ /target:winexe /platform:anycpu "/out:$output\ArctisNova5StartupGate.exe" /reference:System.dll /reference:System.Core.dll $arctisGateSource
if ($LASTEXITCODE -ne 0) { throw 'Arctis Nova 5 startup gate build failed.' }

& $csc /nologo /optimize+ /target:winexe /platform:anycpu "/out:$output\ArctisNova5BatteryMonitor.exe" /reference:System.dll /reference:System.Core.dll /reference:System.Windows.Forms.dll /reference:System.Drawing.dll $arctisMonitorSource
if ($LASTEXITCODE -ne 0) { throw 'Arctis Nova 5 battery monitor build failed.' }

& $csc /nologo /optimize+ /target:exe /platform:anycpu "/out:$output\ClipboardVerification.exe" /reference:System.dll /reference:System.Core.dll $testSource
if ($LASTEXITCODE -ne 0) { throw 'Clipboard verification build failed.' }

& $csc /nologo /optimize+ /target:winexe /platform:anycpu "/out:$output\EnvironmentDetector.exe" /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll $environmentDetectorSource
if ($LASTEXITCODE -ne 0) { throw 'Environment Detector build failed.' }

Get-ChildItem -LiteralPath $output -Filter '*.exe' | Select-Object FullName, Length, LastWriteTime
