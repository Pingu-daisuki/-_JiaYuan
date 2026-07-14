param(
  [string]$PythonVersion = '3.13.14'
)

$ErrorActionPreference = 'Stop'
$desktopRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$projectRoot = (Resolve-Path (Join-Path $desktopRoot '..')).Path
$runtimeRoot = Join-Path $desktopRoot 'runtime'
$pythonRoot = Join-Path $runtimeRoot 'python'
$downloadRoot = Join-Path $runtimeRoot '.downloads'
$pythonArchive = Join-Path $downloadRoot "python-$PythonVersion-embed-amd64.zip"
$getPip = Join-Path $downloadRoot 'get-pip.py'
$pythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$getPipUrl = 'https://bootstrap.pypa.io/get-pip.py'

New-Item -ItemType Directory -Force -Path $runtimeRoot, $downloadRoot | Out-Null
if (-not (Test-Path -LiteralPath $pythonArchive)) {
  Write-Host "Downloading $pythonUrl"
  Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonArchive
}
if (-not (Test-Path -LiteralPath $getPip)) {
  Write-Host "Downloading $getPipUrl"
  Invoke-WebRequest -Uri $getPipUrl -OutFile $getPip
}

if (Test-Path -LiteralPath $pythonRoot) {
  Remove-Item -LiteralPath $pythonRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $pythonRoot | Out-Null
Expand-Archive -LiteralPath $pythonArchive -DestinationPath $pythonRoot -Force

$pthFile = Get-ChildItem -LiteralPath $pythonRoot -File -Filter 'python*._pth' | Select-Object -First 1
if (-not $pthFile) { throw 'Embedded Python _pth file was not found.' }
$pthLines = [System.Collections.Generic.List[string]](Get-Content -LiteralPath $pthFile.FullName)
for ($index = 0; $index -lt $pthLines.Count; $index++) {
  if ($pthLines[$index] -eq '#import site') { $pthLines[$index] = 'import site' }
}
if (-not $pthLines.Contains('Lib\site-packages')) {
  $pthLines.Insert([Math]::Max(0, $pthLines.Count - 1), 'Lib\site-packages')
}
Set-Content -LiteralPath $pthFile.FullName -Value $pthLines -Encoding ascii

$pythonExe = Join-Path $pythonRoot 'python.exe'
& $pythonExe $getPip --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw 'get-pip.py failed.' }
& $pythonExe -m pip install --disable-pip-version-check --no-cache-dir -r (Join-Path $projectRoot 'backend\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }

$modelRoot = Join-Path $runtimeRoot 'models\huggingface'
New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null
$env:HF_HOME = $modelRoot
& $pythonExe -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-small-zh-v1.5')"
if ($LASTEXITCODE -ne 0) { throw 'Base embedding model download failed.' }

$manifest = [ordered]@{
  runtimeVersion = "python-$PythonVersion-requirements-v2"
  pythonVersion = $PythonVersion
  architecture = 'x64'
  generatedAt = (Get-Date).ToUniversalTime().ToString('o')
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimeRoot 'runtime-manifest.json') -Encoding utf8

& $pythonExe -c "from sentence_transformers import SentenceTransformer; import fastapi, chromadb, fitz, docx, pptx, bs4, xmulogin; SentenceTransformer('BAAI/bge-small-zh-v1.5', local_files_only=True); print('Embedded runtime import check OK')"
if ($LASTEXITCODE -ne 0) { throw 'Embedded runtime import check failed.' }

$runtimeArchive = Join-Path $runtimeRoot 'python-runtime.tar'
if (Test-Path -LiteralPath $runtimeArchive) { Remove-Item -LiteralPath $runtimeArchive -Force }
& tar.exe -c -f $runtimeArchive -C $runtimeRoot 'python'
if ($LASTEXITCODE -ne 0) { throw 'Embedded runtime archive creation failed.' }
$modelsArchive = Join-Path $runtimeRoot 'models-runtime.tar'
if (Test-Path -LiteralPath $modelsArchive) { Remove-Item -LiteralPath $modelsArchive -Force }
& tar.exe -c -f $modelsArchive -C (Join-Path $runtimeRoot 'models') 'huggingface'
if ($LASTEXITCODE -ne 0) { throw 'Base embedding model archive creation failed.' }
Write-Host "Runtime ready: $pythonRoot"
