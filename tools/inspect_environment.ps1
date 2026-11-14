# ResQLens - environment inspection (read-only: installs nothing, changes nothing).
# Writes logs\environment_report.txt in the project folder. No passwords or .env contents are read.
$ErrorActionPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$report = Join-Path $logDir 'environment_report.txt'
$lines = New-Object System.Collections.Generic.List[string]
function Add([string]$s) { $lines.Add($s); Write-Host $s }
function Section([string]$s) { Add ''; Add "== $s ==" }
function Run([string]$exe, [string[]]$argv) {
    $cmd = Get-Command $exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cmd) { return $null }
    try { $out = & $cmd.Source @argv 2>&1 | Out-String } catch { $out = "error: $_" }
    return @{ path = $cmd.Source; out = $out.Trim() }
}

Add "ResQLens environment report - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

Section 'Operating system'
$os = Get-CimInstance Win32_OperatingSystem
Add "OS            : $($os.Caption) (version $($os.Version), build $($os.BuildNumber))"
Add "Architecture  : $($os.OSArchitecture) / $env:PROCESSOR_ARCHITECTURE"
Add ("Memory        : {0:N1} GB total, {1:N1} GB free" -f ($os.TotalVisibleMemorySize / 1MB), ($os.FreePhysicalMemory / 1MB))
Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | ForEach-Object {
    Add ("Disk {0}:       {1:N1} GB free of {2:N1} GB" -f $_.Name, ($_.Free / 1GB), (($_.Used + $_.Free) / 1GB))
}
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Add "Running as admin: $isAdmin (an admin account can still install via UAC prompts)"
Add "Local admin group member: $([bool](whoami /groups | Select-String 'S-1-5-32-544'))"
Add "PowerShell    : $($PSVersionTable.PSVersion)  | ExecutionPolicy (CurrentUser): $(Get-ExecutionPolicy -Scope CurrentUser)"

Section 'Python'
$py = Run 'python' @('--version')
if ($py) { Add "python        : $($py.out)  [$($py.path)]" } else { Add 'python        : NOT FOUND on PATH' }
if ($py -and $py.path -like '*WindowsApps*') { Add '  WARNING: this is the Microsoft Store alias, not a real install' }
$pyl = Run 'py' @('-0p')
if ($pyl) { Add "py launcher   :"; $pyl.out -split "`n" | ForEach-Object { Add "   $_" } } else { Add 'py launcher   : not found' }
$pip = Run 'pip' @('--version')
if ($pip) { Add "pip           : $($pip.out)" } else { Add 'pip           : NOT FOUND on PATH' }

Section 'Node.js / npm / Git / VS Code'
foreach ($t in @(@('node', '--version'), @('npm', '--version'), @('git', '--version'))) {
    $r = Run $t[0] @($t[1])
    if ($r) { Add ("{0,-14}: {1}  [{2}]" -f $t[0], ($r.out -split "`n")[0], $r.path) } else { Add ("{0,-14}: NOT FOUND on PATH" -f $t[0]) }
}
$gitName = Run 'git' @('config', '--global', 'user.name')
$gitMail = Run 'git' @('config', '--global', 'user.email')
if ($gitName) { Add "git user.name : $(if ($gitName.out) { 'set' } else { 'NOT set' })  | user.email: $(if ($gitMail.out) { 'set' } else { 'NOT set' })" }
$code = Run 'code' @('--version')
if ($code) { Add "VS Code       : $(($code.out -split "`n")[0])  [$($code.path)]" }
else {
    $codeExe = @("$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe", "$env:ProgramFiles\Microsoft VS Code\Code.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($codeExe) { Add "VS Code       : installed at $codeExe (the 'code' command is not on PATH)" } else { Add 'VS Code       : NOT FOUND' }
}
$ext = Run 'code' @('--list-extensions')
if ($ext) {
    $wanted = 'ms-python.python','ms-python.vscode-pylance','ms-python.debugpy','dbaeumer.vscode-eslint','esbenp.prettier-vscode','mtxr.sqltools','mtxr.sqltools-driver-mysql','eamodio.gitlens','humao.rest-client','dsznajder.es7-react-js-snippets'
    $have = $ext.out -split "`r?`n"
    Add "VS Code extensions installed (recommended ones):"
    foreach ($w in $wanted) { Add ("   [{0}] {1}" -f $(if ($have -contains $w) { 'x' } else { ' ' }), $w) }
}

Section 'MySQL'
$mysql = Run 'mysql' @('--version')
if ($mysql) { Add "mysql client  : $($mysql.out)  [$($mysql.path)]" } else { Add 'mysql client  : not on PATH' }
$mysqlDirs = Get-ChildItem 'C:\Program Files\MySQL', 'C:\Program Files (x86)\MySQL' -Directory -ErrorAction SilentlyContinue
if ($mysqlDirs) { $mysqlDirs | ForEach-Object { Add "installed     : $($_.FullName)" } } else { Add 'installed     : no folder under C:\Program Files\MySQL' }
Get-ChildItem 'C:\Program Files\MySQL\MySQL Server*\bin\mysqld.exe' -ErrorAction SilentlyContinue | ForEach-Object {
    $v = & $_.FullName --version 2>&1 | Out-String
    Add "server binary : $($v.Trim())"
}
$wb = Get-ChildItem 'C:\Program Files\MySQL\MySQL Workbench*\MySQLWorkbench.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
Add "Workbench     : $(if ($wb) { $wb.FullName } else { 'NOT FOUND' })"
$svc = Get-Service | Where-Object { $_.Name -like '*mysql*' -or $_.DisplayName -like '*mysql*' }
if ($svc) { $svc | ForEach-Object { Add "service       : $($_.Name) - $($_.Status) (start: $($_.StartType))" } } else { Add 'service       : no MySQL Windows service found' }
$xampp = Test-Path 'C:\xampp\mysql'
if ($xampp) { Add 'note          : XAMPP MySQL/MariaDB found at C:\xampp\mysql (may also use port 3306)' }

Section 'Ports'
foreach ($p in 3306, 8000, 5173) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue; Add "port $p      : IN USE by $($proc.ProcessName) (PID $($c.OwningProcess))" }
    else { Add "port $p      : free" }
}

Section 'Project state'
Add "project folder: $root"
foreach ($p in 'backend\venv\Scripts\python.exe', 'frontend\node_modules', '.env', '.vscode\settings.json', '.git', 'backend\resqlens.db') {
    Add ("{0,-28}: {1}" -f $p, $(if (Test-Path (Join-Path $root $p)) { 'present' } else { 'absent' }))
}
if (Test-Path (Join-Path $root '.env')) {
    $envText = Get-Content (Join-Path $root '.env')
    $engine = ($envText | Select-String '^DB_ENGINE=(.*)$').Matches.Groups[1].Value
    $pwSet = [bool]($envText | Select-String '^DB_PASSWORD=.+$')
    $keySet = [bool]($envText | Select-String '^SECRET_KEY=.+$')
    Add ".env          : DB_ENGINE=$engine, DB_PASSWORD $(if ($pwSet) { 'is set' } else { 'is EMPTY' }), SECRET_KEY $(if ($keySet) { 'is set' } else { 'is EMPTY' })  (values not shown)"
}

$lines | Set-Content -Encoding UTF8 $report
Write-Host ''
Write-Host "Report saved to $report"
