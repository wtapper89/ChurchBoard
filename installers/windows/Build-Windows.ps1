$ErrorActionPreference = "Stop"
$Project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Project

$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
& $Python -c "import sys; raise SystemExit(sys.version_info < (3, 11))"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.11 or newer is required to build ChurchBoard."
}

& $Python -m venv .build-venv
& .\.build-venv\Scripts\python.exe -m pip install --upgrade pip
& .\.build-venv\Scripts\pip.exe install -r requirements.txt -r build-requirements.txt
& .\.build-venv\Scripts\python.exe packaging\generate_brand_assets.py
& .\.build-venv\Scripts\python.exe packaging\collect_licenses.py
if (-not $env:CHURCHBOARD_PRODMESH_RTA_BUNDLE) {
    $ProdMeshCandidate = Join-Path $Project "build\prodmesh-rta"
    if (Test-Path (Join-Path $ProdMeshCandidate "ProdMeshRemoteRTA.exe")) {
        $env:CHURCHBOARD_PRODMESH_RTA_BUNDLE = $ProdMeshCandidate
    }
}
& .\.build-venv\Scripts\pyinstaller.exe packaging\ChurchBoard.spec --noconfirm --clean

$env:CHURCHBOARD_VERSION = & $Python -c "from app.version import __version__; print(__version__)"
$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) {
    $Iscc = "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path $Iscc)) {
    throw "Inno Setup 6 is required. Install it from https://jrsoftware.org/isdl.php"
}

& $Iscc installers\windows\ChurchBoard.iss
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed."
}

Write-Host "Built dist\ChurchBoard-$($env:CHURCHBOARD_VERSION)-Windows-x64-Setup.exe"
