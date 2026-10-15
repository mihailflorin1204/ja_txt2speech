from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JPTTS_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    allow_non_loopback: bool = False

    data_dir: Path = BASE_DIR / "data"
    models_dir: Path = BASE_DIR / "models"
    external_dir: Path = BASE_DIR / "external"
    frontend_dist: Path = BASE_DIR / "frontend" / "dist"
    ffmpeg_path: Path = BASE_DIR / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"

    device: str = "auto"  # auto | cuda | cpu
    max_resident_engines: int = 2

    # Engine toggles and endpoints
    voicevox_enabled: bool = True
    voicevox_host: str = "127.0.0.1"
    voicevox_port: int = 50021
    voicevox_exe: Path = external_dir / "voicevox" / "run.exe"
    voicevox_use_gpu: bool = True

    sbv2_enabled: bool = True
    sbv2_host: str = "127.0.0.1"
    sbv2_port: int = 5000
    sbv2_repo: Path = external_dir / "Style-Bert-VITS2"
    sbv2_python: Path = external_dir / "Style-Bert-VITS2" / "venv" / "Scripts" / "python.exe"

    gptsovits_enabled: bool = False
    gptsovits_host: str = "127.0.0.1"
    gptsovits_port: int = 9880
    gptsovits_repo: Path = external_dir / "GPT-SoVITS"
    gptsovits_python: Path = external_dir / "GPT-SoVITS" / "venv" / "Scripts" / "python.exe"

    max_interactive_chars: int = 500
    history_limit: int = 50
    preview_text: str = "こんにちは。これは音声プレビューです。"

    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def samples_dir(self) -> Path:
        return self.data_dir / "samples"

    @property
    def previews_dir(self) -> Path:
        return self.data_dir / "previews"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for d in (settings.data_dir, settings.models_dir, settings.audio_dir,
              settings.samples_dir, settings.previews_dir):
        d.mkdir(parents=True, exist_ok=True)
    return settings
