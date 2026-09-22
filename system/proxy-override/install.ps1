$ErrorActionPreference = 'Stop'

$domains = @(
  'updream.cn','updream.bilibili.com',
  'bilibili.com','bilivideo.com','hdslb.com','biliapi.net','biliapi.com','bilicdn1.com','biligame.com',
  'weixin.qq.com','wechat.com','servicewechat.com','wechatapp.com','weixinbridge.com','weixinstatic.com','qpic.cn','qlogo.cn','gtimg.com','finder.video.qq.com','wxapp.tc.qq.com','res.wx.qq.com','weixin110.qq.com','wechatpay.com','tenpay.com',
  'douyin.com','douyinstatic.com','douyinpic.com','douyinvod.com','douyincdn.com','byteimg.com','bytecdn.cn','bytecdn.com','bytedance.com','bytedanceapi.com','bytedns.com','bytedns1.com','bytetcc.com','bytegoofy.com','ibytedtos.com','pstatp.com','snssdk.com','toutiaoapi.com','zijieapi.com','amemv.com','bdurl.net','volces.com','volcengine.com','queniuso.com',
  'xiaoheihe.cn','max-c.com','maxjia.com','360.cn','360safe.com','360tpcdn.com','taobao.com','163.com',
  '126.com','126.net','127.net','yeah.net','bdstatic.com','bdimg.com','bcebos.com','b23.tv',
  'alicdn.com','tmall.com','tmall.hk','tmallglobal.com','mmstat.com','aliapp.org','alipay.com','tanx.com',
  'cf.aliyun.com','fourier.alibaba.com','tdum.alibaba.com',
  'battle.net','blizzard.com','battlenet.com.cn','blizzard.cn','blzstatic.com','blzstatic.cn','netease.com','blzddist1-a.akamaihd.net'
)

$requested = [System.Collections.Generic.List[string]]::new()
foreach ($domain in $domains) {
  $requested.Add($domain)
  $requested.Add("*.$domain")
}

$regPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$oldValue = (Get-ItemProperty -LiteralPath $regPath -Name ProxyOverride -ErrorAction SilentlyContinue).ProxyOverride
if ($null -eq $oldValue) { $oldValue = '' }
$existing = @($oldValue -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$merged = [System.Collections.Generic.List[string]]::new()
foreach ($item in $existing) { if ($seen.Add($item)) { $merged.Add($item) } }
$added = [System.Collections.Generic.List[string]]::new()
foreach ($item in $requested) {
  if ($seen.Add($item)) {
    $merged.Add($item)
    $added.Add($item)
  }
}
$newValue = $merged -join ';'

$recordDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CompanyAIHelpers\ProxyOverrideBypass'
New-Item -ItemType Directory -Path $recordDir -Force | Out-Null
$recordPath = Join-Path $recordDir 'install-record.json'
$backupPath = Join-Path $recordDir 'ProxyOverride.before.txt'
Set-Content -LiteralPath $backupPath -Value $oldValue -Encoding UTF8

Set-ItemProperty -LiteralPath $regPath -Name ProxyOverride -Type String -Value $newValue

Add-Type -Path (Join-Path $PSScriptRoot 'WinInetProxyBypass.cs')
[WinInetProxyBypass]::Apply($newValue)
$settingsChanged = $true
$refreshed = $true

$record = [ordered]@{
  InstalledAt = (Get-Date).ToString('o')
  RegistryPath = 'HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
  ValueName = 'ProxyOverride'
  PreviousValue = $oldValue
  AddedEntries = @($added)
  RequestedEntries = @($requested)
  InstalledValue = $newValue
  BackupPath = $backupPath
  WinInetSettingsChanged = $settingsChanged
  WinInetRefresh = $refreshed
}
$record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $recordPath -Encoding UTF8

$verify = (Get-ItemProperty -LiteralPath $regPath -Name ProxyOverride).ProxyOverride
$verifySet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
@($verify -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) | ForEach-Object { [void]$verifySet.Add($_) }
$missing = @($requested | Where-Object { -not $verifySet.Contains($_) })
[pscustomobject]@{
  RecordPath = $recordPath
  BackupPath = $backupPath
  PreviousCount = $existing.Count
  AddedCount = $added.Count
  FinalCount = $verifySet.Count
  Missing = $missing
  WinInetSettingsChanged = $settingsChanged
  WinInetRefresh = $refreshed
} | ConvertTo-Json -Compress
