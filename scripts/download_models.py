"""Download model weights for engines (run once, or on demand at engine start).

- Style-Bert-VITS2: models live in external/Style-Bert-VITS2/model_assets after
  `initialize.py` (handled by setup_engines.ps1).
- Whisper (faster-whisper) weights for clone transcripts are downloaded on
  first use in M5.

This script exists so `python scripts/download_models.py` can prefetch
everything offline-capable ahead of time.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SBV2 = ROOT / "external" / "Style-Bert-VITS2"


def main() -> int:
    py = SBV2 / "venv" / "Scripts" / "python.exe"
    if not py.exists():
        print("Style-Bert-VITS2 venv missing — run scripts/setup_engines.ps1 first")
        return 1
    print("Downloading default SBV2 models (this can take a while)…")
    return subprocess.call([str(py), "initialize.py"], cwd=SBV2)


if __name__ == "__main__":
    sys.exit(main())
