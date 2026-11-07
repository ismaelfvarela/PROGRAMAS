"""Modelos de dados compartilhados do Roteiro IA."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Role(StrEnum):
    camera = "camera"
    drone = "drone"
    pocket = "pocket"
    audio_ambiente = "audio_ambiente"
    mesa = "mesa"
    lapela_noivo = "lapela_noivo"
    lapela_noiva = "lapela_noiva"
    outro_dia = "outro_dia"
    ignorar = "ignorar"


class FolderAssignment(BaseModel):
    folder: str
    role: Role
    day_label: str = "principal"


class MediaInfo(BaseModel):
    id: int | None = None
    rel_path: str
    folder: str
    role: Role
    day_label: str
    kind: Literal["video", "audio"]
    duration_s: float
    fps_num: int
    fps_den: int
    width: int
    height: int
    rotation: int
    audio_channels: int
    created_at: datetime | None = None
    timecode: str | None = None


class AudioStats(BaseModel):
    media_id: int
    mean_db: float
    peak_db: float
    noise_floor_db: float
    noisy: bool


class SyncResult(BaseModel):
    media_id: int
    day_label: str
    timeline_start_s: float
    confidence: float
    method: Literal["audio", "hora"]


class Word(BaseModel):
    text: str
    start_s: float
    end_s: float


class Transcript(BaseModel):
    media_id: int
    words: list[Word]
    source_role: Role


class Segment(BaseModel):
    id: int | None = None
    media_id: int
    start_s: float
    end_s: float


class Highlight(BaseModel):
    start_s: float
    end_s: float
    reason: str


class Quote(BaseModel):
    text: str
    start_s: float
    end_s: float


class SceneAnalysis(BaseModel):
    segment_id: int
    momento: str
    extra: str | None = None
    descricao: str
    pessoas: list[str]
    emocao_intensidade: int = Field(ge=0, le=10)
    emocao_tipo: str
    qualidade: int = Field(ge=0, le=10)
    problemas: list[str]
    melhores_trechos: list[Highlight]
    falas_chave: list[Quote]
    potencial_gancho: bool
    motivo_gancho: str | None = None
    sugestao_lembranca: bool
    som_ambiente: str = ""
    som_ambiente_util: bool = False


class TrackInfo(BaseModel):
    path: str
    bpm: float
    beats_s: list[float]
    downbeats_s: list[float]
    energy: list[float]
    duration_s: float
    has_vocals: bool
    perfil: Literal["calma", "crescente", "intensa"]
    mtime: float
    # Análise por melodia (versão 2). Todos com padrão: registros antigos continuam carregando.
    voz_proporcao: float = 0.0
    voz_inicio_s: float | None = None
    intro_instrumental_s: float = 0.0
    tonalidade: str = ""
    modo: Literal["maior", "menor", ""] = ""
    climas: list[str] = Field(default_factory=list)
    instrumentos: list[str] = Field(default_factory=list)
    tipo_voz: str = ""
    versao_analise: int = 1
    analise_parcial: bool = False


class Falha(BaseModel):
    id: int | None = None
    etapa: str
    rel_path: str
    msg: str
    created_at: str | None = None
