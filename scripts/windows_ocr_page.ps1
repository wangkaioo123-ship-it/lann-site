param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq "AsTask" -and
        $_.IsGenericMethod -and
        $_.GetParameters().Count -eq 1
    } |
    Select-Object -First 1

function Await-WinRt {
    param(
        [Parameter(Mandatory = $true)]
        $Operation,
        [Parameter(Mandatory = $true)]
        [Type]$ResultType
    )
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $task = $asTask.Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

$resolvedPath = (Resolve-Path -LiteralPath $ImagePath).Path
$file = Await-WinRt (
    [Windows.Storage.StorageFile]::GetFileFromPathAsync($resolvedPath)
) ([Windows.Storage.StorageFile])
$stream = Await-WinRt (
    $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-WinRt (
    [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-WinRt (
    $decoder.GetSoftwareBitmapAsync()
) ([Windows.Graphics.Imaging.SoftwareBitmap])

$language = New-Object Windows.Globalization.Language -ArgumentList "zh-Hans-CN"
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
if ($null -eq $engine) {
    throw "Windows OCR zh-Hans-CN recognizer is unavailable"
}
$result = Await-WinRt (
    $engine.RecognizeAsync($bitmap)
) ([Windows.Media.Ocr.OcrResult])

$lines = foreach ($line in $result.Lines) {
    $words = foreach ($word in $line.Words) {
        [ordered]@{
            text = $word.Text
            x = [math]::Round($word.BoundingRect.X, 2)
            y = [math]::Round($word.BoundingRect.Y, 2)
            width = [math]::Round($word.BoundingRect.Width, 2)
            height = [math]::Round($word.BoundingRect.Height, 2)
        }
    }
    [ordered]@{
        text = $line.Text
        words = @($words)
    }
}

$json = [ordered]@{
    engine = "windows-media-ocr/zh-Hans-CN"
    text = $result.Text
    angle = $result.TextAngle
    lines = @($lines)
} | ConvertTo-Json -Depth 8 -Compress

if ($OutputPath) {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($OutputPath, $json, $utf8)
}
$json
