# VRC-VideoTools Build Script
# Go 1.26 + .NET 9 WPF Custom Studio UI

if (Test-Path "$PSScriptRoot\assets\app.ico") {
    Copy-Item "$PSScriptRoot\assets\*" "$PSScriptRoot\wpf-app\Assets\" -Force
    Copy-Item "$PSScriptRoot\assets\*" "$PSScriptRoot\installer\Assets\" -Force
}

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host " [1/5] Building Go Core Stream Engine..." -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Cyan

Set-Location -Path "$PSScriptRoot\go-core"
$env:CGO_ENABLED = "0"
go build -ldflags "-s -w" -o vrc-video-core.exe .
if ($LASTEXITCODE -ne 0) {
    Write-Error "Go core build failed!"
    exit $LASTEXITCODE
}
Write-Host "Go core build success: go-core\vrc-video-core.exe" -ForegroundColor Green

Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host " [2/5] Publishing .NET 9 WPF App..." -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Cyan

Set-Location -Path $PSScriptRoot
if (Test-Path "$PSScriptRoot\dist\app") {
    Remove-Item -Recurse -Force "$PSScriptRoot\dist\app"
}
dotnet publish wpf-app -c Release -r win-x64 --self-contained false -o "$PSScriptRoot\dist\app"
if ($LASTEXITCODE -ne 0) {
    Write-Error "WPF App publish failed!"
    exit $LASTEXITCODE
}

Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host " [3/5] Packaging payload.zip..." -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Cyan

Copy-Item "$PSScriptRoot\go-core\vrc-video-core.exe" "$PSScriptRoot\dist\app\" -Force

if (-not (Test-Path "$PSScriptRoot\installer\Resources")) {
    New-Item -ItemType Directory -Force "$PSScriptRoot\installer\Resources" | Out-Null
}

if (Test-Path "$PSScriptRoot\installer\Resources\payload.zip") {
    Remove-Item -Force "$PSScriptRoot\installer\Resources\payload.zip"
}
Compress-Archive -Path "$PSScriptRoot\dist\app\*" -DestinationPath "$PSScriptRoot\installer\Resources\payload.zip" -Force
Write-Host "Payload packaged: installer\Resources\payload.zip" -ForegroundColor Green

Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host " [4/5] Publishing Interactive Installer (Setup.exe)..." -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Cyan

if (Test-Path "$PSScriptRoot\dist\installer") {
    Remove-Item -Recurse -Force "$PSScriptRoot\dist\installer"
}
dotnet publish installer -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o "$PSScriptRoot\dist\installer"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Installer publish failed!"
    exit $LASTEXITCODE
}

Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host " [5/5] Finalizing Distribution..." -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Cyan

Copy-Item "$PSScriptRoot\dist\installer\VRC-VideoTools-Setup.exe" "$PSScriptRoot\VRC-VideoTools-Setup.exe" -Force
$setupItem = Get-Item "$PSScriptRoot\VRC-VideoTools-Setup.exe"
$sizeMB = [Math]::Round($setupItem.Length / 1MB, 2)

if ($env:VRCVT_SYNC_DIR -and (Test-Path $env:VRCVT_SYNC_DIR)) {
    Copy-Item "$PSScriptRoot\dist\app\*" "$env:VRCVT_SYNC_DIR\" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  -> Synced to $env:VRCVT_SYNC_DIR\" -ForegroundColor Yellow
}
$installedDir = "$env:LOCALAPPDATA\Programs\VRC-VideoTools"
if (Test-Path $installedDir) {
    Copy-Item "$PSScriptRoot\dist\app\*" "$installedDir\" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  -> Synced to $installedDir\" -ForegroundColor Yellow
}

Write-Host "SUCCESS: Package generated!" -ForegroundColor Green
Write-Host "  -> Installer: $PSScriptRoot\VRC-VideoTools-Setup.exe ($sizeMB MB)" -ForegroundColor Yellow
Write-Host "  -> Portable App: $PSScriptRoot\dist\app\" -ForegroundColor Yellow
