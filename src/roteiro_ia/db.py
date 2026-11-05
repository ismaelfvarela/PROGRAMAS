"""Banco SQLite por projeto (idempotente, chaves naturais)."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal

from .config import Settings
from .models import (
    AudioStats, Falha, MediaInfo, Role, SceneAnalysis, Segment, SyncResult, Transcript,
)
from .safety import assert_writable, safe_mkdir

StageStatus = Literal["pendente", "rodando", "pausado", "feito", "erro"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media(
  id INTEGER PRIMARY KEY AUTOINCREMENT, rel_path TEXT NOT NULL UNIQUE,
  folder TEXT, role TEXT, day_label TEXT, kind TEXT, duration_s REAL,
  fps_num INTEGER, fps_den INTEGER, width INTEGER, height INTEGER,
  rotation INTEGER, audio_channels INTEGER, created_at TEXT, timecode TEXT);
CREATE TABLE IF NOT EXISTS proxies(
  media_id INTEGER PRIMARY KEY, path TEXT NOT NULL, origem TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audio_stats(
  media_id INTEGER PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync(
  media_id INTEGER PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transcripts(
  media_id INTEGER PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS segments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, media_id INTEGER NOT NULL,
  start_s REAL NOT NULL, end_s REAL NOT NULL,
  UNIQUE(media_id, start_s, end_s));
CREATE TABLE IF NOT EXISTS analyses(
  segment_id INTEGER PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS roteiros(
  versao INTEGER PRIMARY KEY AUTOINCREMENT, json_text TEXT NOT NULL, created_at TEXT);
CREATE TABLE IF NOT EXISTS stages(
  name TEXT PRIMARY KEY, status TEXT NOT NULL, detail TEXT DEFAULT '', updated_at TEXT);
CREATE TABLE IF NOT EXISTS falhas(
  id INTEGER PRIMARY KEY AUTOINCREMENT, etapa TEXT, rel_path TEXT, msg TEXT, created_at TEXT);
"""

_MEDIA_COLS = [
    "rel_path", "folder", "role", "day_label", "kind", "duration_s", "fps_num",
    "fps_den", "width", "height", "rotation", "audio_channels", "created_at", "timecode",
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ProjectDB:
    def __init__(self, path: Path, s: Settings):
        path = Path(path)
        assert_writable(path, s)
        safe_mkdir(path.parent, s)
        self.path = path
        self._c = sqlite3.connect(str(path), check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.executescript(_SCHEMA)
        self._c.commit()

    def close(self) -> None:
        self._c.close()

    def __enter__(self) -> "ProjectDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- media
    @staticmethod
    def _to_media(r: sqlite3.Row) -> MediaInfo:
        return MediaInfo(**dict(r))

    def add_media(self, m: MediaInfo) -> int:
        vals = []
        for c in _MEDIA_COLS:
            v = getattr(m, c)
            if c == "role":
                v = str(v)
            elif c == "created_at" and v is not None:
                v = v.isoformat()
            vals.append(v)
        row = self._c.execute("SELECT id FROM media WHERE rel_path=?", (m.rel_path,)).fetchone()
        if row:
            sets = ",".join(f"{c}=?" for c in _MEDIA_COLS)
            self._c.execute(f"UPDATE media SET {sets} WHERE id=?", (*vals, row["id"]))
            mid = row["id"]
        else:
            q = ",".join("?" * len(_MEDIA_COLS))
            cur = self._c.execute(
                f"INSERT INTO media({','.join(_MEDIA_COLS)}) VALUES({q})", vals)
            mid = cur.lastrowid
        self._c.commit()
        return int(mid)

    def list_media(self, role: Role | None = None) -> list[MediaInfo]:
        if role is None:
            rows = self._c.execute("SELECT * FROM media ORDER BY id").fetchall()
        else:
            rows = self._c.execute(
                "SELECT * FROM media WHERE role=? ORDER BY id", (str(role),)).fetchall()
        return [self._to_media(r) for r in rows]

    def get_media(self, id: int) -> MediaInfo | None:
        r = self._c.execute("SELECT * FROM media WHERE id=?", (id,)).fetchone()
        return self._to_media(r) if r else None

    def media_by_rel(self, rel_path: str) -> MediaInfo | None:
        r = self._c.execute("SELECT * FROM media WHERE rel_path=?", (rel_path,)).fetchone()
        return self._to_media(r) if r else None

    # --- proxies
    def set_proxy(self, media_id: int, path: str, origem: Literal["gerado", "lrf"]) -> None:
        self._c.execute(
            "INSERT OR REPLACE INTO proxies(media_id,path,origem) VALUES(?,?,?)",
            (media_id, path, origem))
        self._c.commit()

    def proxy_for(self, media_id: int) -> str | None:
        r = self._c.execute("SELECT path FROM proxies WHERE media_id=?", (media_id,)).fetchone()
        return r["path"] if r else None

    # --- JSON por chave
    def _put(self, table: str, key: int, model) -> None:
        col = "segment_id" if table == "analyses" else "media_id"
        self._c.execute(
            f"INSERT OR REPLACE INTO {table}({col},data) VALUES(?,?)",
            (key, model.model_dump_json()))
        self._c.commit()

    def _get(self, table: str, key: int, cls):
        col = "segment_id" if table == "analyses" else "media_id"
        r = self._c.execute(f"SELECT data FROM {table} WHERE {col}=?", (key,)).fetchone()
        return cls.model_validate_json(r["data"]) if r else None

    def set_audio_stats(self, a: AudioStats) -> None:
        self._put("audio_stats", a.media_id, a)

    def get_audio_stats(self, media_id: int) -> AudioStats | None:
        return self._get("audio_stats", media_id, AudioStats)

    def set_sync(self, r: SyncResult) -> None:
        self._put("sync", r.media_id, r)

    def get_sync(self, media_id: int) -> SyncResult | None:
        return self._get("sync", media_id, SyncResult)

    def set_transcript(self, t: Transcript) -> None:
        self._put("transcripts", t.media_id, t)

    def get_transcript(self, media_id: int) -> Transcript | None:
        return self._get("transcripts", media_id, Transcript)

    def set_analysis(self, a: SceneAnalysis) -> None:
        self._put("analyses", a.segment_id, a)

    def get_analysis(self, segment_id: int) -> SceneAnalysis | None:
        return self._get("analyses", segment_id, SceneAnalysis)

    # --- segments
    def add_segments(self, segs: list[Segment]) -> list[int]:
        """Insere (idempotente) e devolve os ids, na ordem dada."""
        ids = []
        for sg in segs:
            self._c.execute(
                "INSERT OR IGNORE INTO segments(media_id,start_s,end_s) VALUES(?,?,?)",
                (sg.media_id, sg.start_s, sg.end_s))
            r = self._c.execute(
                "SELECT id FROM segments WHERE media_id=? AND start_s=? AND end_s=?",
                (sg.media_id, sg.start_s, sg.end_s)).fetchone()
            ids.append(int(r["id"]))
        self._c.commit()
        return ids

    def list_segments(self, media_id: int | None = None) -> list[Segment]:
        if media_id is None:
            rows = self._c.execute("SELECT * FROM segments ORDER BY id").fetchall()
        else:
            rows = self._c.execute(
                "SELECT * FROM segments WHERE media_id=? ORDER BY start_s", (media_id,)).fetchall()
        return [Segment(**dict(r)) for r in rows]

    # --- roteiros
    def add_roteiro(self, json_text: str) -> int:
        cur = self._c.execute(
            "INSERT INTO roteiros(json_text,created_at) VALUES(?,?)", (json_text, _now()))
        self._c.commit()
        return int(cur.lastrowid)

    def latest_roteiro(self) -> str | None:
        r = self._c.execute(
            "SELECT json_text FROM roteiros ORDER BY versao DESC LIMIT 1").fetchone()
        return r["json_text"] if r else None

    # --- stages
    def stage_status(self, name: str) -> StageStatus:
        r = self._c.execute("SELECT status FROM stages WHERE name=?", (name,)).fetchone()
        return r["status"] if r else "pendente"

    def stage_detail(self, name: str) -> str:
        r = self._c.execute("SELECT detail FROM stages WHERE name=?", (name,)).fetchone()
        return (r["detail"] or "") if r else ""

    def set_stage(self, name: str, status: StageStatus, detail: str = "") -> None:
        self._c.execute(
            "INSERT OR REPLACE INTO stages(name,status,detail,updated_at) VALUES(?,?,?,?)",
            (name, status, detail, _now()))
        self._c.commit()

    # --- falhas
    def add_falha(self, etapa: str, rel_path: str, msg: str) -> None:
        self._c.execute(
            "INSERT INTO falhas(etapa,rel_path,msg,created_at) VALUES(?,?,?,?)",
            (etapa, rel_path, msg, _now()))
        self._c.commit()

    def clear_falhas(self, etapa: str) -> None:
        self._c.execute("DELETE FROM falhas WHERE etapa=?", (etapa,))
        self._c.commit()

    def count_falhas(self, etapa: str) -> int:
        return self._c.execute("SELECT COUNT(*) FROM falhas WHERE etapa=?", (etapa,)).fetchone()[0]

    def list_falhas(self) -> list[Falha]:
        rows = self._c.execute("SELECT * FROM falhas ORDER BY id").fetchall()
        return [Falha(**dict(r)) for r in rows]
