# fetch_deps_windows.ps1 - Collect tesseract + poppler binaries
# for bundling into a PyInstaller build on Windows.
#
# Prerequisites:
#   - Tesseract installed and on PATH (e.g. choco install tesseract, or UB-Mannheim installer)
#   - Internet access (poppler is downloaded from GitHub)
#
# Usage:
#   cd backend
#   powershell -ExecutionPolicy Bypass -File scripts\fetch_deps_windows.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Split-Path -Parent $ScriptDir
$VendorDir = Join-Path $BackendDir "vendor\windows"

# Poppler release to download
$PopplerVersion = "24.08.0-0"
$PopplerUrl = "https://github.com/oschwartz10612/poppler-windows/releases/download/v$PopplerVersion/Release-$PopplerVersion.zip"

Write-Host "==> Collecting Windows vendor dependencies into $VendorDir"

# Clean previous output
if (Test-Path $VendorDir) {
    Remove-Item -Recurse -Force $VendorDir
}

New-Item -ItemType Directory -Force -Path "$VendorDir\tesseract\tessdata" | Out-Null
New-Item -ItemType Directory -Force -Path "$VendorDir\poppler" | Out-Null

# --- Tesseract ---
$TesseractExe = Get-Command tesseract -ErrorAction SilentlyContinue
if (-not $TesseractExe) {
    Write-Error "tesseract not found on PATH. Install via: choco install tesseract"
    exit 1
}

$TesseractPath = $TesseractExe.Source
$TesseractDir = Split-Path -Parent $TesseractPath

Write-Host "==> Collecting tesseract from $TesseractDir"

# Copy tesseract.exe and DLLs from its directory
Copy-Item "$TesseractPath" "$VendorDir\tesseract\" -Force
Write-Host "    Copied tesseract.exe"

Get-ChildItem "$TesseractDir\*.dll" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName "$VendorDir\tesseract\" -Force
    Write-Host "    DLL: $($_.Name)"
}

# Copy tessdata
$TessdataSource = $null
$PossibleTessdata = @(
    (Join-Path $TesseractDir "tessdata"),
    (Join-Path (Split-Path -Parent $TesseractDir) "tessdata"),
    (Join-Path $TesseractDir "..\share\tessdata")
)

foreach ($path in $PossibleTessdata) {
    if (Test-Path $path) {
        $TessdataSource = (Resolve-Path $path).Path
        break
    }
}

if (-not $TessdataSource) {
    if ($env:TESSDATA_PREFIX -and (Test-Path $env:TESSDATA_PREFIX)) {
        $TessdataSource = $env:TESSDATA_PREFIX
    }
}

if (-not $TessdataSource) {
    Write-Error "Could not locate tessdata directory."
    exit 1
}

Write-Host "==> Copying tessdata from $TessdataSource"
foreach ($lang in @("eng", "fra")) {
    $src = Join-Path $TessdataSource "$lang.traineddata"
    if (Test-Path $src) {
        Copy-Item $src "$VendorDir\tesseract\tessdata\" -Force
        Write-Host "    Language: $lang"
    } else {
        Write-Warning "$lang.traineddata not found at $src"
    }
}

$osdFile = Join-Path $TessdataSource "osd.traineddata"
if (Test-Path $osdFile) {
    Copy-Item $osdFile "$VendorDir\tesseract\tessdata\" -Force
}

# --- Poppler (download pre-built) ---
Write-Host "==> Downloading poppler $PopplerVersion from GitHub"

$TempZip = Join-Path $env:TEMP "poppler-windows.zip"
$TempExtract = Join-Path $env:TEMP "poppler-extract"

try {
    Invoke-WebRequest -Uri $PopplerUrl -OutFile $TempZip -UseBasicParsing
    Write-Host "    Downloaded successfully"
} catch {
    Write-Error "Failed to download poppler from $PopplerUrl : $_"
    exit 1
}

# Extract
if (Test-Path $TempExtract) {
    Remove-Item -Recurse -Force $TempExtract
}
Expand-Archive -Path $TempZip -DestinationPath $TempExtract -Force

# Find the bin directory inside the extracted archive
$PopplerBinDir = Get-ChildItem -Path $TempExtract -Recurse -Directory -Filter "bin" | Select-Object -First 1

if (-not $PopplerBinDir) {
    Write-Error "Could not find bin directory in poppler archive"
    exit 1
}

Write-Host "==> Copying poppler binaries from $($PopplerBinDir.FullName)"

# Copy required executables and all DLLs
foreach ($exe in @("pdftoppm.exe", "pdfinfo.exe")) {
    $src = Join-Path $PopplerBinDir.FullName $exe
    if (Test-Path $src) {
        Copy-Item $src "$VendorDir\poppler\" -Force
        Write-Host "    Copied $exe"
    } else {
        Write-Warning "$exe not found in poppler archive"
    }
}

Get-ChildItem (Join-Path $PopplerBinDir.FullName "*.dll") -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName "$VendorDir\poppler\" -Force
    Write-Host "    DLL: $($_.Name)"
}

# Cleanup temp files
Remove-Item -Force $TempZip -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $TempExtract -ErrorAction SilentlyContinue

# --- Summary ---
$TesseractCount = (Get-ChildItem "$VendorDir\tesseract" -Recurse -File).Count
$PopplerCount = (Get-ChildItem "$VendorDir\poppler" -Recurse -File).Count

Write-Host ""
Write-Host "==> Done! Vendor files collected in $VendorDir"
Write-Host "    Tesseract files: $TesseractCount"
Write-Host "    Poppler files:   $PopplerCount"
Write-Host ""
Write-Host "Next step: cd backend && pyinstaller invoice_processor.spec"
