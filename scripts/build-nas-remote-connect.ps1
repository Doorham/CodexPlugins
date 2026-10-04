[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$output = Join-Path $repoRoot 'artifacts\nas-remote-connect'
New-Item -ItemType Directory -Force -Path $output | Out-Null
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$source = Join-Path $repoRoot 'helpers\nas-remote-connect\src\Program.cs'
& $csc /nologo /optimize+ /target:winexe "/out:$output\NasRemoteConnect.exe" /reference:System.dll /reference:System.Core.dll /reference:System.Security.dll /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll $source
if ($LASTEXITCODE -ne 0) { throw 'NAS connector compilation failed.' }
# No company configuration or Tailscale installer is included in this public build.
Get-Item -LiteralPath (Join-Path $output 'NasRemoteConnect.exe')
