[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$policyPath = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
New-Item -Path $policyPath -Force | Out-Null
New-ItemProperty -Path $policyPath -Name EnableLinkedConnections -PropertyType DWord -Value 1 -Force | Out-Null
$value = (Get-ItemProperty -LiteralPath $policyPath -Name EnableLinkedConnections).EnableLinkedConnections
if ([int]$value -ne 1) { throw 'EnableLinkedConnections verification failed.' }
