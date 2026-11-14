# ResQLens - automated verification. Writes logs\verification_report.txt.
# Runs: database check, backend tests (SQLite + MySQL test DB), frontend build + type-check,
# and a live API smoke test on a temporary port. Never prints passwords or .env values.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$report = Join-Path $logDir 'verification_report.txt'
$lines = New-Object System.Collections.Generic.List[string]
$results = New-Object System.Collections.Generic.List[string]
function Add([string]$s) { $lines.Add($s); Write-Host $s }
function Result([string]$name, [bool]$ok, [string]$detail) {
    $mark = if ($ok) { 'PASS' } else { 'FAIL' }
    $results.Add(("[{0}] {1} - {2}" -f $mark, $name, $detail)); Add ("[{0}] {1} - {2}" -f $mark, $name, $detail)
}
function Exec([string]$label, [string]$workdir, [string]$exe, [string[]]$argv) {
    Add ''; Add "== $label =="
    Push-Location $workdir
    $out = & $exe @argv 2>&1 | Out-String
    $code = $LASTEXITCODE
    Pop-Location
    $tail = ($out -split "`r?`n" | Where-Object { $_ -ne '' } | Select-Object -Last 40) -join "`n"
    Add $tail
    return @{ code = $code; out = $out }
}

Add "ResQLens verification - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$py = Join-Path $root 'backend\venv\Scripts\python.exe'
if (-not (Test-Path $py)) { Add 'backend\venv missing - run setup.bat first'; $lines | Set-Content -Encoding UTF8 $report; exit 1 }
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$envFile = Join-Path $root '.env'
$engine = 'sqlite'
if (Test-Path $envFile) { $m = (Get-Content $envFile | Select-String '^DB_ENGINE=(.*)$'); if ($m) { $engine = $m.Matches.Groups[1].Value.Trim() } }
Add "DB_ENGINE=$engine"

# 1. versions inside the venv
$r = Exec 'Python packages' $backend $py @('-c', "import sys,starlette,pydantic,uvicorn,networkx,reportlab,pandas,jwt,pymysql; print(sys.version.split()[0], 'starlette', starlette.__version__, 'pydantic', pydantic.__version__, 'pymysql', pymysql.__version__)")
Result 'Backend dependencies import' ($r.code -eq 0) ($r.out.Trim() -split "`n" | Select-Object -Last 1)

# 2. database check
$r = Exec 'Database check' $backend $py @('-m', 'scripts.check_db')
Result 'Database connection (auth, schema, read, write, rollback)' ($r.code -eq 0) $(if ($r.code -eq 0) { "engine $engine" } else { 'see section above' })

# 3. backend tests on SQLite
$env:TEST_DB_ENGINE = 'sqlite'
$r = Exec 'Backend tests (SQLite)' $backend $py @('-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-W', 'ignore')
Result 'Backend tests on SQLite' ($r.code -eq 0) (($r.out -split "`r?`n" | Where-Object { $_ -match 'passed|failed|error' } | Select-Object -Last 1))

# 4. backend tests on MySQL (separate resqlens_test database)
if ($engine -eq 'mysql') {
    $env:TEST_DB_ENGINE = 'mysql'
    $r = Exec 'Backend tests (MySQL resqlens_test)' $backend $py @('-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-W', 'ignore')
    Result 'Backend tests on MySQL' ($r.code -eq 0) (($r.out -split "`r?`n" | Where-Object { $_ -match 'passed|failed|error' } | Select-Object -Last 1))
    $env:TEST_DB_ENGINE = 'sqlite'
}

# 5. frontend
$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if ($npm -and (Test-Path (Join-Path $frontend 'node_modules'))) {
    $r = Exec 'Frontend production build' $frontend $npm @('run', 'build')
    Result 'Frontend build' ($r.code -eq 0) $(if ($r.code -eq 0) { 'dist/ rebuilt' } else { 'see section above' })
    $r = Exec 'Frontend TypeScript type-check' $frontend $npm @('run', 'typecheck')
    $errs = ([regex]::Matches($r.out, 'error TS')).Count
    Result 'TypeScript type-check' ($r.code -eq 0) "$errs error(s)"
} else { Result 'Frontend' $false 'npm or frontend\node_modules missing - run setup.bat' }

# 6. live API smoke test on a temporary port (does not disturb a running instance on 8000)
Add ''; Add '== Live API smoke test (port 8765) =='
$proc = Start-Process -FilePath $py -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8765' -WorkingDirectory $backend -PassThru -WindowStyle Hidden -RedirectStandardError (Join-Path $logDir 'smoke_server.log')
$base = 'http://127.0.0.1:8765'
$up = $false
for ($i = 0; $i -lt 40; $i++) { try { $h = Invoke-RestMethod "$base/api/health" -TimeoutSec 2; $up = $true; break } catch { Start-Sleep -Milliseconds 750 } }
if ($up) {
    Result 'Backend starts + /api/health' $true "database $($h.database.engine) $($h.database.version), users=$($h.database.users)"
    try { $d = Invoke-WebRequest "$base/docs" -UseBasicParsing -TimeoutSec 5; Result '/docs (Swagger UI page)' ($d.StatusCode -eq 200) "HTTP $($d.StatusCode)" } catch { Result '/docs' $false "$_" }
    try { $o = Invoke-RestMethod "$base/openapi.json" -TimeoutSec 5; Result '/openapi.json' ($o.paths.PSObject.Properties.Count -gt 40) "$($o.paths.PSObject.Properties.Count) paths" } catch { Result '/openapi.json' $false "$_" }
    try {
        $login = Invoke-RestMethod "$base/api/auth/login" -Method Post -ContentType 'application/json' -Body '{"email":"demo@resqlens.dev","password":"Demo@2026"}' -TimeoutSec 10
        $hdr = @{ Authorization = "Bearer $($login.token)" }
        $projects = Invoke-RestMethod "$base/api/projects" -Headers $hdr -TimeoutSec 10
        Result 'Login + authorised API call' ($projects.Count -ge 1) "$($projects.Count) project(s) for the demo user"
        $ui = Invoke-WebRequest "$base/" -UseBasicParsing -TimeoutSec 5
        Result 'Built UI served by backend' ($ui.Content -match 'id="root"') "HTTP $($ui.StatusCode)"
    } catch { Result 'Login + API' $false "$_" }
} else {
    Result 'Backend starts + /api/health' $false 'did not answer within 30 s - see logs\smoke_server.log'
}
if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }

Add ''; Add '== SUMMARY =='
$results | ForEach-Object { Add $_ }
$failed = ($results | Where-Object { $_ -like '[[]FAIL*' }).Count
Add $(if ($failed -eq 0) { 'ALL CHECKS PASSED' } else { "$failed CHECK(S) FAILED" })
$lines | Set-Content -Encoding UTF8 $report
Write-Host ''
Write-Host "Report saved to $report"
