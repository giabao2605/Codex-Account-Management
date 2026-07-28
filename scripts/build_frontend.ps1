$ErrorActionPreference = "Stop"

$scriptsDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDirectory = Split-Path -Parent $scriptsDirectory
$frontendDirectory = Join-Path $projectDirectory "frontend"
$distributionDirectory = Join-Path $projectDirectory "web-dist"
$assetsDirectory = Join-Path $distributionDirectory "assets"
$indexPath = Join-Path $distributionDirectory "index.html"

Get-Command npm -ErrorAction Stop | Out-Null

Push-Location $frontendDirectory
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) {
        throw "npm ci failed with exit code $LASTEXITCODE."
    }

    & npm run build
    if ($LASTEXITCODE -ne 0) {
        throw "npm run build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $indexPath -PathType Leaf)) {
    throw "The production frontend build is missing web-dist/index.html."
}
if (-not (Test-Path -LiteralPath $assetsDirectory -PathType Container)) {
    throw "The production frontend build is missing web-dist/assets."
}

$sourceMaps = @(
    Get-ChildItem -LiteralPath $distributionDirectory -Recurse -Filter *.map
)
if ($sourceMaps.Count -gt 0) {
    throw "Production source maps must not be shipped in web-dist."
}

Write-Host "Production frontend build completed in web-dist."
