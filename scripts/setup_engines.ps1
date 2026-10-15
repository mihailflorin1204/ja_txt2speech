# Setup script for external TTS engines (Windows).
# Downloads VOICEVOX Engine binary and installs Style-Bert-VITS2 into external/.
# Usage: powershell -File scripts\setup_engines.ps1
#
# Learned on this machine (slow/flaky links): big wheels are fetched with
# curl -C - (resumable) instead of pip, which can't resume a stalled download.

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$ext = Join-Path $root "external"
New-Item -ItemType Directory -Force $ext | Out-Null

$vvVersion = "0.25.2"
$vvDir = Join-Path $ext "voicevox\windows-nvidia"
$vvBase = "https://github.com/VOICEVOX/voicevox_engine/releases/download/$vvVersion"

# --- VOICEVOX Engine (Windows NVIDIA build; use -cpu variant for CPU-only) ---
if (-not (Test-Path (Join-Path $vvDir "run.exe"))) {
    $dl = Join-Path $ext "voicevox_dl"
    New-Item -ItemType Directory -Force $dl | Out-Null
    $p1 = Join-Path $dl "voicevox_engine-windows-nvidia-$vvVersion.7z.001"
    $p2 = Join-Path $dl "voicevox_engine-windows-nvidia-$vvVersion.7z.002"
    curl.exe -L --retry 10 --retry-all-errors -C - -o $p1 "$vvBase/voicevox_engine-windows-nvidia-$vvVersion.7z.001"
    curl.exe -L --retry 10 --retry-all-errors -C - -o $p2 "$vvBase/voicevox_engine-windows-nvidia-$vvVersion.7z.002"
    $seven = Join-Path $root "tools\7zr.exe"
    if (-not (Test-Path $seven)) {
        curl.exe -L -o $seven "https://www.7-zip.org/a/7zr.exe"
    }
    # split archive -> external\voicevox\windows-nvidia\run.exe
    & $seven x $p1 "-o$(Join-Path $ext 'voicevox')" -y
    Write-Host "VOICEVOX extracted"
} else {
    Write-Host "VOICEVOX already installed"
}

# --- Style-Bert-VITS2 (separate venv: pins torch<2.4) ---
$sbv2 = Join-Path $ext "Style-Bert-VITS2"
if (-not (Test-Path $sbv2)) {
    git clone --depth 1 https://github.com/litagin02/Style-Bert-VITS2.git $sbv2
}
$venvPy = Join-Path $sbv2 "venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    py -3.11 -m venv (Join-Path $sbv2 "venv")

    # torch cu121 2.3.1 wheel via resumable curl (pip stalls on this 2.4GB wheel)
    $torchWheel = Join-Path $sbv2 "torch-2.3.1+cu121-cp311-cp311-win_amd64.whl"
    if (-not (Test-Path $torchWheel)) {
        curl.exe -L --retry 10 --retry-all-errors -C - -o $torchWheel `
            "https://download.pytorch.org/whl/cu121/torch-2.3.1%2Bcu121-cp311-cp311-win_amd64.whl"
    }
    $taWheel = Join-Path $sbv2 "torchaudio-2.3.1+cu121-cp311-cp311-win_amd64.whl"
    if (-not (Test-Path $taWheel)) {
        curl.exe -L --retry 10 --retry-all-errors -C - -o $taWheel `
            "https://download.pytorch.org/whl/cu121/torchaudio-2.3.1%2Bcu121-cp311-cp311-win_amd64.whl"
    }
    # Windows torch needs these DLL packages (PyPI wheels; curl-resumable too)
    & $venvPy -m pip install --timeout 300 --retries 10 mkl==2021.4.0 intel-openmp tbb
    & $venvPy -m pip install --no-deps $torchWheel $taWheel
    & $venvPy -m pip install typing_extensions sympy networkx jinja2 fsspec filelock markupsafe mpmath

    # server-side deps only (skip gradio/pyannote/training stack)
    & $venvPy -m pip install --timeout 300 --retries 10 `
        "numpy<2" fastapi "uvicorn[standard]" GPUtil psutil scipy soundfile `
        "transformers==4.46.3" huggingface_hub safetensors librosa numba onnxruntime `
        pyopenjtalk-plus pyworld-prebuilt pypinyin cn2an jieba num2words inflect `
        g2p_en nltk loguru punctuators "protobuf==4.25" cmudict accelerate

    Push-Location $sbv2
    & $venvPy initialize.py --only_infer   # bert + default jvnv models (no training assets)
    Pop-Location
    Write-Host "Style-Bert-VITS2 installed"
} else {
    Write-Host "Style-Bert-VITS2 already installed"
}

# --- GPT-SoVITS (M5, optional) ---
$gsv = Join-Path $ext "GPT-SoVITS"
if (-not (Test-Path $gsv)) {
    git clone --depth 1 https://github.com/RVC-Boss/GPT-SoVITS.git $gsv
    Write-Host "GPT-SoVITS cloned - set up its venv when enabling cloning"
}

Write-Host "Done. Engines live under external/ (gitignored)."
