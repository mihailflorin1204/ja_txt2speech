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

# --- GPT-SoVITS (voice cloning) ---
$gsv = Join-Path $ext "GPT-SoVITS"
if (-not (Test-Path $gsv)) {
    git clone --depth 1 https://github.com/RVC-Boss/GPT-SoVITS.git $gsv
}
$gsvPy = Join-Path $gsv "venv\Scripts\python.exe"
if (-not (Test-Path $gsvPy)) {
    py -3.11 -m venv (Join-Path $gsv "venv")
    # reuse the SBV2 torch wheel if present (same 2.3.1+cu121 pin)
    $torchWheel = Join-Path $sbv2 "torch-2.3.1+cu121-cp311-cp311-win_amd64.whl"
    $taWheel = Join-Path $sbv2 "torchaudio-2.3.1+cu121-cp311-cp311-win_amd64.whl"
    & $gsvPy -m pip install --timeout 300 --retries 10 mkl==2021.4.0 intel-openmp tbb
    if (Test-Path $torchWheel) {
        & $gsvPy -m pip install --no-deps $torchWheel $taWheel
    } else {
        & $gsvPy -m pip install "torch<2.4" "torchaudio<2.4" --index-url https://download.pytorch.org/whl/cu121
    }
    & $gsvPy -m pip install --timeout 300 --retries 10 `
        typing_extensions sympy networkx jinja2 fsspec filelock markupsafe mpmath `
        "numpy<2.0" scipy librosa==0.10.2 numba "transformers>=4.51,<5" peft einops `
        onnxruntime-gpu sentencepiece ffmpeg-python pyyaml psutil tqdm requests `
        jieba split-lang "fast_langdetect>=0.3.1" wordsegment ToJyutping g2pk2 `
        ko_pron opencc jamo cn2an pypinyin g2p_en inflect nltk matplotlib resampy `
        "fastapi[standard]>=0.115.2" "uvicorn[standard]" "pydantic<=2.10.6" `
        "torchmetrics<=1.5" "pytorch-lightning>=2.4" pyopenjtalk-plus cmudict
    # torch>=2.4-only deps installed without deps (keeps cu121 2.3.1)
    & $gsvPy -m pip install --no-deps rotary_embedding_torch x_transformers
    & $gsvPy -m pip install loguru einx torch-einops-utils

    # jieba_fast has no Windows wheel -> shim it with plain jieba
    $jf = Join-Path $gsv "venv\Lib\site-packages\jieba_fast"
    New-Item -ItemType Directory -Force $jf | Out-Null
    Set-Content (Join-Path $jf "__init__.py") @"
from jieba import *
from jieba import lcut, lcut_for_search, cut, cut_for_search, load_userdict, Tokenizer, posseg
import sys, jieba
sys.modules.setdefault("jieba_fast.posseg", __import__("jieba.posseg", fromlist=["posseg"]))
"@

    # pretrained models (roberta, hubert, gsv v2) + safetensors conversion
    # (transformers>=4.52 blocks torch.load on torch<2.6 -> need safetensors)
    Push-Location $gsv
    & $gsvPy -c @"
from huggingface_hub import hf_hub_download
import torch, safetensors.torch
files = [
 'chinese-roberta-wwm-ext-large/config.json',
 'chinese-roberta-wwm-ext-large/pytorch_model.bin',
 'chinese-roberta-wwm-ext-large/tokenizer.json',
 'chinese-hubert-base/config.json',
 'chinese-hubert-base/preprocessor_config.json',
 'chinese-hubert-base/pytorch_model.bin',
 'gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt',
 'gsv-v2final-pretrained/s2D2333k.pth',
 'gsv-v2final-pretrained/s2G2333k.pth',
]
for f in files:
    hf_hub_download('lj1995/GPT-SoVITS', f, local_dir='GPT_SoVITS/pretrained_models')
# convert .bin -> safetensors to satisfy CVE-2025-32434 torch>=2.6 check
for d in ['chinese-roberta-wwm-ext-large', 'chinese-hubert-base']:
    p = f'GPT_SoVITS/pretrained_models/{d}'
    sd = torch.load(p + '/pytorch_model.bin', map_location='cpu', weights_only=True)
    seen, out = set(), {}
    for k, v in sd.items():
        key = (v.data_ptr(), v.numel(), tuple(v.shape))
        if key in seen: continue
        seen.add(key); out[k] = v.contiguous()
    safetensors.torch.save_file(out, p + '/model.safetensors')
print('models ready')
"@
    # fast_langdetect model cache (lid.176.bin + ftz)
    & $gsvPy -c "from fast_langdetect import LangDetectConfig, LangDetector; LangDetector(LangDetectConfig(cache_dir='GPT_SoVITS/pretrained_models/fast_langdetect', model='auto'))"
    Pop-Location
    Write-Host "GPT-SoVITS installed"
} else {
    Write-Host "GPT-SoVITS already installed"
}

Write-Host "Done. Engines live under external/ (gitignored)."
