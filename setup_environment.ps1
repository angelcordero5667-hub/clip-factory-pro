# Clip Factory Pro - Script de Instalación Automatizada para Windows 11
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Clip Factory Pro - Instalador de Dependencias Base " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$baseDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$toolsDir = Join-Path $baseDir "tools"
New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null

# 1. Comprobar o Descargar Python 3.11
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "[1/3] Descargando instalador oficial de Python 3.11.9..." -ForegroundColor Yellow
    $pyInstaller = Join-Path $toolsDir "python-3.11.9-amd64.exe"
    if (-not (Test-Path $pyInstaller)) {
        curl.exe -L "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -o $pyInstaller
    }
    Write-Host "Instalando Python 3.11 (con PATH activado)..." -ForegroundColor Green
    Start-Process -FilePath $pyInstaller -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0" -Wait
    Write-Host "Python 3.11 instalado." -ForegroundColor Green
} else {
    Write-Host "[1/3] Python ya está disponible en el sistema." -ForegroundColor Green
}

# 2. Comprobar o Descargar FFmpeg
$ffmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpegCmd) {
    Write-Host "[2/3] Descargando paquete portátil de FFmpeg..." -ForegroundColor Yellow
    $ffmpegZip = Join-Path $toolsDir "ffmpeg.zip"
    $ffmpegExtract = Join-Path $toolsDir "ffmpeg"
    if (-not (Test-Path $ffmpegZip)) {
        curl.exe -L "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -o $ffmpegZip
    }
    if (-not (Test-Path $ffmpegExtract)) {
        Write-Host "Descomprimiendo FFmpeg..." -ForegroundColor Yellow
        tar.exe -xf $ffmpegZip -C $toolsDir
        Get-ChildItem $toolsDir -Directory -Filter "ffmpeg-*-essentials_build" | Rename-Item -NewName "ffmpeg"
    }
    Write-Host "FFmpeg listo en: $ffmpegExtract\bin" -ForegroundColor Green
} else {
    Write-Host "[2/3] FFmpeg ya está disponible en el sistema." -ForegroundColor Green
}

# 3. Comprobar Ollama
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaCmd) {
    Write-Host "[3/3] Descargando instalador de Ollama para Windows..." -ForegroundColor Yellow
    $ollamaInstaller = Join-Path $toolsDir "OllamaSetup.exe"
    if (-not (Test-Path $ollamaInstaller)) {
        curl.exe -L "https://ollama.com/download/OllamaSetup.exe" -o $ollamaInstaller
    }
    Write-Host "Instalando Ollama..." -ForegroundColor Green
    Start-Process -FilePath $ollamaInstaller -ArgumentList "/silent" -Wait
} else {
    Write-Host "[3/3] Ollama ya está disponible." -ForegroundColor Green
}

Write-Host "`nEntorno configurado correctamente." -ForegroundColor Cyan
