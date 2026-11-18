# Build the Phase 3 objects on top of aria_phase2 and run every Phase 3 query file.
# Prerequisite: Phase 2 is built (Phase2_Implementation\SQL_Scripts\run_all.ps1) and pgvector is
# installed on the server. Embedding CSVs must exist in ..\Embeddings\data (they are committed;
# regenerate with ..\Embeddings\run_pipeline.py).
#
# Usage (Windows PowerShell):
#   $env:PGHOST = '127.0.0.1'; $env:PGUSER = 'postgres'
#   $env:PGPASSWORD = Read-Host 'Postgres password'   # or %APPDATA%\postgresql\pgpass.conf; never commit it
#   .\run_all.ps1
# Set $env:PSQL if psql is not on PATH (default: PostgreSQL 18's install folder).
#
# Output of every file (statements + results) is saved to ..\Query_Results\<file>.txt.
# A1 and B1 contain deliberate rule violations marked "EXPECTED ERROR"; any other error fails.
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$psql = $env:PSQL
if (-not $psql) {
    $default = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
    if (Test-Path $default) { $psql = $default } else { $psql = 'psql' }
}
$out = Join-Path $PSScriptRoot '..\Query_Results'
New-Item -ItemType Directory -Force $out | Out-Null

foreach ($f in '00_prereqs.sql', '01_hierarchy_tables.sql', '02_product_seed.sql',
               '03_hierarchy_rules_and_ops.sql', '04_reviews.sql', '05_vectors.sql', '06_verify.sql') {
    Write-Host "== $f"
    $log = Join-Path $out ('setup_' + [IO.Path]::GetFileNameWithoutExtension($f) + '.txt')
    & $psql -X -e -v ON_ERROR_STOP=1 -d aria_phase2 -f $f 2>&1 | ForEach-Object { "$_" } | Set-Content -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL $f, see $log"
        Get-Content $log -Tail 5
        exit 1
    }
}

$expectedErrors = @{ 'A1_hierarchy_demo.sql' = 5; 'B1_jsonb_queries.sql' = 2 }
$failed = $false
foreach ($file in Get-ChildItem A1_*.sql, B1_*.sql, C?_*.sql, D1_*.sql | Sort-Object Name) {
    $log = Join-Path $out ($file.BaseName + '.txt')
    & $psql -X -e -d aria_phase2 -f $file.Name 2>&1 | ForEach-Object { "$_" } | Set-Content -Encoding utf8 $log
    $errors = (Select-String -Path $log -Pattern 'ERROR:' | Measure-Object).Count
    $expected = 0
    if ($expectedErrors.ContainsKey($file.Name)) { $expected = $expectedErrors[$file.Name] }
    if ($errors -ne $expected) {
        Write-Host "FAIL $($file.Name): $errors errors (expected $expected), see $log"
        $failed = $true
    } else {
        Write-Host "ok   $($file.Name)"
    }
}
if ($failed) { exit 1 }
