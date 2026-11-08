import sqlite3
import json
from pathlib import Path
from contextlib import closing
from typing import List, Optional, Dict, Any
from src.common.config import settings
from src.common.models import ViralMomentCandidate

JOB_FIELDS = {"status", "step_index", "step_label", "message", "progress", "video_id", "error", "options"}


class Database:
    """
    Gestión de persistencia SQLite para Clip Factory Profesional.
    Almacena videos procesados, candidatos (clips) y la cola de trabajos (jobs).
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with closing(self.get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    duration REAL,
                    language TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS candidates (
                    id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    duration REAL NOT NULL,
                    title TEXT,
                    hook_text TEXT,
                    context_text TEXT,
                    virality_score INTEGER NOT NULL,
                    hook_score INTEGER DEFAULT 80,
                    flow_score INTEGER DEFAULT 80,
                    trend_score INTEGER DEFAULT 80,
                    category TEXT,
                    reasoning TEXT,
                    social_description TEXT,
                    hashtags TEXT,
                    status TEXT DEFAULT 'pending',
                    clip_path TEXT,
                    FOREIGN KEY (video_id) REFERENCES videos(id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL DEFAULT 'process',
                    source TEXT NOT NULL DEFAULT '',
                    options TEXT DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'queued',
                    step_index INTEGER DEFAULT 0,
                    step_label TEXT DEFAULT '',
                    message TEXT DEFAULT '',
                    progress REAL DEFAULT 0,
                    video_id TEXT,
                    candidate_id TEXT,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Migraciones defensivas para bases de datos existentes
            self._add_missing_columns(cursor, "candidates", [
                ("title", "TEXT"),
                ("hook_score", "INTEGER DEFAULT 80"),
                ("flow_score", "INTEGER DEFAULT 80"),
                ("trend_score", "INTEGER DEFAULT 80"),
                ("social_description", "TEXT"),
                ("hashtags", "TEXT"),
                ("engine", "TEXT DEFAULT 'heuristic'"),
                ("dirty", "INTEGER DEFAULT 0"),   # 1 = tiempos editados, falta re-renderizar
            ])
            self._add_missing_columns(cursor, "videos", [
                ("source", "TEXT"),
                ("transcript_path", "TEXT"),
            ])
            # Índices de las consultas más frecuentes (clips de un video, cola por estado)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_video ON candidates(video_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, id)")
            # WAL: el dashboard lee mientras el worker escribe sin bloquearse (el modo queda guardado en el archivo)
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass
            conn.commit()

    @staticmethod
    def _add_missing_columns(cursor, table: str, columns):
        existing = [col[1] for col in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
        for name, col_type in columns:
            if name not in existing:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")

    # ------------------------------------------------------------------ videos
    def save_video(self, video_id: str, filename: str, filepath: str, duration: float, language: str,
                   source: Optional[str] = None, transcript_path: Optional[str] = None):
        with closing(self.get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO videos (id, filename, filepath, duration, language, source, transcript_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (video_id, filename, filepath, duration, language, source, transcript_path))
            conn.commit()

    def update_video_filepath(self, video_id: str, filepath: str):
        with closing(self.get_connection()) as conn:
            conn.execute("UPDATE videos SET filepath = ? WHERE id = ?", (filepath, video_id))
            conn.commit()

    def get_video(self, video_id: str) -> Optional[Dict[str, Any]]:
        with closing(self.get_connection()) as conn:
            row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
            return dict(row) if row else None

    def get_all_videos(self) -> List[Dict[str, Any]]:
        """Más reciente primero (created_at y, si empatan, rowid)."""
        with closing(self.get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM videos ORDER BY created_at DESC, rowid DESC")
            return [dict(row) for row in cursor.fetchall()]

    # -------------------------------------------------------------- candidates
    def save_candidates(self, video_id: str, candidates: List[ViralMomentCandidate], clip_paths: Optional[Dict[str, str]] = None):
        clip_paths = clip_paths or {}
        with closing(self.get_connection()) as conn:
            cursor = conn.cursor()
            for cand in candidates:
                c_path = clip_paths.get(cand.id, "")
                cursor.execute("""
                    INSERT OR REPLACE INTO candidates (
                        id, video_id, start_time, end_time, duration,
                        title, hook_text, context_text, virality_score,
                        hook_score, flow_score, trend_score,
                        category, reasoning, social_description, hashtags, status, clip_path, engine
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    cand.id, video_id, cand.start_time, cand.end_time, cand.duration,
                    cand.title, cand.hook_text, cand.context_text, float(cand.virality_score),
                    cand.breakdown.hook_score, cand.breakdown.flow_score, cand.breakdown.trend_score,
                    cand.category, cand.reasoning, cand.social_description,
                    json.dumps(cand.hashtags, ensure_ascii=False), cand.status, c_path, cand.engine
                ))
            conn.commit()

    def update_candidate_status(self, candidate_id: str, status: str):
        with closing(self.get_connection()) as conn:
            conn.execute("UPDATE candidates SET status = ? WHERE id = ?", (status, candidate_id))
            conn.commit()

    def update_candidate_clip_path(self, candidate_id: str, clip_path: str, dirty: bool = False):
        with closing(self.get_connection()) as conn:
            conn.execute("UPDATE candidates SET clip_path = ?, dirty = ? WHERE id = ?",
                         (clip_path, 1 if dirty else 0, candidate_id))
            conn.commit()

    def update_candidate_fields(
        self,
        candidate_id: str,
        title: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        dirty: Optional[bool] = None,
    ):
        """Edita título y/o tiempos. Si cambian los tiempos o se especifica dirty, marca el clip."""
        cand = self.get_candidate(candidate_id)
        if not cand:
            return None
        new_title = cand["title"] if title is None else title
        new_start = cand["start_time"] if start_time is None else start_time
        new_end = cand["end_time"] if end_time is None else end_time
        times_changed = (new_start != cand["start_time"]) or (new_end != cand["end_time"])
        if dirty is not None:
            dirty_flag = 1 if dirty else 0
        else:
            dirty_flag = 1 if (times_changed or cand.get("dirty")) else 0
        with closing(self.get_connection()) as conn:
            conn.execute(
                "UPDATE candidates SET title = ?, start_time = ?, end_time = ?, duration = ?, dirty = ? WHERE id = ?",
                (new_title, new_start, new_end, round(new_end - new_start, 2), dirty_flag, candidate_id)
            )
            conn.commit()
        return self.get_candidate(candidate_id)

    @staticmethod
    def _parse_candidate(row) -> Dict[str, Any]:
        r = dict(row)
        if r.get("hashtags") and isinstance(r["hashtags"], str):
            try:
                r["hashtags"] = json.loads(r["hashtags"])
            except Exception:
                r["hashtags"] = []
        else:
            r["hashtags"] = []
        return r

    def get_candidate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        with closing(self.get_connection()) as conn:
            row = conn.execute("SELECT * FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
            return self._parse_candidate(row) if row else None

    def get_candidates_by_video(self, video_id: str) -> List[Dict[str, Any]]:
        with closing(self.get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM candidates WHERE video_id = ? ORDER BY virality_score DESC", (video_id,))
            return [self._parse_candidate(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, int]:
        with closing(self.get_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM videos")
            total_videos = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM candidates WHERE status = 'approved'")
            approved_clips = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM candidates WHERE status = 'pending'")
            pending_clips = cursor.fetchone()[0]
            return {
                "total_videos": total_videos,
                "approved_clips": approved_clips,
                "pending_clips": pending_clips
            }

    # -------------------------------------------------------------------- jobs
    def create_job(self, source: str, options: Optional[Dict[str, Any]] = None,
                   kind: str = "process", candidate_id: Optional[str] = None,
                   video_id: Optional[str] = None) -> int:
        with closing(self.get_connection()) as conn:
            cur = conn.execute(
                "INSERT INTO jobs (kind, source, options, candidate_id, video_id) VALUES (?, ?, ?, ?, ?)",
                (kind, source, json.dumps(options or {}, ensure_ascii=False), candidate_id, video_id))
            conn.commit()
            return int(cur.lastrowid)

    @staticmethod
    def _parse_job(row) -> Dict[str, Any]:
        j = dict(row)
        try:
            j["options"] = json.loads(j.get("options") or "{}")
        except Exception:
            j["options"] = {}
        return j

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        with closing(self.get_connection()) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._parse_job(row) if row else None

    def list_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with closing(self.get_connection()) as conn:
            rows = conn.execute("""
                SELECT j.*, v.duration AS video_duration
                FROM jobs j
                LEFT JOIN videos v ON j.video_id = v.id
                ORDER BY j.id DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [self._parse_job(r) for r in rows]

    def update_job(self, job_id: int, **fields):
        fields = {k: v for k, v in fields.items() if k in JOB_FIELDS}
        if not fields:
            return
        if "options" in fields and not isinstance(fields["options"], str):
            fields["options"] = json.dumps(fields["options"], ensure_ascii=False)
        sets = ", ".join(f"{k} = ?" for k in fields) + ", updated_at = CURRENT_TIMESTAMP"
        with closing(self.get_connection()) as conn:
            conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", (*fields.values(), job_id))
            conn.commit()

    def claim_next_job(self) -> Optional[Dict[str, Any]]:
        """Toma de forma atómica el trabajo en cola más antiguo y lo marca como 'running'."""
        with closing(self.get_connection()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
            if not row:
                conn.rollback()
                return None
            conn.execute("UPDATE jobs SET status = 'running', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
            conn.commit()
            return self._parse_job(conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())

    def cancel_job(self, job_id: int, allow_running: bool = False) -> bool:
        """Cancela trabajos en cola (o en ejecución si allow_running=True)."""
        statuses = "('queued', 'running')" if allow_running else "('queued')"
        with closing(self.get_connection()) as conn:
            cur = conn.execute(
                f"UPDATE jobs SET status = 'cancelled', message = 'Cancelado por el usuario', "
                f"updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status IN {statuses}",
                (job_id,))
            conn.commit()
            return cur.rowcount > 0

    def reset_stale_jobs(self) -> int:
        """Al arrancar: los trabajos que quedaron 'running' (servidor cerrado) pasan a error."""
        with closing(self.get_connection()) as conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'error', error = 'Interrumpido al reiniciar el servidor', "
                "updated_at = CURRENT_TIMESTAMP WHERE status = 'running'")
            conn.commit()
            return cur.rowcount


db = Database()
