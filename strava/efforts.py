"""
strava/efforts.py

Fetcha TUTTI gli effort di un'attività via GET /activities/{id}/segment_efforts
(endpoint raw — restituisce tutti i segmenti percorsi, non solo gli starred).
"""
import logging
import calendar
from cache.db import SegmentCache, Effort, CachedSegment

logger = logging.getLogger(__name__)


def _to_seconds(duration) -> int:
    if duration is None:
        return 0
    if hasattr(duration, 'total_seconds'):
        return int(duration.total_seconds())
    return int(duration)


def fetch_and_store_strava_efforts(strava_client, cache: SegmentCache,
                                    activity_id: int, strava_activity_id: int):
    from strava.auth import StravaAuth
    import os
    os.environ.setdefault("SILENCE_TOKEN_WARNINGS", "true")

    cfg = strava_client._config if hasattr(strava_client, '_config') else {}
    strava_cfg = cfg.get("strava", {}) if cfg else {}
    auth = StravaAuth(strava_cfg.get("client_id", ""), strava_cfg.get("client_secret", ""))
    fresh_token = auth.get_valid_access_token()

    from stravalib.client import Client
    from stravalib.util.limiter import DefaultRateLimiter
    client = Client(
        access_token=fresh_token,
        rate_limiter=DefaultRateLimiter(priority="medium"),
    )

    # Log rate limit Strava (informativo)
    try:
        for rule in client.protocol.rate_limiter.rules:
            usage = getattr(rule, 'usage', None)
            limit = getattr(rule, 'limit', None)
            if usage is not None and limit:
                logger.info(f"Strava rate limit: {usage}/{limit}")
    except Exception:
        pass

    # get_activity con include_all_efforts=True — unico endpoint pubblico disponibile
    activity = client.get_activity(strava_activity_id, include_all_efforts=True)
    raw_efforts = activity.segment_efforts or []
    logger.info(f"Strava restituisce {len(raw_efforts)} effort per attività {strava_activity_id}")

    if not raw_efforts:
        logger.warning("Nessun effort — verifica scope activity:read_all e segmenti starred")

    # Cancella solo effort Fréchet locali
    cache._conn.execute(
        "DELETE FROM efforts WHERE activity_id=? AND source='frechet'",
        (activity_id,)
    )
    cache._conn.commit()

    saved = 0
    skipped = 0
    for se in raw_efforts:
        logger.info(se)
        hidden = getattr(se, 'hidden', False)
        if hidden:
            logger.info(f"Segmento {getattr(se,'id','?')} '{getattr(se,'name','?')}' nascosto — scartato")
            skipped += 1
            continue

        # se è un oggetto stravalib (DetailedSegmentEffort)
        seg = getattr(se, 'segment', None)
        if seg is None:
            logger.warning(f"Effort {getattr(se,'id','?')} senza segment — scartato")
            skipped += 1
            continue

        seg_id = seg.id
        if not seg_id:
            logger.warning(f"Effort {getattr(se,'id','?')} seg senza id — scartato")
            skipped += 1
            continue

        # Upsert segmento
        existing = cache._conn.execute(
            "SELECT segment_id, polyline FROM segments WHERE segment_id=?", (seg_id,)
        ).fetchone()
        needs_upsert = not existing or not (existing[1] or "").strip()

        if needs_upsert:
            start_ll = getattr(seg, 'start_latlng', None)
            end_ll   = getattr(seg, 'end_latlng', None)
            seg_map  = getattr(seg, 'map', None)
            polyline = (getattr(seg, 'points', None)
                        or (getattr(seg_map, 'polyline', None) if seg_map else None)
                        or "")

            if not polyline:
                try:
                    detailed = client.get_segment(seg_id)
                    d_map = getattr(detailed, 'map', None)
                    polyline = (getattr(detailed, 'points', None)
                                or (getattr(d_map, 'polyline', None) if d_map else None)
                                or "")
                    if not start_ll:
                        start_ll = getattr(detailed, 'start_latlng', None)
                    if not end_ll:
                        end_ll = getattr(detailed, 'end_latlng', None)
                    logger.info(f"DetailedSegment {seg_id} polyline len={len(polyline)}")
                except Exception as ex:
                    logger.warning(f"get_segment({seg_id}) fallito: {ex}")

            elev_high = getattr(seg, 'elevation_high', None) or 0
            elev_low  = getattr(seg, 'elevation_low', None) or 0
            cs = CachedSegment(
                segment_id=seg_id,
                name=getattr(seg, 'name', None) or f"Segment {seg_id}",
                source="strava",
                activity_type=str(getattr(seg, 'activity_type', 'cycling') or 'cycling').lower(),
                avg_grade=float(getattr(seg, 'average_grade', 0) or 0),
                distance=float(getattr(seg, 'distance', 0) or 0),
                elev_difference=float(elev_high) - float(elev_low),
                start_lat=float(start_ll.lat) if start_ll else 0.0,
                start_lng=float(start_ll.lon) if start_ll else 0.0,
                end_lat=float(end_ll.lat) if end_ll else 0.0,
                end_lng=float(end_ll.lon) if end_ll else 0.0,
                polyline=polyline,
            )
            cache.upsert_segment(cs)

        elapsed  = _to_seconds(getattr(se, 'elapsed_time', None))
        distance = float(getattr(se, 'distance', None) or getattr(seg, 'distance', 0) or 0)
        avg_speed = distance / elapsed if elapsed > 0 else 0.0

        start_time_s  = None
        start_offset  = None
        try:
            se_start  = getattr(se, 'start_date', None)
            act_start = getattr(activity, 'start_date', None)
            if se_start:
                start_time_s = float(calendar.timegm(se_start.timetuple()))
            if se_start and act_start:
                start_offset = _to_seconds(se_start - act_start)
        except Exception:
            pass

        gps_start_idx = getattr(se, 'start_index', None)
        gps_end_idx   = getattr(se, 'end_index', None)

        avg_hr = getattr(se, "average_heartrate", None)
        try:
            avg_hr = float(avg_hr) if avg_hr is not None else None
        except Exception:
            avg_hr = None

        effort = Effort(
            effort_id=None,
            activity_id=activity_id,
            segment_id=seg_id,
            strava_effort_id=se.id,
            source="strava_api",
            elapsed_seconds=elapsed,
            avg_speed_ms=avg_speed,
            avg_grade_pct=float(getattr(seg, 'average_grade', 0) or 0),
            distance_m=distance,
            elev_gain_m=0.0,
            frechet_distance_m=0.0,
            start_idx=gps_start_idx,
            end_idx=gps_end_idx,
            start_time_s=start_time_s,
            average_heartrate=avg_hr,
        )
        cache.insert_effort(effort)
        saved += 1

    cache.update_activity_strava_id(activity_id, strava_activity_id, "strava_api")
    if skipped:
        logger.warning(f"Effort scartati: {skipped} su {len(raw_efforts)} totali")
    return saved
