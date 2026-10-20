# Run every portfolio query against aria_phase2 and save its output (query text + results)
# to expected_output\<file>.txt. Same connection settings as SQL_Scripts\run_all.ps1.
# Files run in order, so Q08-Q10 install the views, triggers and procedure later files use.
# Errors marked "EXPECTED ERROR" in the SQL are demonstrations; any other error fails the run.
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot
$psql = $env:PSQL
if (-not $psql) {
    $default = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
    if (Test-Path $default) { $psql = $default } else { $psql = 'psql' }
}
New-Item -ItemType Directory -Force expected_output | Out-Null

$expectedErrors = @{ 'Q09_triggers.sql' = 1; 'Q11_checkout_transaction.sql' = 2 }
$failed = $false
foreach ($file in Get-ChildItem Q*.sql | Sort-Object Name) {
    $out = Join-Path 'expected_output' ($file.BaseName + '.txt')
    & $psql -X -e -d aria_phase2 -f $file.Name 2>&1 | ForEach-Object { "$_" } | Set-Content -Encoding utf8 $out
    $errors = (Select-String -Path $out -Pattern 'ERROR:' | Measure-Object).Count
    $expected = 0
    if ($expectedErrors.ContainsKey($file.Name)) { $expected = $expectedErrors[$file.Name] }
    if ($errors -ne $expected) {
        Write-Host "FAIL $($file.Name): $errors errors (expected $expected), see $out"
        $failed = $true
    } else {
        Write-Host "ok   $($file.Name)"
    }
}
if ($failed) { exit 1 }
