# Rebuild aria_phase2 from scratch: database, tables, indexes, seed data, portfolio objects.
# Usage (Windows PowerShell):
#   $env:PGHOST = '127.0.0.1'; $env:PGUSER = 'postgres'
#   $env:PGPASSWORD = '...'      # or use %APPDATA%\postgresql\pgpass.conf; never commit it
#   .\run_all.ps1
# Set $env:PSQL if psql is not on PATH (default: PostgreSQL 18's install folder).
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$psql = $env:PSQL
if (-not $psql) {
    $default = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
    if (Test-Path $default) { $psql = $default } else { $psql = 'psql' }
}

function Invoke-Psql([string]$Database, [string]$File) {
    Write-Host "== $File"
    & $psql -X -q -v ON_ERROR_STOP=1 -d $Database -f $File
    if ($LASTEXITCODE -ne 0) { throw "psql failed on $File" }
}

Invoke-Psql 'postgres' '00_create_database.sql'
foreach ($f in '01_tables.sql', '02_indexes.sql', '03_seed.sql', '04_verify_seed.sql') {
    Invoke-Psql 'aria_phase2' $f
}
Invoke-Psql 'aria_phase2' '..\Query_Portfolio\00_portfolio_objects.sql'
Write-Host 'aria_phase2 is ready.'
