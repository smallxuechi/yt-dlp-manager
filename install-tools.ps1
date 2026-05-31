# yt-dlp 和 FFmpeg 安装脚本
# 运行方式: .\install-tools.ps1

Write-Host "=== yt-dlp 安装工具 ===" -ForegroundColor Green
$toolsDir = $PSScriptRoot

# 下载 yt-dlp
Write-Host "`n[1/2] 正在下载 yt-dlp..." -ForegroundColor Yellow
$ytDlpUrl = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
$ytDlpPath = "$toolsDir\tools\yt-dlp.exe"

try {
    Invoke-WebRequest -Uri $ytDlpUrl -OutFile $ytDlpPath -UseBasicParsing
    Write-Host "yt-dlp 下载完成!" -ForegroundColor Green
} catch {
    Write-Host "yt-dlp 下载失败，请手动下载: $ytDlpUrl" -ForegroundColor Red
}

# 下载 FFmpeg
Write-Host "`n[2/2] 正在下载 FFmpeg..." -ForegroundColor Yellow
$ffmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip"
$ffmpegZipPath = "$toolsDir\tools\ffmpeg.zip"

try {
    Invoke-WebRequest -Uri $ffmpegUrl -OutFile $ffmpegZipPath -UseBasicParsing
    
    # 解压 FFmpeg
    Write-Host "正在解压 FFmpeg..." -ForegroundColor Yellow
    Expand-Archive -Path $ffmpegZipPath -DestinationPath "$toolsDir\tools" -Force
    
    # 移动文件
    $ffmpegExtractedDir = Get-ChildItem -Path "$toolsDir\tools" -Directory | Where-Object { $_.Name -like "ffmpeg*" }
    if ($ffmpegExtractedDir) {
        Copy-Item -Path "$($ffmpegExtractedDir.FullName)\bin\ffmpeg.exe" -Destination "$toolsDir\tools\" -Force
        Copy-Item -Path "$($ffmpegExtractedDir.FullName)\bin\ffprobe.exe" -Destination "$toolsDir\tools\" -Force
        Remove-Item -Path $ffmpegZipPath -Force
        Remove-Item -Path $ffmpegExtractedDir.FullName -Recurse -Force
    }
    Write-Host "FFmpeg 安装完成!" -ForegroundColor Green
} catch {
    Write-Host "FFmpeg 下载/解压失败，请手动下载: $ffmpegUrl" -ForegroundColor Red
    Write-Host "下载后解压，将 ffmpeg.exe 和 ffprobe.exe 放到 tools 目录" -ForegroundColor Yellow
}

Write-Host "`n=== 安装完成 ===" -ForegroundColor Green
Write-Host "请确保 tools 目录有: yt-dlp.exe, ffmpeg.exe, ffprobe.exe" -ForegroundColor Cyan

# 验证
Write-Host "`n验证安装:" -ForegroundColor Yellow
if (Test-Path "$toolsDir\tools\yt-dlp.exe") {
    & "$toolsDir\tools\yt-dlp.exe" --version
}
if (Test-Path "$toolsDir\tools\ffmpeg.exe") {
    & "$toolsDir\tools\ffmpeg.exe" -version
}

Write-Host "`n运行启动命令: python server.py" -ForegroundColor Cyan