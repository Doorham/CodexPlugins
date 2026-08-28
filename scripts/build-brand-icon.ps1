[CmdletBinding()]
param(
    [string]$OutputPath,
    [string]$PreviewPath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $repoRoot 'assets\CodexTools.ico'
}

function New-RoundedPath {
    param(
        [float]$X,
        [float]$Y,
        [float]$Width,
        [float]$Height,
        [float]$Radius
    )

    $diameter = [Math]::Max(1.0, $Radius * 2.0)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc($X, $Y, $diameter, $diameter, 180, 90)
    $path.AddArc($X + $Width - $diameter, $Y, $diameter, $diameter, 270, 90)
    $path.AddArc($X + $Width - $diameter, $Y + $Height - $diameter, $diameter, $diameter, 0, 90)
    $path.AddArc($X, $Y + $Height - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    return $path
}

function New-BrandPng {
    param([int]$Size)

    $bitmap = New-Object System.Drawing.Bitmap($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit

        $shadowPath = New-RoundedPath ($Size * 0.07) ($Size * 0.085) ($Size * 0.86) ($Size * 0.86) ($Size * 0.21)
        $shadowBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(72, 0, 0, 0))
        $graphics.FillPath($shadowBrush, $shadowPath)

        $tilePath = New-RoundedPath ($Size * 0.045) ($Size * 0.04) ($Size * 0.88) ($Size * 0.88) ($Size * 0.22)
        $tileBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 241, 243, 245))
        $borderPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 211, 216, 222), [Math]::Max(1.0, $Size * 0.008))
        $graphics.FillPath($tileBrush, $tilePath)
        $graphics.DrawPath($borderPen, $tilePath)

        $font = New-Object System.Drawing.Font('Segoe UI', ($Size * 0.59), [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
        $textBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 12, 14, 18))
        $format = New-Object System.Drawing.StringFormat
        $format.Alignment = [System.Drawing.StringAlignment]::Center
        $format.LineAlignment = [System.Drawing.StringAlignment]::Center
        $textRect = New-Object System.Drawing.RectangleF(0, (-$Size * 0.025), ($Size * 0.97), ($Size * 0.96))
        $graphics.DrawString('C', $font, $textBrush, $textRect, $format)

        $stream = New-Object System.IO.MemoryStream
        $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        return $stream.ToArray()
    }
    finally {
        if ($format) { $format.Dispose() }
        if ($textBrush) { $textBrush.Dispose() }
        if ($font) { $font.Dispose() }
        if ($borderPen) { $borderPen.Dispose() }
        if ($tileBrush) { $tileBrush.Dispose() }
        if ($tilePath) { $tilePath.Dispose() }
        if ($shadowBrush) { $shadowBrush.Dispose() }
        if ($shadowPath) { $shadowPath.Dispose() }
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

$sizes = @(16, 24, 32, 48, 64, 128, 256)
$frames = New-Object 'System.Collections.Generic.List[byte[]]'
foreach ($size in $sizes) {
    $frameBytes = [byte[]](New-BrandPng -Size $size)
    $frames.Add($frameBytes)
}

$parent = Split-Path -Parent $OutputPath
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }

$file = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
$writer = New-Object System.IO.BinaryWriter($file)
try {
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$sizes.Count)

    $offset = 6 + (16 * $sizes.Count)
    for ($index = 0; $index -lt $sizes.Count; $index++) {
        $size = $sizes[$index]
        $frame = $frames[$index]
        $writer.Write([byte]$(if ($size -eq 256) { 0 } else { $size }))
        $writer.Write([byte]$(if ($size -eq 256) { 0 } else { $size }))
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([uint32]$frame.Length)
        $writer.Write([uint32]$offset)
        $offset += $frame.Length
    }

    foreach ($frame in $frames) {
        $writer.Write([byte[]]$frame)
    }
}
finally {
    $writer.Dispose()
    $file.Dispose()
}

if (-not [string]::IsNullOrWhiteSpace($PreviewPath)) {
    $previewParent = Split-Path -Parent $PreviewPath
    if ($previewParent) { New-Item -ItemType Directory -Force -Path $previewParent | Out-Null }
    [System.IO.File]::WriteAllBytes($PreviewPath, [byte[]]$frames[$frames.Count - 1])
}

[pscustomobject]@{
    Icon = $OutputPath
    Sizes = ($sizes -join ',')
    Bytes = (Get-Item -LiteralPath $OutputPath).Length
    Preview = $PreviewPath
}
