from datetime import UTC, datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Voice(SQLModel, table=True):
    id: str = Field(primary_key=True)
    engine: str = Field(index=True)
    engine_voice_id: str
    name: str
    gender: str = "unknown"
    styles: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    features: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    credit: str = ""
    is_cloned: bool = False
    is_favorite: bool = False
    consent_at: datetime | None = None
    model_path: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class CloneSample(SQLModel, table=True):
    id: str = Field(primary_key=True)
    voice_id: str | None = Field(default=None, foreign_key="voice.id", index=True)
    audio_path: str
    transcript: str = ""
    duration_s: float = 0.0
    quality_report: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)


class DictionaryEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    surface: str = Field(index=True)
    reading: str
    accent_type: int | None = None
    pos: str = ""
    priority: int = 0
    updated_at: datetime = Field(default_factory=_utcnow)


class Preset(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    voice_id: str = Field(foreign_key="voice.id")
    settings: dict = Field(default_factory=dict, sa_column=Column(JSON))


class Job(SQLModel, table=True):
    id: str = Field(primary_key=True)
    kind: str = "long_text"  # long_text | clone_finetune
    status: str = "queued"  # queued|running|paused|completed|failed|cancelled
    voice_id: str | None = Field(default=None, foreign_key="voice.id")
    settings: dict = Field(default_factory=dict, sa_column=Column(JSON))
    chapters: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    export_options: dict = Field(default_factory=dict, sa_column=Column(JSON))
    total_sentences: int = 0
    done_sentences: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class JobSentence(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(foreign_key="job.id", index=True)
    chapter_index: int = 0
    sentence_index: int = 0
    text: str
    status: str = "pending"  # pending|done|failed
    attempts: int = 0
    audio_path: str | None = None
    duration_s: float | None = None


class Generation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    text: str
    voice_id: str
    settings: dict = Field(default_factory=dict, sa_column=Column(JSON))
    audio_path: str
    format: str = "wav"
    duration_s: float | None = None
    created_at: datetime = Field(default_factory=_utcnow)
