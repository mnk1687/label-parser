$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not $env:LABELDESK_TESSERACT) { $env:LABELDESK_TESSERACT = 'C:\Program Files\Tesseract-OCR' }
$env:LABELDESK_TESSDATA = Join-Path $env:LABELDESK_TESSERACT 'tessdata'
if (-not (Test-Path "$env:LABELDESK_TESSERACT\tesseract.exe")) { throw 'Build machine needs Tesseract. End users do not.' }
python -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
python packaging/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
$licenseDir = 'packaging/licenses/tesseract-windows'
New-Item -ItemType Directory -Force $licenseDir | Out-Null
Get-ChildItem $env:LABELDESK_TESSERACT -Recurse -File | Where-Object { $_.Name -match 'LICENSE|COPYING|NOTICE' } | ForEach-Object { Copy-Item $_.FullName (Join-Path $licenseDir ($_.FullName.Substring($env:LABELDESK_TESSERACT.Length).Replace('\','_'))) }
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python -m PyInstaller --noconfirm --clean packaging/LabelDesk.spec
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
# Verify the installed executable, including OCR and GUI resources, before packaging.
$smoke = Join-Path $env:TEMP ('LabelDesk-smoke-' + [guid]::NewGuid())
$p = Start-Process -FilePath 'dist/LabelDesk/LabelDesk.exe' -ArgumentList @('--self-test', ('"' + $smoke + '"')) -Wait -PassThru
if ($p.ExitCode -ne 0 -or -not (Test-Path "$smoke/PASS.txt")) { throw "Frozen smoke test failed. See $smoke" }
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { throw 'Build machine needs Inno Setup 6.' }
& $iscc packaging/windows.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
Compress-Archive -Path dist/LabelDesk -DestinationPath dist/LabelDesk-0.5.0-Windows-x64-Portable.zip -Force
