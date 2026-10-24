param([string]$Python = 'python', [switch]$UseExistingEnvironment)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$buildRoot = Join-Path $repoRoot '.build-journal'
$skillRoot = Join-Path $repoRoot '.agents\skills\ai-dev-journal'
$buildPython = Join-Path $buildRoot 'venv\Scripts\python.exe'
if (-not $UseExistingEnvironment) {
    & $Python -m venv (Join-Path $buildRoot 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Build venv creation failed' }
    & $buildPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Build dependency install failed' }
}
& $buildPython -m PyInstaller --noconfirm --clean --onedir --name journal --distpath (Join-Path $buildRoot 'dist') --workpath (Join-Path $buildRoot 'work') --specpath $buildRoot (Join-Path $skillRoot 'scripts\journal.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
$staged = Join-Path $buildRoot 'dist\journal'
$destination = Join-Path $skillRoot 'bin\windows-x64'
$doctor = & (Join-Path $staged 'journal.exe') doctor | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $doctor.ready -or -not $doctor.bundled) { throw 'Staged runtime self-test failed' }
# Keep the third-party license notices with every rebuilt distribution.
Copy-Item -LiteralPath (Join-Path $destination 'licenses') -Destination (Join-Path $staged 'licenses') -Recurse -Force
$pythonLicense = & $buildPython -c 'from pathlib import Path; import sys; print(next((str(Path(sys.base_prefix) / name) for name in ("LICENSE_PYTHON.txt", "LICENSE.txt") if (Path(sys.base_prefix) / name).is_file()), ""))'
if ($pythonLicense) { Copy-Item -LiteralPath $pythonLicense -Destination (Join-Path $staged 'licenses\Python-LICENSE.txt') -Force }
$dependencyInfo = & $buildPython -c 'import json, sys, cryptography, PyInstaller; print(json.dumps(dict(python=sys.version.split()[0], cryptography=cryptography.__version__, builder="PyInstaller " + PyInstaller.__version__ + " onedir")))' | ConvertFrom-Json
$info = [ordered]@{
    package_version = '2.0.0'
    platform = 'windows-x64'
    release_date = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'China Standard Time').ToString('yyyy-MM-dd')
    builder = $dependencyInfo.builder
    python = $dependencyInfo.python
    cryptography = $dependencyInfo.cryptography
    encrypted_format_version = 1
    source_sha256 = (Get-FileHash -LiteralPath (Join-Path $skillRoot 'scripts\journal.py') -Algorithm SHA256).Hash.ToLower()
    exe_sha256 = (Get-FileHash -LiteralPath (Join-Path $staged 'journal.exe') -Algorithm SHA256).Hash.ToLower()
}
[IO.File]::WriteAllText((Join-Path $staged 'BUILD-INFO.json'), (($info | ConvertTo-Json) -replace "`r`n", "`n") + "`n", [Text.UTF8Encoding]::new($false))
# Verify resolved targets before moving a recursive directory; keep the old bundle recoverable.
$resolvedDestination = (Resolve-Path -LiteralPath $destination).Path
$resolvedStaged = (Resolve-Path -LiteralPath $staged).Path
if ($resolvedDestination -ne (Join-Path $repoRoot '.agents\skills\ai-dev-journal\bin\windows-x64')) { throw 'Unexpected bundle destination' }
if (-not $resolvedStaged.StartsWith($buildRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Staging path escapes build workspace' }
$backup = Join-Path $buildRoot ('previous-bundle-' + [Guid]::NewGuid().ToString('N'))
if (-not [IO.Path]::GetFullPath($backup).StartsWith($buildRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Backup path escapes build workspace' }
Move-Item -LiteralPath $resolvedDestination -Destination $backup
try {
    Copy-Item -LiteralPath $resolvedStaged -Destination $destination -Recurse
} catch {
    throw "Bundle copy failed; previous bundle remains at $backup"
}
$info | ConvertTo-Json
