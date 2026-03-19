"""
gui/server.py — Flask backend per la GUI stravish

Endpoints:
  GET  /api/activities              lista attività importate
  GET  /api/activities/<id>/efforts effort di una attività
  GET  /api/segments                lista segmenti in cache
  GET  /api/segments/<id>/efforts   storico effort per segmento
  POST /api/import                  importa GPX (multipart)
  GET  /api/status                  stato DB
"""

import sys
import os
import re
import logging
import threading
import webbrowser
import yaml

from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, abort

# sys.path — funziona sia da gui/ che dalla root
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("SILENCE_TOKEN_WARNINGS", "true")

import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="stravalib")
logging.getLogger("stravalib.util.limiter").setLevel(logging.ERROR)
logging.getLogger("py.warnings").setLevel(logging.ERROR)

from cache.db import SegmentCache
from strava.auth import StravaAuth

logger = logging.getLogger(__name__)


def _idx_overlap_ratio(a_start, a_end, b_start, b_end):
    try:
        a0, a1 = int(a_start), int(a_end)
        b0, b1 = int(b_start), int(b_end)
    except Exception:
        return 0.0
    if a1 < a0:
        a0, a1 = a1, a0
    if b1 < b0:
        b0, b1 = b1, b0
    inter = min(a1, b1) - max(a0, b0)
    if inter <= 0:
        return 0.0
    lena = max(1, a1 - a0)
    lenb = max(1, b1 - b0)
    return inter / float(min(lena, lenb))


def _effort_is_equivalent(a, b):
    # Se sono effort su segmenti DIVERSI ma entrambi ufficiali da Strava API,
    # non deduplichiamoli: l'utente vuole vedere tutti i cloni/varianti di segmenti riconosciuti da Strava.
    if a.get("segment_id") != b.get("segment_id"):
        if a.get("source") == "strava_api" and b.get("source") == "strava_api":
            return False

    ov = _idx_overlap_ratio(a.get("start_idx"), a.get("end_idx"), b.get("start_idx"), b.get("end_idx"))
    if ov < 0.85:
        return False
    ad = float(a.get("distance_m") or 0.0)
    bd = float(b.get("distance_m") or 0.0)
    if ad > 0 and bd > 0:
        dist_delta = abs(ad - bd) / max(ad, bd)
        if dist_delta > 0.35:
            return False
    ae = float(a.get("elapsed_seconds") or 0.0)
    be = float(b.get("elapsed_seconds") or 0.0)
    if ae > 0 and be > 0:
        t_delta = abs(ae - be) / max(ae, be)
        if t_delta > 0.50:
            return False
    return True


def _source_rank(source):
    # Preferenza: Strava API > historical > frechet > auto
    return {
        "strava_api": 4,
        "historical": 3,
        "frechet": 2,
        "auto": 1,
    }.get(source or "", 0)


def _get_effective_efforts_for_activity(activity_id):
    """Restituisce tutto il raw DB degli effort associati, rimuovendo le dedupliche."""
    raw = get_cache().get_efforts_for_activity(activity_id)
    if not raw:
        return []
    
    # Ordinamento standard come richiesto dalla UI per default
    raw.sort(key=lambda e: (float(e.get("start_time_s") or 9e18), int(e.get("effort_id") or 0)))
    return raw


def _count_efforts_with_avg_heartrate(activity_id: int) -> int:
    row = get_cache()._conn.execute(
        """SELECT COUNT(*) AS c
           FROM efforts
           WHERE activity_id=? AND average_heartrate IS NOT NULL""",
        (activity_id,),
    ).fetchone()
    return int(row["c"] if row else 0)

# ── Log stream per SSE ────────────────────────────────────────────
import queue as _queue
_log_queue = _queue.Queue(maxsize=500)
_ORIGINAL_STDERR = sys.stderr

class _QueueHandler(logging.Handler):
    def emit(self, record):
        try:
            _log_queue.put_nowait({
                "level": record.levelname,
                "msg":   self.format(record),
                "ts":    record.created,
            })
        except _queue.Full:
            pass

_qh = _QueueHandler()
_qh.setFormatter(logging.Formatter("%(name)s: %(message)s"))
_qh.setLevel(logging.INFO)


def _configure_logging(verbose=False):
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Handler SSE: sempre attivo per il viewer
    if not any(isinstance(h, _QueueHandler) for h in root_logger.handlers):
        root_logger.addHandler(_qh)

    # Handler console: solo in --verbose
    has_console = any(getattr(h, "_stravish_console", False) for h in root_logger.handlers)
    if verbose and not has_console:
        console = logging.StreamHandler(_ORIGINAL_STDERR)
        console._stravish_console = True
        console.setLevel(logging.DEBUG)
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s %(filename)s:%(lineno)d: %(message)s"))
        root_logger.addHandler(console)

# Redirigi logger specifici
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("werkzeug").addHandler(_qh)
logging.getLogger("segmentizer.pipeline").setLevel(logging.INFO)

# Opzionale: cattura stampe su stderr standard (es. eccezioni non gestite nel thread)
class StderrToLogger(object):
    def __init__(self, logger_obj, level):
        self.logger_obj = logger_obj
        self.level = level
    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger_obj.log(self.level, line.rstrip())
    def flush(self):
        pass

import sys
sys.stderr = StderrToLogger(logging.getLogger("STDERR"), logging.ERROR)


def _fetch_activity(client, activity_id: int, include_all_efforts: bool = True, context: str = ""):
    ctx = f" ({context})" if context else ""
    logger.info(
        "Strava get_activity(%s, include_all_efforts=%s)%s",
        int(activity_id),
        include_all_efforts,
        ctx,
    )
    return client.get_activity(int(activity_id), include_all_efforts=include_all_efforts)


def _get_fresh_client():
    """Crea un client stravalib con token sempre aggiornato."""
    from strava.auth import StravaAuth
    from stravalib.client import Client
    from stravalib.util.limiter import DefaultRateLimiter
    strava_cfg = _config.get("strava", {})
    auth = StravaAuth(strava_cfg.get("client_id",""), strava_cfg.get("client_secret",""))
    token = auth.get_valid_access_token()
    return Client(access_token=token, rate_limiter=DefaultRateLimiter(priority="medium"))


def _save_strava_meta(cache, activity_id, activity):
    """Salva i metadata biometrici di un'attività Strava nel DB."""
    def _f(val):
        try: return float(val) if val is not None else None
        except: return None
    mt = getattr(activity, 'moving_time', None)
    dist = _f(getattr(activity, 'distance', None))
    elev = _f(getattr(activity, 'total_elevation_gain', None))
    cache.update_activity_meta(
        activity_id,
        activity_name     = getattr(activity, 'name', None),
        moving_time_s     = _to_seconds(mt) if mt else None,
        avg_heartrate     = _f(getattr(activity, 'average_heartrate', None)),
        max_heartrate     = _f(getattr(activity, 'max_heartrate', None)),
        avg_watts         = _f(getattr(activity, 'average_watts', None)),
        avg_cadence       = _f(getattr(activity, 'average_cadence', None)),
        max_cadence       = _f(getattr(activity, 'max_cadence', None)),
        calories          = getattr(activity, 'calories', None),
        total_distance_m  = dist,
        total_elevation_m = elev,
    )


def _enrich_effort(e):
    """Calcola elev_gain_m stimato e VAM, modifica il dict in-place."""
    elev = e.get("elev_gain_m") or 0.0
    if elev == 0.0 and e.get("avg_grade_pct") and e.get("distance_m"):
        elev = max(0.0, e["avg_grade_pct"] / 100.0 * e["distance_m"])
        e["elev_gain_m"] = elev
    ts   = e.get("elapsed_seconds") or 0
    dist = e.get("distance_m") or 0
    if elev > 0 and ts > 0 and dist >= 600:
        vam = elev / ts * 3600
        e["vam"] = round(vam) if vam >= 600 else None
    else:
        e["vam"] = None


def _to_seconds(duration) -> int:
    """Converte stravalib Duration o timedelta in secondi interi."""
    if duration is None:
        return 0
    if hasattr(duration, 'total_seconds'):
        return int(duration.total_seconds())
    return int(duration)  # stravalib Duration è già in secondi


def _persist_gpx_payload(filename_hint: str, payload: bytes) -> str:
    """Salva un GPX in cache/imported_gpx e ritorna path persistente."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename_hint or "activity")
    if not safe.lower().endswith(".gpx"):
        safe += ".gpx"
    root = Path(_config.get("cache", {}).get("db_path", "./cache/segments.db")).parent
    out_dir = root / "imported_gpx"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / safe
    idx = 1
    while target.exists():
        target = out_dir / f"{Path(safe).stem}_{idx}.gpx"
        idx += 1
    target.write_bytes(payload)
    return str(target)

app = Flask(__name__, static_folder=str(Path(__file__).parent), static_url_path="")

_cache = None
_config = None


def get_cache():
    global _cache
    if _cache is None:
        _cache = SegmentCache(_config["cache"]["db_path"])
        # WAL mode: evita lock su macOS con accessi concorrenti Flask
        _cache._conn.execute("PRAGMA journal_mode=WAL")
        _cache._conn.execute("PRAGMA synchronous=NORMAL")
    return _cache


# ------------------------------------------------------------------ #
# Static — serve index.html
# ------------------------------------------------------------------ #

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "viewer.html")


# ------------------------------------------------------------------ #
# API
# ------------------------------------------------------------------ #

@app.route("/api/status")
def api_status():
    c = get_cache()
    conn = c._conn
    return jsonify({
        "segments": conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0],
        "activities": conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0],
        "efforts": conn.execute("SELECT COUNT(*) FROM efforts").fetchone()[0],
        "db_path": str(c.db_path),
    })


@app.route("/api/cleanup-orphan-segments", methods=["POST"])
def api_cleanup_orphan_segments():
    """
    Rimuove dal DB tutti i segmenti che non hanno effort associati.
    Utile per velocizzare il matching storico.
    """
    count = get_cache().cleanup_orphan_segments()
    return jsonify({
        "removed": count,
        "message": f"Rimossi {count} segmenti orfani"
    })


@app.route("/api/activities")
def api_activities():
    activities = get_cache().get_all_activities()
    for a in activities:
        aid = a["activity_id"]
        effective = _get_effective_efforts_for_activity(aid)
        a["effort_count"] = len(effective)
        a["strava_effort_count"] = sum(1 for e in effective if e.get("source") == "strava_api")
        a["auto_effort_count"] = sum(1 for e in effective if e.get("source") == "auto")
        a["historical_effort_count"] = sum(1 for e in effective if e.get("source") == "historical")
    return jsonify(activities)


@app.route("/api/activities/<int:activity_id>/efforts")
def api_activity_efforts(activity_id):
    efforts = _get_effective_efforts_for_activity(activity_id)
    row = get_cache()._conn.execute(
        "SELECT num_points FROM activities WHERE activity_id=?", (activity_id,)
    ).fetchone()
    total_points = row["num_points"] if row else None
    for e in efforts:
        if total_points:
            e["total_points"] = total_points
        _enrich_effort(e)
    return jsonify(efforts)


@app.route("/api/segments")
def api_segments():
    segs = get_cache().get_all_segments()
    c = get_cache()._conn
    # Conta effort per segmento in un colpo solo
    effort_counts = {
        r[0]: r[1] for r in c.execute(
            "SELECT segment_id, COUNT(*) FROM efforts GROUP BY segment_id"
        ).fetchall()
    }
    result = []
    for s in segs:
        result.append({
            "segment_id": s.segment_id,
            "name": s.name,
            "source": s.source,
            "distance": s.distance,
            "avg_grade": s.avg_grade,
            "elev_difference": s.elev_difference,
            "start_lat": s.start_lat,
            "start_lng": s.start_lng,
            "end_lat": s.end_lat,
            "end_lng": s.end_lng,
            "polyline": s.polyline,
            "effort_count": effort_counts.get(s.segment_id, 0),
        })
    # Ordina: prima i percorsi (effort_count > 0), poi per nome
    result.sort(key=lambda s: (-s["effort_count"], s["name"].lower()))
    return jsonify(result)


@app.route("/api/logs/stream")
def api_logs_stream():
    """SSE endpoint — streamma i log in tempo reale."""
    def generate():
        yield "retry: 1000\n\n"
        while True:
            try:
                entry = _log_queue.get(timeout=15)
                level = entry["level"]
                msg   = entry["msg"].replace("\n", " ↵ ")
                import datetime, json as _json
                ts = datetime.datetime.fromtimestamp(entry["ts"]).strftime("%H:%M:%S")
                data = _json.dumps({"level": level, "msg": msg, "ts": ts})
                yield f"data: {data}\n\n"
            except _queue.Empty:
                yield ":\n\n"  # keepalive
    from flask import Response, stream_with_context
    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/strava/rate-limit")
def api_rate_limit():
    """Restituisce lo stato del rate limit Strava."""
    try:
        from strava.auth import StravaAuth
        from stravalib.client import Client
        from stravalib.util.limiter import DefaultRateLimiter
        strava_cfg = _config.get("strava", {})
        auth = StravaAuth(strava_cfg.get("client_id",""), strava_cfg.get("client_secret",""))
        token = auth.get_valid_access_token()
        if not token:
            return jsonify({"error": "no token"}), 401
        client = Client(access_token=token, rate_limiter=DefaultRateLimiter(priority="medium"))
        rules = []
        for rule in client.protocol.rate_limiter.rules:
            usage = getattr(rule, 'usage', None)
            limit = getattr(rule, 'limit', None)
            if usage is not None and limit:
                rules.append({"usage": int(usage), "limit": int(limit)})
        return jsonify({"rules": rules})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(get_cache().get_all_settings())

@app.route("/api/settings", methods=["POST"])
def api_set_settings():
    data = request.get_json(force=True)
    for k, v in data.items():
        get_cache().set_setting(k, v)
    # Invalida power bests (dipendono da peso, crr, cda)
    get_cache()._conn.execute("DELETE FROM power_bests")
    get_cache()._conn.commit()
    return jsonify({"ok": True})


@app.route("/api/segments/<path:segment_id>", methods=["DELETE"])
def api_delete_segment(segment_id):
    try: segment_id = int(segment_id)
    except ValueError: pass
    get_cache().delete_segment(segment_id)
    return jsonify({"ok": True})


@app.route("/api/activities/<int:activity_id>", methods=["DELETE"])
def api_delete_activity(activity_id):
    get_cache().delete_activity(activity_id)
    return jsonify({"ok": True})


@app.route("/api/activities/<int:activity_id>/summary")
def api_activity_summary(activity_id):
    """Restituisce i dati summary di un'attività (meta Strava + estrazione GPX estensioni)."""
    row = get_cache()._conn.execute(
        "SELECT * FROM activities WHERE activity_id=?", (activity_id,)
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    data = dict(row)
    data.pop("gpx_points", None)
    # effort_count
    ec = get_cache()._conn.execute(
        "SELECT COUNT(*) FROM efforts WHERE activity_id=?", (activity_id,)
    ).fetchone()
    data["effort_count"] = ec[0] if ec else 0

    # Stima watt se non rilevati
    if not data.get("avg_watts") and data.get("total_distance_m") and data.get("moving_time_s") and data.get("total_elevation_m"):
        try:
            import math
            s = get_cache().get_all_settings()
            m_rider = float(s.get("weight_kg", 75))
            m_bike  = float(s.get("bike_kg", 10))
            crr     = float(s.get("crr", 0.005))
            cda     = float(s.get("cda", 0.35))
            m_tot   = m_rider + m_bike
            g       = 9.81
            rho     = 1.225
            dist    = data["total_distance_m"]
            t       = data["moving_time_s"]
            elev    = data["total_elevation_m"]
            v       = dist / t
            slope   = elev / dist
            f_grav  = m_tot * g * math.sin(math.atan(slope))
            f_roll  = m_tot * g * math.cos(math.atan(slope)) * crr
            f_aero  = 0.5 * rho * cda * v ** 2
            p_est   = max(0, (f_grav + f_roll + f_aero) * v)
            data["avg_watts_estimated"] = round(p_est)
        except Exception as ex:
            logger.debug(f"Stima watt fallita: {ex}")

    # Calorie: da watt reali o stimati × tempo (efficienza metabolica ciclismo ~24%)
    if not data.get("calories") and data.get("moving_time_s"):
        watts = data.get("avg_watts") or data.get("avg_watts_estimated")
        if watts:
            data["calories"] = round(watts * data["moving_time_s"] / (4184 * 0.24))
    return jsonify(data)


@app.route("/api/activities/<int:activity_id>/medals")
def api_activity_medals(activity_id):
    """Restituisce le medaglie (top-3 per segmento) per questa attività."""
    cache = get_cache()
    efforts = _get_effective_efforts_for_activity(activity_id)
    medals = []
    for effort in efforts:
        seg_id = effort["segment_id"]
        seg_name = effort.get("name") or f"Segmento {seg_id}"
        elapsed = effort.get("elapsed_seconds") or 0
        if not elapsed:
            continue
        # Tutti gli effort storici per questo segmento, ordinati per tempo
        all_efforts = cache._conn.execute(
            """SELECT elapsed_seconds, activity_id FROM efforts
               WHERE segment_id=? AND elapsed_seconds > 0
               ORDER BY elapsed_seconds ASC""",
            (seg_id,)
        ).fetchall()
        if not all_efforts:
            continue
        # Trova posizione dell'effort corrente (deduplicato per attività — prendi il migliore)
        seen = {}
        ranked = []
        for r in all_efforts:
            aid = r["activity_id"]
            if aid not in seen:
                seen[aid] = r["elapsed_seconds"]
                ranked.append((r["elapsed_seconds"], aid))
        # Rank dell'attività corrente
        best_for_activity = min(
            (e["elapsed_seconds"] for e in efforts
             if e["segment_id"] == seg_id and e.get("elapsed_seconds")),
            default=None
        )
        if best_for_activity is None:
            continue
        rank = next((i+1 for i, (t, _) in enumerate(ranked) if t >= best_for_activity), len(ranked))
        if rank <= 3:
            medals.append({
                "segment_id": seg_id,
                "name": seg_name,
                "rank": rank,
                "elapsed_seconds": best_for_activity,
                "total": len(ranked),
            })
    medals.sort(key=lambda m: m["rank"])
    return jsonify(medals)


@app.route("/api/activities/<int:activity_id>/refresh-meta", methods=["POST"])
def api_refresh_meta(activity_id):
    """Aggiorna i metadata biometrici da Strava per questa attività."""
    row = get_cache()._conn.execute(
        "SELECT strava_activity_id FROM activities WHERE activity_id=?", (activity_id,)
    ).fetchone()
    if not row or not row["strava_activity_id"]:
        return jsonify({"error": "Nessun strava_activity_id associato"}), 400
    strava_id = row["strava_activity_id"]
    try:
        strava = StravaClient(_config, get_cache())
        act_meta = _fetch_activity(_get_fresh_client(), int(strava_id), context="refresh-meta")
        _save_strava_meta(get_cache(), activity_id, act_meta)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/activities/<int:activity_id>/refresh", methods=["POST"])
def api_refresh_activity(activity_id):
    """Ricalcola aggregati/segmentizzazione da GPX locale o upload, poi aggiorna Strava."""
    from segmentizer.pipeline import Segmentizer
    from strava.client import StravaClient
    from strava.efforts import fetch_and_store_strava_efforts

    activity_type = request.form.get("activity_type", "cycling") if request.form else "cycling"

    row = get_cache()._conn.execute(
        """SELECT activity_id, filename, strava_activity_id, gpx_path
           FROM activities WHERE activity_id=?""",
        (activity_id,)
    ).fetchone()
    if not row:
        return jsonify({"error": "Attività non trovata"}), 404

    gpx_path = row["gpx_path"]

    if "gpx" in request.files:
        f = request.files["gpx"]
        payload = f.read()
        safe_name = f.filename if f.filename else row["filename"]
        gpx_path = _persist_gpx_payload(safe_name, payload)
        
        get_cache()._conn.execute(
            "UPDATE activities SET gpx_path=? WHERE activity_id=?", 
            (str(gpx_path), activity_id)
        )
        get_cache()._conn.commit()

    if not gpx_path or not Path(gpx_path).exists():
        return jsonify({
            "error": "GPX sorgente non disponibile per refresh. Allega il file GPX dell'attività."
        }), 400

    # Reset effort esistenti per ricalcolo pulito
    get_cache().delete_efforts_for_activity(activity_id)

    try:
        seg = Segmentizer(config=_config)
        r = seg.process(
            gpx_path,
            activity_type=activity_type,
            filename_override=row["filename"],
            strava_activity_id=row["strava_activity_id"],
        )

        strava_saved = 0
        if row["strava_activity_id"]:
            strava = StravaClient(_config, get_cache())
            strava_saved = fetch_and_store_strava_efforts(
                strava, get_cache(), activity_id, int(row["strava_activity_id"])
            )
            try:
                act_meta = _fetch_activity(_get_fresh_client(), int(row["strava_activity_id"]), context="refresh-activity")
                _save_strava_meta(get_cache(), activity_id, act_meta)
            except Exception as ex:
                logger.warning(f"refresh meta Strava fallito: {ex}")

        return jsonify({
            "ok": True,
            "activity_id": activity_id,
            "segments_matched": len(r.get("segments_matched", [])),
            "strava_efforts": strava_saved,
            "efforts_with_avg_heartrate": _count_efforts_with_avg_heartrate(activity_id),
            "gpx_stats": r.get("gpx_stats", {}),
        })
    except Exception as e:
        logger.error("api_refresh_activity error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/efforts/<int:effort_id>", methods=["DELETE"])
def api_delete_effort(effort_id):
    get_cache()._conn.execute("DELETE FROM efforts WHERE effort_id=?", (effort_id,))
    get_cache()._conn.commit()
    return jsonify({"ok": True})


@app.route("/api/segments/<path:segment_id>/efforts")
def api_segment_efforts(segment_id):
    try: segment_id = int(segment_id)
    except ValueError: pass
    efforts = get_cache().get_efforts_for_segment(segment_id)
    if efforts:
        best_time = efforts[0]["elapsed_seconds"]
        for i, e in enumerate(efforts):
            e["rank"] = i + 1
            e["delta_from_best"] = e["elapsed_seconds"] - best_time
            e["avg_speed_kmh"] = (e["avg_speed_ms"] * 3.6) if e["avg_speed_ms"] else 0
            _enrich_effort(e)
    return jsonify(efforts)


@app.route("/api/activities/<int:activity_id>/strava-efforts", methods=["POST"])
def api_fetch_strava_efforts(activity_id):
    """Fetcha gli effort da Strava API per questa attività."""
    data = request.get_json(force=True)
    strava_activity_id = data.get("strava_activity_id")
    if not strava_activity_id:
        return jsonify({"error": "strava_activity_id mancante"}), 400

    from strava.client import StravaClient
    from strava.efforts import fetch_and_store_strava_efforts

    strava = StravaClient(_config, get_cache())
    try:
        saved = fetch_and_store_strava_efforts(strava, get_cache(),
                                                activity_id, int(strava_activity_id))
        # Aggiorna strava_effort_source nel DB — essenziale per il colore pulsante
        get_cache().update_activity_strava_id(activity_id, int(strava_activity_id), "strava_api")
        try:
            act_meta = _fetch_activity(_get_fresh_client(), int(strava_activity_id), context="fetch-strava-efforts")
            _save_strava_meta(get_cache(), activity_id, act_meta)
        except Exception as ex:
            logger.warning(f"Meta Strava non disponibili: {ex}")
                # Leggi rate limit aggiornato dopo il fetch
        rl = {}
        try:
            for rule in (strava._client.protocol.rate_limiter.rules if strava._client else []):
                usage = getattr(rule, 'usage', None)
                limit = getattr(rule, 'limit', None)
                if usage is not None and limit:
                    rl = {"usage": int(usage), "limit": int(limit)}
                    break
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "saved": saved,
            "efforts_with_avg_heartrate": _count_efforts_with_avg_heartrate(activity_id),
            "rate_limit": rl,
        })
    except Exception as e:
        import traceback
        err_detail = traceback.format_exc()
        err_str = str(e)
        if "429" in err_str or "Rate Limit" in err_str or "Too Many Requests" in err_str:
            if "read rate limit" in err_str.lower() or "short" in err_str.lower():
                logger.warning("⏱ Rate limit breve Strava (100/15min) — aspetta 15 minuti")
                return jsonify({"error": "⏱ Rate limit raggiunto (100/15min) — riprova tra 15 minuti"}), 429
            else:
                logger.warning("⏱ Rate limit giornaliero Strava (1000/giorno) — aspetta mezzanotte UTC")
                return jsonify({"error": "⏱ Rate limit giornaliero esaurito — riprova domani"}), 429
        logger.error("fetch_strava_efforts ERROR:\n%s", err_detail)
        return jsonify({"error": err_str, "detail": err_detail}), 500


@app.route("/api/strava/automatch", methods=["POST"])
def api_strava_automatch():
    """
    Tenta il match automatico per tutte le attività senza strava_activity_id.
    Chiama get_activities() una volta sola e aggiorna il DB per ogni match trovato.
    """
    from stravalib.client import Client
    from stravalib.util.limiter import DefaultRateLimiter
    import os, re
    os.environ.setdefault("SILENCE_TOKEN_WARNINGS", "true")

    auth = StravaAuth(
        _config["strava"].get("client_id", ""),
        _config["strava"].get("client_secret", ""),
    )
    token = auth.get_valid_access_token()
    if not token:
        return jsonify({"matched": 0, "error": "non autenticato"})

    def _norm(s):
        s = (s or "").lower().strip()
        s = re.sub(r"\.gpx$", "", s)
        s = re.sub(r"[^a-z0-9]", "", s)
        return s

    # Attività locali senza strava_activity_id
    unlinked = [
        a for a in get_cache().get_all_activities()
        if not a.get("strava_activity_id")
    ]
    if not unlinked:
        return jsonify({"matched": 0, "already_linked": True})

    # Costruisci indice norm→strava_id dalla lista Strava
    try:
        client = Client(access_token=token, rate_limiter=DefaultRateLimiter(priority="medium"))
        strava_index = {}
        for act in client.get_activities():
            n = _norm(act.name)
            if n and n not in strava_index:
                strava_index[n] = act.id
        # Aggiorna cache match
        api_strava_match_activity._cache = None
    except Exception as e:
        logger.error(f"automatch get_activities error: {e}")
        return jsonify({"matched": 0, "error": str(e)}), 500

    # Strava IDs già usati da altre attività locali — non riusare
    already_linked = {
        a["strava_activity_id"]
        for a in get_cache().get_all_activities()
        if a.get("strava_activity_id")
    }

    matched = 0
    for a in unlinked:
        key = _norm(a["filename"])
        strava_id = strava_index.get(key)
        if strava_id and strava_id not in already_linked:
            get_cache().update_activity_strava_id(a["activity_id"], strava_id, "local")
            already_linked.add(strava_id)
            matched += 1
            logger.info(f"Automatch: {a['filename']} → Strava {strava_id}")
        elif strava_id and strava_id in already_linked:
            # Trova quale attività ha già quel strava_id
            owner = next((x for x in get_cache().get_all_activities()
                          if x.get("strava_activity_id") == strava_id), None)
            owner_name = owner["filename"] if owner else "?"
            logger.warning(
                f"Automatch skip: {a['filename']} → Strava {strava_id} "
                f"già agganciato a '{owner_name}' (activity_id={owner['activity_id'] if owner else '?'})"
            )

    return jsonify({"matched": matched, "total_unlinked": len(unlinked)})


@app.route("/api/strava/match-activity", methods=["POST"])
def api_strava_match_activity():
    """
    Cerca tra le attività Strava quella il cui nome corrisponde al filename GPX.
    Body: { filename: "IpBike_67.gpx" }
    Risposta: { strava_id: 1234567890, name: "...", start_date: "..." } o { strava_id: null }
    """
    from stravalib.client import Client
    from stravalib.util.limiter import DefaultRateLimiter
    import os
    os.environ.setdefault("SILENCE_TOKEN_WARNINGS", "true")

    data = request.get_json(force=True)
    filename = data.get("filename", "")
    if not filename:
        return jsonify({"strava_id": None}), 400

    auth = StravaAuth(
        _config["strava"].get("client_id", ""),
        _config["strava"].get("client_secret", ""),
    )
    token = auth.get_valid_access_token()
    if not token:
        return jsonify({"strava_id": None, "error": "non autenticato"}), 401

    # Normalizza: rimuovi estensione e caratteri speciali per confronto
    def _norm(s):
        import re
        s = s.lower().strip()
        s = re.sub(r'\.gpx$', '', s)
        s = re.sub(r'[^a-z0-9]', '', s)
        return s

    needle = _norm(filename)

    try:
        client = Client(access_token=token, rate_limiter=DefaultRateLimiter(priority="medium"))

        # Usa la cache in-memory se disponibile (evita N chiamate in batch import)
        if not hasattr(api_strava_match_activity, '_cache') or \
           api_strava_match_activity._cache is None:
            api_strava_match_activity._cache = [
                {"id": act.id, "name": act.name,
                 "norm": _norm(act.name or ""),
                 "start_date": act.start_date.strftime("%Y-%m-%dT%H:%M:%S")
                               if act.start_date else None,
                 "distance_m": float(act.distance or 0)}
                for act in client.get_activities()
            ]

        for act in api_strava_match_activity._cache:
            if act["norm"] == needle:
                return jsonify({
                    "strava_id": act["id"],
                    "name": act["name"],
                    "start_date": act["start_date"],
                    "distance_m": act["distance_m"],
                })
    except Exception as e:
        logger.warning(f"strava match-activity error: {e}")
        return jsonify({"strava_id": None, "error": str(e)}), 500

    return jsonify({"strava_id": None})


@app.route("/api/activities/<int:activity_id>/gpx-track")
def api_gpx_track(activity_id):
    """
    Restituisce il tracciato come [[lat,lng],...].
    Se non presente nel DB, lo fetcha dagli stream Strava e lo cacha.
    """
    import json
    row = get_cache()._conn.execute(
        "SELECT gpx_points, strava_activity_id FROM activities WHERE activity_id=?",
        (activity_id,)
    ).fetchone()
    if not row:
        return jsonify([])

    if row["gpx_points"]:
        sl = get_cache()._conn.execute(
            "SELECT stream_length FROM activities WHERE activity_id=?", (activity_id,)
        ).fetchone()
        return jsonify({
            "track": json.loads(row["gpx_points"]),
            "stream_length": sl["stream_length"] if sl else None
        })

    # Nessun tracciato in cache — prova a recuperarlo dagli stream Strava
    strava_id = row["strava_activity_id"]
    if not strava_id:
        return jsonify([])

    try:
        from stravalib.client import Client
        from stravalib.util.limiter import DefaultRateLimiter
        import os
        os.environ.setdefault("SILENCE_TOKEN_WARNINGS", "true")

        auth = StravaAuth(
            _config["strava"].get("client_id", ""),
            _config["strava"].get("client_secret", ""),
        )
        token = auth.get_valid_access_token()
        if not token:
            return jsonify([])

        client = Client(access_token=token, rate_limiter=DefaultRateLimiter(priority="medium"))
        streams = client.get_activity_streams(strava_id, types=["latlng"], resolution="medium")
        latlng_s = streams.get("latlng")
        if not latlng_s or not latlng_s.data:
            return jsonify([])

        # Decima a max 500 punti
        pts = latlng_s.data
        step = max(1, len(pts) // 500)
        track = [[round(p[0], 6), round(p[1], 6)] for p in pts[::step]]
        track_json = json.dumps(track)

        # Cacha nel DB per le prossime richieste
        get_cache().update_activity_gpx(activity_id, track_json, len(pts))
        logger.info(f"GPX track fetchato da Strava per activity {activity_id} ({len(track)} pts, stream={len(pts)})")
        return jsonify({"track": track, "stream_length": len(pts)})

    except Exception as e:
        logger.warning(f"gpx-track fallback Strava fallito: {e}")
        return jsonify([])


@app.route("/api/activities/<int:activity_id>/notes", methods=["PATCH"])
def api_activity_notes(activity_id):
    data = request.get_json(force=True)
    notes = data.get("notes", "")
    get_cache().update_activity_notes(activity_id, notes)
    return jsonify({"ok": True})


@app.route("/api/activities/<int:activity_id>/rename", methods=["PATCH"])
def api_activity_rename(activity_id):
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Nome non valido"}), 400
    get_cache().update_activity_meta(activity_id, activity_name=name)
    return jsonify({"ok": True})


@app.route("/api/activities/<int:activity_id>/power-bests")
def api_activity_power_bests(activity_id):
    """
    Calcola i picchi di potenza media su intervalli predefiniti (sliding window).
    Funziona solo con GPX locale (non import da Strava senza GPX).

    Intervalli: 5, 10, 15, 20, 25, 30, 40, 45, 55, 60 minuti.
    Per ogni intervallo restituisce:
      - watts: potenza media massima
      - start_s: secondo di inizio della finestra
      - end_s: secondo di fine della finestra
    """
    import math

    row = get_cache()._conn.execute(
        "SELECT gpx_path FROM activities WHERE activity_id=?", (activity_id,)
    ).fetchone()
    if not row:
        return jsonify({"error": "Attività non trovata"}), 404

    gpx_path = row["gpx_path"]
    if not gpx_path or not Path(gpx_path).exists():
        return jsonify({"error": "GPX non disponibile", "bests": []})

    # Leggi impostazioni utente per il modello fisico
    settings = get_cache().get_all_settings()
    m_rider = float(settings.get("weight_kg", 75))
    m_bike  = float(settings.get("bike_kg", 10))
    crr     = float(settings.get("crr", 0.005))
    cda     = float(settings.get("cda", 0.32))
    m_tot   = m_rider + m_bike
    g       = 9.81
    rho     = 1.225

    # Parsing GPX
    try:
        from utils.gpx_utils import parse_gpx_points, compute_distances
        points = parse_gpx_points(gpx_path)
        if len(points) < 10:
            return jsonify({"error": "GPX troppo corto", "bests": []})
        points = compute_distances(points)
    except Exception as ex:
        logger.warning(f"Parsing GPX fallito per power-bests: {ex}")
        return jsonify({"error": str(ex), "bests": []})

    # Calcola timestamp in secondi dall'inizio
    t0 = points[0]["time"]
    if t0 is None:
        return jsonify({"error": "GPX senza timestamp", "bests": []})

    for p in points:
        if p["time"]:
            p["t_s"] = (p["time"] - t0).total_seconds()
        else:
            p["t_s"] = None

    # Rimuovi punti senza timestamp
    points = [p for p in points if p["t_s"] is not None]
    if len(points) < 10:
        return jsonify({"error": "GPX con pochi punti validi", "bests": []})

    # ── Outlier detection MAD-based sulle velocità ────────────────
    # Calcola tutte le velocità punto-punto valide
    import statistics as _stats
    raw_speeds = []
    for i in range(1, len(points)):
        dt = points[i]["t_s"] - points[i-1]["t_s"]
        dd = points[i]["dist_from_start_m"] - points[i-1]["dist_from_start_m"]
        if dt >= 1.0 and dd > 0:
            raw_speeds.append(dd / dt)

    if not raw_speeds:
        return jsonify({"error": "Nessun segmento valido", "bests": []})

    # Soglia: mediana + 6 * MAD (robusto contro GPS glitch)
    v_median = _stats.median(raw_speeds)
    v_mad = _stats.median([abs(v - v_median) for v in raw_speeds])
    v_threshold = v_median + 6.0 * max(v_mad, 0.5)

    MAX_SLOPE = 0.35        # 35%

    # Calcola potenza istantanea — outlier di velocità SCARTATI, non corretti
    power_segments = []

    for i in range(1, len(points)):
        p0, p1 = points[i-1], points[i]
        dt = p1["t_s"] - p0["t_s"]
        if dt < 1.0:
            continue

        dd = p1["dist_from_start_m"] - p0["dist_from_start_m"]
        if dd <= 0:
            continue

        v = dd / dt
        if v > v_threshold:
            continue  # outlier GPS: scarta intero segmento

        de = p1["ele"] - p0["ele"]
        slope = max(-MAX_SLOPE, min(MAX_SLOPE, de / dd))

        f_grav = m_tot * g * math.sin(math.atan(slope))
        f_roll = m_tot * g * math.cos(math.atan(slope)) * crr
        f_aero = 0.5 * rho * cda * v * v
        p_inst = max(0.0, (f_grav + f_roll + f_aero) * v)

        power_segments.append({
            "t_start": p0["t_s"],
            "t_end": p1["t_s"],
            "watts": p_inst,
        })

    if not power_segments:
        return jsonify({"error": "Nessun segmento valido", "bests": []})

    # ── Resample a 1s + prefix-sum → sliding window O(n) ─────────
    total_secs = int(power_segments[-1]["t_end"]) + 1
    power_1s = [0.0] * total_secs

    for seg in power_segments:
        w = seg["watts"]
        for s in range(max(0, int(seg["t_start"])), min(total_secs, int(seg["t_end"]))):
            power_1s[s] = w

    prefix = [0.0] * (total_secs + 1)
    for i in range(total_secs):
        prefix[i + 1] = prefix[i] + power_1s[i]

    def _fmt_time(s):
        m = int(s) // 60
        sec = int(s) % 60
        return f"{m}m{sec:02d}s"

    intervals_min = [5, 10, 15, 20, 25, 30, 40, 45, 55, 60]
    bests = []

    for interval_min in intervals_min:
        win = interval_min * 60
        if total_secs < win:
            continue

        best_watts = 0.0
        best_start = 0

        for start in range(total_secs - win + 1):
            avg_w = (prefix[start + win] - prefix[start]) / win
            if avg_w > best_watts:
                best_watts = avg_w
                best_start = start

        if best_watts > 0:
            bests.append({
                "interval_min": interval_min,
                "interval_minutes": interval_min,
                "watts": round(best_watts),
                "start_s": best_start,
                "end_s": best_start + win,
                "start_fmt": _fmt_time(best_start),
                "end_fmt": _fmt_time(best_start + win),
            })

    # Salva nel DB per ranking
    if bests:
        get_cache().save_power_bests(activity_id, bests)

    return jsonify({"bests": bests})


@app.route("/api/activities/<int:activity_id>/power-bests-ranked")
def api_activity_power_bests_ranked(activity_id):
    """
    Restituisce i power bests di un'attività con rank rispetto a tutte le altre attività.
    Usa cache DB; ricalcola solo se mancanti o invalidi (valori assurdi pre-fix).
    """
    existing = get_cache().get_power_bests_for_activity(activity_id)
    if not existing or any(b["watts"] > 2000 for b in existing):
        if existing:
            get_cache().delete_power_bests_for_activity(activity_id)
        with app.test_client() as client:
            resp = client.get(f"/api/activities/{activity_id}/power-bests")
            if resp.status_code != 200:
                return jsonify({"bests": [], "error": "Calcolo power bests fallito"})

    # Ora leggi con i rank
    ranked = get_cache().get_power_bests_with_rank(activity_id)

    # Aggiungi formattazione tempi
    for r in ranked:
        def fmt_time(s):
            m = int(s) // 60
            sec = int(s) % 60
            return f"{m}m{sec:02d}s"
        r["start_fmt"] = fmt_time(r["start_s"])
        r["end_fmt"] = fmt_time(r["end_s"])
        r["interval_min"] = r["interval_minutes"]

    return jsonify({"bests": ranked})


@app.route("/api/power-bests/rankings")
def api_power_bests_rankings():
    """
    Restituisce la classifica globale dei power bests per tutti gli intervalli.
    Opzionale: ?interval=N per filtrare un singolo intervallo.
    """
    interval = request.args.get("interval", type=int)
    all_bests = get_cache().get_power_bests_rankings(interval)

    # Raggruppa per intervallo e assegna rank
    from collections import defaultdict
    by_interval = defaultdict(list)
    for b in all_bests:
        by_interval[b["interval_minutes"]].append(b)

    result = {}
    for interval_min, bests in by_interval.items():
        # Già ordinati per watts DESC dal DB
        ranked = []
        for i, b in enumerate(bests, 1):
            def fmt_time(s):
                m = int(s) // 60
                sec = int(s) % 60
                return f"{m}m{sec:02d}s"
            ranked.append({
                "rank": i,
                "watts": b["watts"],
                "activity_id": b["activity_id"],
                "activity_name": b.get("activity_name") or b.get("filename", ""),
                "activity_date": b.get("activity_date"),
                "start_fmt": fmt_time(b["start_s"]),
                "end_fmt": fmt_time(b["end_s"]),
                "is_pr": i == 1,
            })
        result[str(interval_min)] = ranked

    return jsonify(result)


@app.route("/api/strava/activities")
def api_strava_activities():
    """
    Fetch lista attività Strava con paginazione automatica.
    Confronta con le attività già importate nel DB per marcare quelle nuove.
    """
    from strava.auth import StravaAuth
    import os
    os.environ.setdefault("SILENCE_TOKEN_WARNINGS", "true")
    from stravalib.client import Client
    from stravalib.util.limiter import DefaultRateLimiter

    auth = StravaAuth(
        _config["strava"].get("client_id", ""),
        _config["strava"].get("client_secret", ""),
    )
    token = auth.get_valid_access_token()
    if not token:
        return jsonify({"error": "Non autenticato. Esegui: python run.py auth login"}), 401

    try:
        client = Client(access_token=token, rate_limiter=DefaultRateLimiter(priority="medium"))
        activities = []
        # Invalida cache match — la lista è aggiornata
        api_strava_match_activity._cache = None
        for act in client.get_activities():
            activities.append({
                "strava_id":    act.id,
                "name":         act.name,
                "sport_type":   str(act.sport_type or act.type or ""),
                "start_date":   act.start_date.strftime("%Y-%m-%dT%H:%M:%S") if act.start_date else None,
                "distance_m":   float(act.distance or 0),
                "elevation_m":  float(act.total_elevation_gain or 0),
                "moving_time_s": _to_seconds(act.moving_time),
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Marca quelle già importate (match per data)
    imported_dates = {
        a["activity_date"] for a in get_cache().get_all_activities()
        if a.get("activity_date")
    }
    for a in activities:
        a["imported"] = a["start_date"] in imported_dates

    return jsonify(activities)


@app.route("/api/import", methods=["POST"])
def api_import():
    """Importa uno o più file GPX. Ritorna i risultati.
    Parametri form opzionali:
      strava_activity_id — se presente, fetcha effort da Strava API dopo l'import
      type               — cycling|running (default cycling)
    """
    if "gpx" not in request.files:
        return jsonify({"error": "Nessun file GPX"}), 400

    files = request.files.getlist("gpx")
    strava_activity_id = request.form.get("strava_activity_id", "").strip()
    results = []

    from segmentizer.pipeline import Segmentizer
    from strava.auth import StravaAuth as _Auth

    auth = StravaAuth(
        _config["strava"].get("client_id", ""),
        _config["strava"].get("client_secret", ""),
    )
    token = auth.get_valid_access_token()
    if token:
        _config["strava"]["access_token"] = token

    seg = Segmentizer(config=_config)

    for f in files:
        try:
            payload = f.read()
            src_path = _persist_gpx_payload(f.filename or "upload.gpx", payload)
            r = seg.process(src_path, activity_type=request.form.get("type", "cycling"))
            matched = r["segments_matched"]
            result = {
                "filename": f.filename,
                "activity_id": r["activity_id"],
                "activity_date": r["activity_date"],
                "reimport": r["reimport"],
                "segments_matched": len(matched),
                "source": r["source"],
                "gpx_stats": r["gpx_stats"],
            }
            # Se fornito strava_activity_id, fetcha effort API
            if strava_activity_id:
                try:
                    from strava.client import StravaClient
                    from strava.efforts import fetch_and_store_strava_efforts
                    strava = StravaClient(_config, get_cache())
                    saved = fetch_and_store_strava_efforts(
                        strava, get_cache(), r["activity_id"], int(strava_activity_id)
                    )
                    result["strava_efforts"] = saved
                except Exception as e_strava:
                    logger.warning(f"Strava effort fetch fallito: {e_strava}")
                    result["strava_efforts_error"] = str(e_strava)
            results.append(result)
        except Exception as e:
            results.append({"filename": f.filename, "error": str(e)})

    return jsonify(results)


@app.route("/api/strava/import-activity", methods=["POST"])
def api_strava_import_activity():
    """
    Modalità 2: import completo da Strava.
    Body JSON: { strava_activity_id: int, activity_type: str }
    1. Fetcha stream GPS → ricostruisce GPX sintetico
    2. Importa GPX via pipeline (fetch segmenti + matching Fréchet)
    3. Fetcha effort da API Strava (i 68 esatti)
    """
    import traceback
    from strava.auth import StravaAuth as _Auth
    from stravalib.client import Client
    from stravalib.util.limiter import DefaultRateLimiter
    from strava.gpx_builder import build_gpx_from_streams
    from strava.client import StravaClient
    from strava.efforts import fetch_and_store_strava_efforts
    from segmentizer.pipeline import Segmentizer

    data = request.get_json(force=True)
    strava_activity_id = data.get("strava_activity_id")
    activity_type      = data.get("activity_type", "cycling")
    if not strava_activity_id:
        return jsonify({"error": "strava_activity_id mancante"}), 400

    auth = StravaAuth(
        _config["strava"].get("client_id", ""),
        _config["strava"].get("client_secret", ""),
    )
    token = auth.get_valid_access_token()
    if not token:
        return jsonify({"error": "Non autenticato"}), 401
    _config["strava"]["access_token"] = token

    client = Client(access_token=token, rate_limiter=DefaultRateLimiter(priority="medium"))

    try:
        # 1. Recupera metadati attività
        activity = _fetch_activity(client, int(strava_activity_id), context="import-activity")
        act_name = activity.name or f"Strava {strava_activity_id}"

        # 2. Ricostruisci GPX dagli stream
        gpx_content = build_gpx_from_streams(client, strava_activity_id, act_name)
        if not gpx_content:
            return jsonify({"error": "Stream GPS non disponibili per questa attività"}), 400

        # 3. Salva GPX temporaneo e importa via pipeline
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in act_name)
        filename  = f"strava_{strava_activity_id}_{safe_name[:40]}.gpx"

        src_path = _persist_gpx_payload(filename, gpx_content.encode("utf-8"))
        seg = Segmentizer(config=_config)
        r = seg.process(src_path, activity_type=activity_type,
                        filename_override=filename,
                        strava_activity_id=strava_activity_id)

        activity_id = r["activity_id"]

        # 3b. Salva metadata Strava nell'attività
        _save_strava_meta(get_cache(), activity_id, activity)

        # 4. Fetch effort Strava API — idempotente per strava_effort_id
        strava_client = StravaClient(_config, get_cache())
        saved = fetch_and_store_strava_efforts(
            strava_client, get_cache(), activity_id, int(strava_activity_id)
        )
        get_cache().update_activity_strava_id(activity_id, int(strava_activity_id), "strava_api")

        return jsonify({
            "ok": True,
            "activity_id": activity_id,
            "filename": filename,
            "segments_matched": len(r["segments_matched"]),
            "strava_efforts": saved,
            "gpx_stats": r["gpx_stats"],
        })

    except Exception as e:
        logger.error("strava_import_activity ERROR:\n%s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------ #
# Avvio
# ------------------------------------------------------------------ #

def run_server(config, host="127.0.0.1", port=5757, open_browser=True, verbose=False):
    global _config
    _config = config
    _configure_logging(verbose=verbose)

    url = "http://{}:{}".format(host, port)
    print("\n🌐 stravish GUI  →  {}".format(url))
    print("   Premi Ctrl+C per fermare\n")

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
