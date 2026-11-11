#Requires -Version 5.1
<#
    Builds the SDN firewall image and runs the end-to-end demo.
    Requires Docker Desktop with the Linux engine running.
#>
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker was not found on PATH." -ForegroundColor Red
    Write-Host "Install Docker Desktop (https://www.docker.com/products/docker-desktop/) and run this script again."
    exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is installed but the engine is not responding." -ForegroundColor Red
    Write-Host "Start Docker Desktop, wait for it to say 'Engine running', then retry."
    exit 1
}

Write-Host "Building image 'sdn-firewall'..." -ForegroundColor Cyan
docker build -t sdn-firewall .
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }

Write-Host ""
Write-Host "Running the firewall demo..." -ForegroundColor Cyan
docker run --rm -it --privileged sdn-firewall /app/demo.sh
exit $LASTEXITCODE
