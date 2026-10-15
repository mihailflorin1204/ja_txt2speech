# Run jp-tts in dev mode: backend on :8000, Vite dev server on :5173.
# Usage: powershell -File scripts\run_dev.ps1

$root = Split-Path $PSScriptRoot -Parent
$env:PATH = "$root\tools\node;$root\tools\ffmpeg\bin;$env:PATH"

$backend = Start-Process -PassThru -NoNewWindow `
    -FilePath "$root\backend\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload" `
    -WorkingDirectory "$root\backend"

$env:PATH = "$root\tools\node;$env:PATH"
$pnpm = Join-Path $root "tools\node\node_modules\corepack\shims\pnpm.cmd"
if (-not (Test-Path $pnpm)) { $pnpm = "pnpm.cmd" }  # fall back to PATH
$frontend = Start-Process -PassThru -NoNewWindow `
    -FilePath $pnpm -ArgumentList "dev" `
    -WorkingDirectory "$root\frontend"

Write-Host "backend pid=$($backend.Id)  frontend pid=$($frontend.Id)"
Write-Host "UI: http://localhost:5173   API: http://127.0.0.1:8000/api/v1"
if ($frontend) {
    try { Wait-Process -Id $frontend.Id } finally {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Warning "frontend failed to start; backend still running (pid $($backend.Id))"
    Wait-Process -Id $backend.Id
}
