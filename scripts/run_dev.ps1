# Run jp-tts in dev mode: backend on :8000, Vite dev server on :5173.
# Usage: powershell -File scripts\run_dev.ps1

$root = Split-Path $PSScriptRoot -Parent
$env:PATH = "$root\tools\node;$root\tools\ffmpeg\bin;$env:PATH"

$backend = Start-Process -PassThru -NoNewWindow `
    -FilePath "$root\backend\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload" `
    -WorkingDirectory "$root\backend"

$frontend = Start-Process -PassThru -NoNewWindow `
    -FilePath "pnpm" -ArgumentList "dev" `
    -WorkingDirectory "$root\frontend"

Write-Host "backend pid=$($backend.Id)  frontend pid=$($frontend.Id)"
Write-Host "UI: http://localhost:5173   API: http://127.0.0.1:8000/api/v1"
try { Wait-Process -Id $frontend.Id } finally {
    Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
}
