"""
cache/db.py

Schema SQLite:
  segments      — catalogo segmenti (Strava + auto)
  fetched_tiles — tile bbox già interrogate
  activities    — ogni GPX importato
  efforts       — ogni volta che un segmento è stato percorso

Changelog:
  v2: activities.strava_activity_id — ID attività su Strava (per fetch effort API)
      activities.strava_effort_source — 'local'|'strava_api' (come sono stati importati)
      efforts.strava_effort_id — ID effort Strava (dedup)
      efforts.source — 'frechet'|'strava_api'
"""
from typing import List, Optional
import sqlite3
import logging
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CachedSegment:
    segment_id: int
    name: str
    source: str
    activity_type: str
    avg_grade: float
    distance: float
    elev_difference: float
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    polyline: str


@dataclass
class Effort:
    effort_id: Optional[int]
    activity_id: int
    segment_id: int
    elapsed_seconds: float
    avg_speed_ms: float
    avg_grade_pct: float
    distance_m: float
    elev_gain_m: float
    frechet_distance_m: float
    start_idx: int
    end_idx: int
    strava_effort_id: Optional[int] = None
    source: str = "frechet"
    start_time_s: Optional[float] = None   # epoch UTC — ordinamento stabile
    average_heartrate: Optional[float] = None


@dataclass
class PowerBest:
    """Record di potenza media massima su un intervallo."""
    power_best_id: Optional[int]
    activity_id: int
    interval_minutes: int
    watts: float
    start_s: float          # secondi dall'inizio attività
    end_s: float
    activity_date: Optional[str] = None  # per ranking cross-activity


class SegmentCache:

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS segments (
        segment_id    INTEGER PRIMARY KEY,
        name          TEXT,
        source        TEXT NOT NULL DEFAULT 'strava',
        activity_type TEXT,
        avg_grade     REAL,
        distance      REAL,
        elev_difference REAL,
        start_lat     REAL,
        start_lng     REAL,
        end_lat       REAL,
        end_lng       REAL,
        polyline      TEXT,
        fetched_at    TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS fetched_tiles (
        tile_key      TEXT PRIMARY KEY,
        fetched_at    TEXT DEFAULT (datetime('now')),
        segment_count INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS activities (
        activity_id           INTEGER PRIMARY KEY AUTOINCREMENT,
        strava_activity_id    INTEGER UNIQUE DEFAULT NULL,
        strava_effort_source  TEXT DEFAULT 'local',
        notes                 TEXT DEFAULT NULL,
        filename              TEXT NOT NULL,
        activity_date         TEXT,
        total_distance_m      REAL,
        total_elevation_m     REAL,
        num_points            INTEGER,
        imported_at           TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS efforts (
        effort_id          INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id        INTEGER NOT NULL REFERENCES activities(activity_id),
        segment_id         INTEGER NOT NULL REFERENCES segments(segment_id),
        strava_effort_id   INTEGER UNIQUE DEFAULT NULL,
        source             TEXT DEFAULT 'frechet',
        elapsed_seconds    REAL,
        avg_speed_ms       REAL,
        avg_grade_pct      REAL,
        distance_m         REAL,
        elev_gain_m        REAL,
        frechet_distance_m REAL,
        start_idx          INTEGER,
        end_idx            INTEGER,
        average_heartrate  REAL
    );

    CREATE INDEX IF NOT EXISTS idx_segments_bbox  ON segments (start_lat, start_lng);
    CREATE INDEX IF NOT EXISTS idx_efforts_seg    ON efforts (segment_id);
    CREATE INDEX IF NOT EXISTS idx_efforts_act    ON efforts (activity_id);
    CREATE INDEX IF NOT EXISTS idx_activities_strava ON activities (strava_activity_id);
    """

    # Colonne aggiunte in versioni successive — migrate automaticamente
    _MIGRATIONS = [
        ("activities", "notes",                "TEXT DEFAULT NULL"),
        ("activities", "strava_activity_id",   "INTEGER UNIQUE DEFAULT NULL"),
        ("activities", "strava_effort_source", "TEXT DEFAULT 'local'"),
        ("efforts",    "strava_effort_id",      "INTEGER UNIQUE DEFAULT NULL"),
        ("efforts",    "source",                "TEXT DEFAULT 'frechet'"),
        ("efforts",    "start_time_s",          "REAL DEFAULT NULL"),
        ("efforts",    "average_heartrate",    "REAL DEFAULT NULL"),
        ("activities", "gpx_points",             "TEXT DEFAULT NULL"),
        ("activities", "stream_length",           "INTEGER DEFAULT NULL"),
        ("activities", "moving_time_s",           "INTEGER DEFAULT NULL"),
        ("activities", "avg_heartrate",           "REAL DEFAULT NULL"),
        ("activities", "avg_watts",               "REAL DEFAULT NULL"),
        ("activities", "avg_cadence",             "REAL DEFAULT NULL"),
        ("activities", "calories",               "INTEGER DEFAULT NULL"),
        ("activities", "max_heartrate",           "REAL DEFAULT NULL"),
        ("activities", "activity_name",           "TEXT DEFAULT NULL"),
        ("activities", "gpx_path",               "TEXT DEFAULT NULL"),
        ("activities", "max_cadence",             "REAL DEFAULT NULL"),
        ("activities", "sigma_heartrate",         "REAL DEFAULT NULL"),
        ("activities", "sigma_cadence",           "REAL DEFAULT NULL"),
        ("activities", "gpx_warning",             "TEXT DEFAULT NULL"),
    ]

    # Schema tabella power_bests (creata separatamente per retrocompatibilità)
    POWER_BESTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS power_bests (
        power_best_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id       INTEGER NOT NULL REFERENCES activities(activity_id),
        interval_minutes  INTEGER NOT NULL,
        watts             REAL NOT NULL,
        start_s           REAL NOT NULL,
        end_s             REAL NOT NULL,
        created_at        TEXT DEFAULT (datetime('now')),
        UNIQUE(activity_id, interval_minutes)
    );
    CREATE INDEX IF NOT EXISTS idx_pb_interval ON power_bests(interval_minutes);
    CREATE INDEX IF NOT EXISTS idx_pb_watts ON power_bests(interval_minutes, watts DESC);
    """

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_db()

    def _init_db(self):
        self._conn.executescript(self.SCHEMA)
        # Assicura che le tabelle aggiunte dopo la prima init esistano
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        # Tabella power_bests (aggiunta v3)
        self._conn.executescript(self.POWER_BESTS_SCHEMA)
        # Migrazione incrementale: aggiunge colonne mancanti senza perdere dati
        for table, col, typedef in self._MIGRATIONS:
            existing = {r[1] for r in self._conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()}
            if col not in existing:
                try:
                    self._conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"
                    )
                    logger.info(f"Migrazione: aggiunta colonna {table}.{col}")
                except Exception as e:
                    logger.warning(f"Migrazione {table}.{col} fallita: {e}")
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __del__(self):
        self.close()

    # --- Tiles ---

    def is_tile_fetched(self, tile_key):
        return self._conn.execute(
            "SELECT 1 FROM fetched_tiles WHERE tile_key=?", (tile_key,)
        ).fetchone() is not None

    def mark_tile_fetched(self, tile_key, segment_count=0):
        self._conn.execute(
            "INSERT OR REPLACE INTO fetched_tiles (tile_key, segment_count) VALUES (?,?)",
            (tile_key, segment_count)
        )
        self._conn.commit()

    # --- Segments ---

    def upsert_segment(self, seg):
        self._conn.execute(
            """INSERT OR REPLACE INTO segments
               (segment_id,name,source,activity_type,avg_grade,distance,
                elev_difference,start_lat,start_lng,end_lat,end_lng,polyline)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (seg.segment_id, seg.name, seg.source, seg.activity_type,
             seg.avg_grade, seg.distance, seg.elev_difference,
             seg.start_lat, seg.start_lng, seg.end_lat, seg.end_lng, seg.polyline)
        )
        self._conn.commit()

    def get_all_segments(self):
        rows = self._conn.execute(
            """SELECT segment_id,name,source,activity_type,avg_grade,distance,
                      elev_difference,start_lat,start_lng,end_lat,end_lng,polyline
               FROM segments"""
        ).fetchall()
        return [self._row_to_segment(r) for r in rows]

    def get_segments_in_bbox(self, lat_min, lat_max, lng_min, lng_max):
        rows = self._conn.execute(
            """SELECT segment_id,name,source,activity_type,avg_grade,distance,
                      elev_difference,start_lat,start_lng,end_lat,end_lng,polyline
               FROM segments
               WHERE start_lat BETWEEN ? AND ? AND start_lng BETWEEN ? AND ?""",
            (lat_min, lat_max, lng_min, lng_max)
        ).fetchall()
        return [self._row_to_segment(r) for r in rows]

    def count(self):
        return self._conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]

    # --- Activities ---

    def find_activity(self, filename, activity_date, strava_activity_id=None):
        if strava_activity_id:
            row = self._conn.execute(
                "SELECT activity_id FROM activities WHERE strava_activity_id=?",
                (strava_activity_id,)
            ).fetchone()
            if row:
                return row["activity_id"]
        if activity_date:
            row = self._conn.execute(
                "SELECT activity_id FROM activities WHERE filename=? AND activity_date=?",
                (filename, activity_date)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT activity_id FROM activities WHERE filename=? AND activity_date IS NULL",
                (filename,)
            ).fetchone()
        return row["activity_id"] if row else None

    def insert_activity(self, filename, activity_date, total_distance_m,
                        total_elevation_m, num_points,
                        strava_activity_id=None, strava_effort_source="local"):
        cur = self._conn.execute(
            """INSERT INTO activities
               (filename, activity_date, total_distance_m, total_elevation_m,
                num_points, strava_activity_id, strava_effort_source)
               VALUES (?,?,?,?,?,?,?)""",
            (filename, activity_date, total_distance_m, total_elevation_m,
             num_points, strava_activity_id, strava_effort_source)
        )
        self._conn.commit()
        return cur.lastrowid

    def update_activity_strava_id(self, activity_id, strava_activity_id,
                                   strava_effort_source="strava_api"):
        try:
            self._conn.execute(
                """UPDATE activities
                   SET strava_activity_id=?, strava_effort_source=?
                   WHERE activity_id=?""",
                (strava_activity_id, strava_effort_source, activity_id)
            )
            self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            logger.warning(f"update_activity_strava_id skipped (activity_id={activity_id}, "
                           f"strava_id={strava_activity_id}): {e}")

    def update_activity_notes(self, activity_id, notes):
        self._conn.execute(
            "UPDATE activities SET notes=? WHERE activity_id=?",
            (notes, activity_id)
        )
        self._conn.commit()

    def update_activity_totals(self, activity_id, total_distance_m, total_elevation_m, num_points=None):
        if num_points is None:
            self._conn.execute(
                """UPDATE activities
                   SET total_distance_m=?, total_elevation_m=?
                   WHERE activity_id=?""",
                (total_distance_m, total_elevation_m, activity_id)
            )
        else:
            self._conn.execute(
                """UPDATE activities
                   SET total_distance_m=?, total_elevation_m=?, num_points=?
                   WHERE activity_id=?""",
                (total_distance_m, total_elevation_m, num_points, activity_id)
            )
        self._conn.commit()

    def update_activity_gpx(self, activity_id, gpx_points_json: str, stream_length: int = None):
        """Salva il tracciato GPX come JSON array [[lat,lng],...] per visualizzazione."""
        self._conn.execute(
            "UPDATE activities SET gpx_points=?, stream_length=? WHERE activity_id=?",
            (gpx_points_json, stream_length, activity_id)
        )
        self._conn.commit()

    # --- Settings ---

    def get_setting(self, key, default=None):
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        self._conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value))
        )
        self._conn.commit()

    def get_all_settings(self):
        rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def update_activity_meta(self, activity_id, **kwargs):
        """Aggiorna i campi metadata opzionali di un'attività."""
        allowed = {"moving_time_s", "avg_heartrate", "avg_watts", "avg_cadence",
                   "calories", "max_heartrate", "activity_name", "gpx_path",
                   "max_cadence", "sigma_heartrate", "sigma_cadence",
                   "total_distance_m", "total_elevation_m"}
        fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self._conn.execute(
            f"UPDATE activities SET {sets} WHERE activity_id=?",
            (*fields.values(), activity_id)
        )
        self._conn.commit()

    def delete_segment(self, segment_id):
        """Elimina un segmento e tutti i suoi effort dal DB."""
        self._conn.execute("DELETE FROM efforts WHERE segment_id=?", (segment_id,))
        self._conn.execute("DELETE FROM segments WHERE segment_id=?", (segment_id,))
        self._conn.commit()

    def cleanup_orphan_segments(self) -> int:
        """
        Rimuove dal DB tutti i segmenti che non hanno effort associati.
        Ritorna il numero di segmenti eliminati.
        """
        # Trova segmenti senza effort
        orphans = self._conn.execute("""
            SELECT s.segment_id FROM segments s
            LEFT JOIN efforts e ON s.segment_id = e.segment_id
            WHERE e.effort_id IS NULL
        """).fetchall()

        count = len(orphans)
        if count > 0:
            self._conn.execute("""
                DELETE FROM segments WHERE segment_id IN (
                    SELECT s.segment_id FROM segments s
                    LEFT JOIN efforts e ON s.segment_id = e.segment_id
                    WHERE e.effort_id IS NULL
                )
            """)
            self._conn.commit()
            logger.info(f"Cleanup: rimossi {count} segmenti orfani")
        return count

    def get_segments_with_efforts_in_bbox(self, lat_min, lat_max, lng_min, lng_max):
        """
        Ritorna solo i segmenti nel bbox che hanno almeno un effort associato.
        Molto più efficiente per il matching storico.
        """
        rows = self._conn.execute("""
            SELECT DISTINCT s.segment_id, s.name, s.source, s.activity_type,
                   s.avg_grade, s.distance, s.elev_difference,
                   s.start_lat, s.start_lng, s.end_lat, s.end_lng, s.polyline
            FROM segments s
            INNER JOIN efforts e ON s.segment_id = e.segment_id
            WHERE s.start_lat BETWEEN ? AND ? AND s.start_lng BETWEEN ? AND ?
        """, (lat_min, lat_max, lng_min, lng_max)).fetchall()
        return [self._row_to_segment(r) for r in rows]

    def delete_activity(self, activity_id: int):
        """Elimina un'attività e tutti i suoi effort e power bests dal DB."""
        self._conn.execute("DELETE FROM power_bests WHERE activity_id=?", (activity_id,))
        self._conn.execute("DELETE FROM efforts WHERE activity_id=?", (activity_id,))
        self._conn.execute("DELETE FROM activities WHERE activity_id=?", (activity_id,))
        self._conn.commit()

    def get_all_activities(self):
        rows = self._conn.execute(
            "SELECT * FROM activities ORDER BY activity_date DESC, imported_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Efforts ---

    def insert_effort(self, effort):
        start_time_s = getattr(effort, 'start_time_s', None)
        if getattr(effort, 'strava_effort_id', None):
            cur = self._conn.execute(
                """INSERT INTO efforts
                   (activity_id, segment_id, strava_effort_id, source,
                    elapsed_seconds, avg_speed_ms, avg_grade_pct,
                    distance_m, elev_gain_m, frechet_distance_m,
                    start_idx, end_idx, start_time_s, average_heartrate)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(strava_effort_id) DO UPDATE SET
                     elapsed_seconds=excluded.elapsed_seconds,
                     avg_speed_ms=excluded.avg_speed_ms,
                     start_idx=excluded.start_idx,
                     start_time_s=excluded.start_time_s,
                     average_heartrate=excluded.average_heartrate""",
                (effort.activity_id, effort.segment_id,
                 effort.strava_effort_id,
                 getattr(effort, "source", "frechet"),
                 effort.elapsed_seconds, effort.avg_speed_ms, effort.avg_grade_pct,
                 effort.distance_m, effort.elev_gain_m, effort.frechet_distance_m,
                 effort.start_idx, effort.end_idx, start_time_s, getattr(effort, 'average_heartrate', None))
            )
        else:
            cur = self._conn.execute(
                """INSERT INTO efforts
                   (activity_id, segment_id, source,
                    elapsed_seconds, avg_speed_ms, avg_grade_pct,
                    distance_m, elev_gain_m, frechet_distance_m,
                    start_idx, end_idx, start_time_s, average_heartrate)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (effort.activity_id, effort.segment_id,
                 getattr(effort, "source", "frechet"),
                 effort.elapsed_seconds, effort.avg_speed_ms, effort.avg_grade_pct,
                 effort.distance_m, effort.elev_gain_m, effort.frechet_distance_m,
                 effort.start_idx, effort.end_idx, start_time_s, getattr(effort, 'average_heartrate', None))
            )
        self._conn.commit()
        return cur.lastrowid

    def delete_efforts_for_activity(self, activity_id):
        self._conn.execute("DELETE FROM efforts WHERE activity_id=?", (activity_id,))
        self._conn.commit()

    def get_efforts_for_segment(self, segment_id):
        rows = self._conn.execute(
            """SELECT e.*, a.filename, a.activity_date
               FROM efforts e JOIN activities a ON a.activity_id=e.activity_id
               WHERE e.segment_id=?
               ORDER BY e.elapsed_seconds ASC""",
            (segment_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_efforts_for_activity(self, activity_id):
        rows = self._conn.execute(
            """SELECT e.*, s.name, s.distance, s.avg_grade, s.polyline, s.source as seg_source
               FROM efforts e JOIN segments s ON s.segment_id=e.segment_id
               WHERE e.activity_id=?
               ORDER BY
                 COALESCE(e.start_time_s, 999999999) ASC,
                 e.effort_id ASC""",
            (activity_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if 'start_time_s' not in d:
                d['start_time_s'] = None
            result.append(d)
        return result

    @staticmethod
    def _row_to_segment(row):
        fields = set(CachedSegment.__dataclass_fields__)
        return CachedSegment(**{k: v for k, v in dict(row).items() if k in fields})

    # --- Power Bests ---

    def save_power_bests(self, activity_id: int, bests: list):
        """
        Salva i power bests per un'attività.
        bests: lista di dict con {interval_minutes, watts, start_s, end_s}
        Sovrascrive eventuali valori esistenti per la stessa attività.
        """
        # Elimina eventuali bests precedenti per questa attività
        self._conn.execute(
            "DELETE FROM power_bests WHERE activity_id=?", (activity_id,)
        )
        for b in bests:
            self._conn.execute(
                """INSERT INTO power_bests
                   (activity_id, interval_minutes, watts, start_s, end_s)
                   VALUES (?, ?, ?, ?, ?)""",
                (activity_id, b["interval_minutes"], b["watts"],
                 b["start_s"], b["end_s"])
            )
        self._conn.commit()

    def get_power_bests_for_activity(self, activity_id: int):
        """Restituisce i power bests salvati per un'attività."""
        rows = self._conn.execute(
            """SELECT * FROM power_bests
               WHERE activity_id=?
               ORDER BY interval_minutes ASC""",
            (activity_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_power_bests_rankings(self, interval_minutes: int = None):
        """
        Restituisce la classifica dei power bests per ogni intervallo.
        Se interval_minutes è specificato, filtra solo quell'intervallo.
        """
        where = "WHERE pb.interval_minutes=?" if interval_minutes else ""
        params = (interval_minutes,) if interval_minutes else ()
        rows = self._conn.execute(
            f"""SELECT pb.*, a.filename, a.activity_date, a.activity_name
               FROM power_bests pb
               JOIN activities a ON a.activity_id = pb.activity_id
               {where}
               ORDER BY pb.interval_minutes ASC, pb.watts DESC""",
            params
        ).fetchall()
        return [dict(r) for r in rows]

    def get_power_bests_with_rank(self, activity_id: int):
        """
        Restituisce i power bests di un'attività con il rank rispetto a tutte le altre.
        """
        # Prima ottieni i bests dell'attività
        bests = self.get_power_bests_for_activity(activity_id)
        result = []
        for b in bests:
            # Conta quanti sono migliori (più watt) per lo stesso intervallo
            row = self._conn.execute(
                """SELECT COUNT(*) as better_count,
                          (SELECT MAX(watts) FROM power_bests WHERE interval_minutes=?) as best_watts
                   FROM power_bests
                   WHERE interval_minutes=? AND watts > ?""",
                (b["interval_minutes"], b["interval_minutes"], b["watts"])
            ).fetchone()
            better_count = (row["better_count"] or 0) if row else 0
            rank = better_count + 1
            best_watts = (row["best_watts"] or b["watts"]) if row else b["watts"]
            # Conta totale per quell'intervallo
            total_row = self._conn.execute(
                "SELECT COUNT(*) as total FROM power_bests WHERE interval_minutes=?",
                (b["interval_minutes"],)
            ).fetchone()
            total = total_row["total"] if total_row else 1
            result.append({
                **b,
                "rank": rank,
                "total": total,
                "best_watts": best_watts,
                "is_pr": rank == 1
            })
        return result

    def delete_power_bests_for_activity(self, activity_id: int):
        """Elimina i power bests di un'attività."""
        self._conn.execute(
            "DELETE FROM power_bests WHERE activity_id=?", (activity_id,)
        )
        self._conn.commit()

    def delete_effort(self, effort_id: int):
        """Elimina un singolo effort dal DB."""
        self._conn.execute("DELETE FROM efforts WHERE effort_id=?", (effort_id,))
        self._conn.commit()
