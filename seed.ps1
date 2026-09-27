<#
GEOPOD v2 - seed.ps1
Seeding lokal (Windows + Docker). Padanan seed_geojson.sh yang memakai podman.

Syarat: stack sudah jalan (docker compose -f podman-compose.yml up -d)
Cara pakai:
    .\seed.ps1

Env opsional:
    GEOPOD_NET         nama network docker compose (default: geopodv2_geopod)
    DATABASE_URL       koneksi DB dari dalam container (default ke hostname geodb)
    SEED_MATCH_PREFIX  filter kode, mis. 1673
    SEED_CODE_FIELD    kolom/properti kode bila bukan iddesa
    SEED_NAME_FIELD    kolom/properti nama bila tidak terdeteksi
#>
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $here

$NET = if ($env:GEOPOD_NET) { $env:GEOPOD_NET } else { 'geopodv2_geopod' }
$DB  = if ($env:DATABASE_URL) { $env:DATABASE_URL } else { 'postgres://geopod:geopod@geodb:5432/geopod_db' }
$IMG = 'geopod-seed:latest'

function Invoke-Docker {
    param([string[]]$Args2)
    & docker @Args2
    if ($LASTEXITCODE -ne 0) { throw "docker gagal (exit $LASTEXITCODE): $($Args2 -join ' ')" }
}

Write-Host "[geopod] build image seed..."
Invoke-Docker @('build', '-t', $IMG, '-f', (Join-Path $here 'deploy/seed/Dockerfile.seed'), (Join-Path $here 'deploy/seed'))

Write-Host "[geopod] seed geometri (GeoJSON/SHP) dari geojson_seed..."
Invoke-Docker @('run', '--rm', '--network', $NET, `
    '-e', "DATABASE_URL=$DB", `
    '-e', "SEED_CODE_FIELD=$env:SEED_CODE_FIELD", `
    '-e', "SEED_NAME_FIELD=$env:SEED_NAME_FIELD", `
    '-e', "SEED_MATCH_PREFIX=$env:SEED_MATCH_PREFIX", `
    '-v', "$here\geojson_seed:/data:ro", `
    $IMG, '/app/seed_geojson.py', '--src', '/data')

$xlsx = Get-ChildItem (Join-Path $here 'podes_seed') -Filter *.xlsx -ErrorAction SilentlyContinue
if ($xlsx.Count -gt 0) {
    foreach ($f in $xlsx) {
        Write-Host "[geopod] import atribut Podes: $($f.Name)"
        Invoke-Docker @('run', '--rm', '--network', $NET, `
            '-e', "DATABASE_URL=$DB", `
            '-v', "$($f.FullName):/data/input.xlsx:ro", `
            $IMG, '/app/import_podes_xlsx.py', '--src', '/data/input.xlsx')
    }
} else {
    Write-Host "[geopod] tidak ada file .xlsx di podes_seed -> impor atribut dilewati."
}

Write-Host "[geopod] seeding selesai."