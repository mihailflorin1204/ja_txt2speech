import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JPTTS_DATA_DIR", str(Path(__file__).resolve().parent / "tmp_data"))
