[CmdletBinding()]
param([switch]$AllowMissingSdk)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$project = Join-Path $repoRoot 'helpers\updream-bridge\src\UpdreamBridgeConfig.csproj'
$artifactRoot = Join-Path $repoRoot 'artifacts\updream-bridge'
$publishRoot = Join-Path $artifactRoot 'app'
$helperRoot = Join-Path $repoRoot 'artifacts\helpers'
$dotnet = Get-Command dotnet.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $dotnet) {
    if ($AllowMissingSdk) { Write-Warning 'UpdreamBridge 未构建：缺少 .NET SDK；请在软件安装检查中查看环境要求。'; return }
    throw 'UpdreamBridge 构建需要 .NET SDK 8 或更高版本。'
}
$sdks = @(& $dotnet.Source --list-sdks)
if ($LASTEXITCODE -ne 0 -or -not @($sdks | Where-Object { $_ -match '^(?:[8-9]|[1-9][0-9])\.' }).Count) {
    if ($AllowMissingSdk) { Write-Warning 'UpdreamBridge 未构建：缺少 .NET SDK 8+。'; return }
    throw 'UpdreamBridge 构建需要 .NET SDK 8 或更高版本。'
}
New-Item -ItemType Directory -Force -Path $publishRoot, $helperRoot | Out-Null
$objPath = ($artifactRoot -replace '\\', '/') + '/obj/'
$binPath = ($artifactRoot -replace '\\', '/') + '/bin/'
& $dotnet.Source publish $project -c Release -r win-x64 --self-contained false -o $publishRoot '-p:PublishSingleFile=true' '-p:IncludeNativeLibrariesForSelfExtract=true' "-p:BaseIntermediateOutputPath=$objPath" "-p:BaseOutputPath=$binPath" -v:q
if ($LASTEXITCODE -ne 0) { throw 'UpdreamBridge 构建失败。' }
$builtExe = Join-Path $publishRoot 'UpdreamBridgeConfig.exe'
if (-not (Test-Path -LiteralPath $builtExe -PathType Leaf)) { throw 'UpdreamBridge 未生成 EXE。' }
Copy-Item -LiteralPath $builtExe -Destination (Join-Path $helperRoot 'UpdreamBridgeConfig.exe') -Force
Get-Item -LiteralPath (Join-Path $helperRoot 'UpdreamBridgeConfig.exe') | Select-Object FullName,Length
