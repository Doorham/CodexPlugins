[CmdletBinding()]
param([switch]$AllowMissingSdk)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$project = Join-Path $repoRoot 'helpers\updream-bridge\src\UpdreamBridgeConfig.csproj'
$artifactRoot = Join-Path $repoRoot 'artifacts\updream-bridge'
$publishRoot = Join-Path $artifactRoot 'app'
$helperRoot = Join-Path $repoRoot 'artifacts\helpers'
$env:DOTNET_CLI_HOME = Join-Path $repoRoot '.runtime\dotnet'
$env:NUGET_PACKAGES = Join-Path $repoRoot '.runtime\nuget-packages'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$dotnet = $null
$dotnetCandidates = @()
if ($env:ProgramW6432) { $dotnetCandidates += Join-Path $env:ProgramW6432 'dotnet\dotnet.exe' }
$dotnetCandidates += @(Get-Command dotnet.exe -CommandType Application -All -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
foreach ($candidate in $dotnetCandidates | Select-Object -Unique) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    $candidateSdks = @(& $candidate --list-sdks)
    if ($LASTEXITCODE -eq 0 -and @($candidateSdks | Where-Object { $_ -match '^(?:[8-9]|[1-9][0-9])\.' }).Count) { $dotnet = $candidate; break }
}
if (-not $dotnet) {
    if ($AllowMissingSdk) { Write-Warning 'UpdreamBridge 未构建：缺少 .NET SDK；请在 Codex 环境补全中检测并安装 SDK。'; return }
    throw 'UpdreamBridge 构建需要 .NET SDK 8 或更高版本。'
}
$sdks = @(& $dotnet --list-sdks)
if ($LASTEXITCODE -ne 0 -or -not @($sdks | Where-Object { $_ -match '^(?:[8-9]|[1-9][0-9])\.' }).Count) {
    if ($AllowMissingSdk) { Write-Warning 'UpdreamBridge 未构建：缺少 .NET SDK 8+。'; return }
    throw 'UpdreamBridge 构建需要 .NET SDK 8 或更高版本。'
}
New-Item -ItemType Directory -Force -Path $publishRoot, $helperRoot | Out-Null
$objPath = ($artifactRoot -replace '\\', '/') + '/obj/'
$binPath = ($artifactRoot -replace '\\', '/') + '/bin/'
& $dotnet publish $project -c Release -r win-x64 --self-contained false -o $publishRoot '-p:PublishSingleFile=true' '-p:IncludeNativeLibrariesForSelfExtract=true' "-p:BaseIntermediateOutputPath=$objPath" "-p:BaseOutputPath=$binPath" -v:q
if ($LASTEXITCODE -ne 0) { throw 'UpdreamBridge 构建失败。' }
$builtExe = Join-Path $publishRoot 'UpdreamBridgeConfig.exe'
if (-not (Test-Path -LiteralPath $builtExe -PathType Leaf)) { throw 'UpdreamBridge 未生成 EXE。' }
Copy-Item -LiteralPath $builtExe -Destination (Join-Path $helperRoot 'UpdreamBridgeConfig.exe') -Force
Get-Item -LiteralPath (Join-Path $helperRoot 'UpdreamBridgeConfig.exe') | Select-Object FullName,Length
