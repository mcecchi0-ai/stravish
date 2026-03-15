"""
segmentizer/pipeline.py — import leggero: parse GPX → salva attività + tracciato.
"""
import json
import logging
import os
import yaml
import gpxpy

from cache.db import SegmentCache, CachedSegment, Effort
from utils.gpx_utils import parse_gpx_points, compute_distances
from auto_detect.detector import AutoSegmentDetector
from matcher.frechet import SegmentMatcher

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


class Segmentizer:

    def __init__(self, config_path=None, config=None):
        if config is not None:
            self.config = config
        else:
            with open(config_path or "config.yml") as f:
                self.config = yaml.safe_load(f)
        self.cache = SegmentCache(self.config["cache"]["db_path"])

    def process(self, gpx_path, activity_type="cycling",
                filename_override=None, strava_activity_id=None):
        logger.info("Processing: {}".format(gpx_path))

        points = parse_gpx_points(gpx_path)
        if not points:
            raise ValueError("GPX vuoto o non valido")

        points = compute_distances(points)
        filename = filename_override or os.path.basename(str(gpx_path))

        gpx_date = None
        gpx_meta = {}
        try:
            with open(gpx_path) as f:
                gpx_obj = gpxpy.parse(f)
            if gpx_obj.tracks and gpx_obj.tracks[0].segments:
                pt0 = gpx_obj.tracks[0].segments[0].points[0]
                if pt0.time:
                    gpx_date = pt0.time.strftime("%Y-%m-%dT%H:%M:%S")
            hrs, cads, pwrs, times = [], [], [], []
            for track in gpx_obj.tracks:
                for seg in track.segments:
                    for pt in seg.points:
                        if pt.time:
                            times.append(pt.time)
                        for ext in (pt.extensions or []):
                            for child in list(ext):
                                tag = child.tag.split("}")[-1].lower()
                                try:
                                    v = float(child.text)
                                    if tag in ("hr", "heartrate") and v > 0: hrs.append(v)
                                    elif tag in ("cad", "cadence") and v > 0: cads.append(v)
                                    elif tag in ("power", "watts") and v > 0: pwrs.append(v)
                                except Exception:
                                    pass
            import statistics as _stats
            if hrs:
                gpx_meta["avg_heartrate"] = round(_stats.mean(hrs), 1)
                gpx_meta["max_heartrate"] = round(max(hrs))
                if len(hrs) >= 2:
                    gpx_meta["sigma_heartrate"] = round(_stats.pstdev(hrs), 1)
            if cads:
                gpx_meta["avg_cadence"] = round(_stats.mean(cads), 1)
                gpx_meta["max_cadence"] = round(max(cads))
                if len(cads) >= 2:
                    gpx_meta["sigma_cadence"] = round(_stats.pstdev(cads), 1)
            if pwrs:
                gpx_meta["avg_watts"] = round(_stats.mean(pwrs), 1)
            if len(times) >= 2:
                delta = (times[-1] - times[0]).total_seconds()
                if delta > 0:
                    gpx_meta["moving_time_s"] = int(delta)
        except Exception as ex:
            logger.warning(f"GPX meta extraction failed: {ex}")

        total_dist = points[-1]["dist_from_start_m"] if points else 0
        total_ele  = sum(
            max(0, points[i]["ele"] - points[i-1]["ele"])
            for i in range(1, len(points))
        )

        # Tracciato decimato per visualizzazione (max 500 punti)
        step = max(1, len(points) // 500)
        gpx_track = [[round(p["lat"], 6), round(p["lng"], 6)]
                     for p in points[::step]]
        gpx_points_json = json.dumps(gpx_track)

        # ── Auto-detect segmenti locali ─────────────────────────────
        auto_segments = []
        auto_efforts_data = []
        if self.config.get("auto_detect", {}).get("enabled", True):
            try:
                detector = AutoSegmentDetector(self.config)
                matcher  = SegmentMatcher(self.config)
                detected = detector.detect(points)
                logger.info(f"Auto-detect: {len(detected)} segmenti trovati in {filename}")
                import calendar, time as _time
                act_epoch = None
                if gpx_date:
                    import datetime
                    dt = datetime.datetime.strptime(gpx_date, "%Y-%m-%dT%H:%M:%S")
                    act_epoch = float(calendar.timegm(dt.timetuple()))
                for seg in detected:
                    result = matcher.match_auto_segment(seg, points)
                    if result:
                        auto_efforts_data.append((seg, result, act_epoch))
                        auto_segments.append(seg)
            except Exception as ex:
                logger.warning(f"Auto-detect fallito: {ex}")

        activity_id = self.cache.find_activity(filename, gpx_date)
        is_reimport = activity_id is not None
        if is_reimport:
            logger.info("Attività già presente (id={}), aggiorno tracciato".format(activity_id))
            self.cache.update_activity_gpx(activity_id, gpx_points_json, len(points))
        else:
            activity_id = self.cache.insert_activity(
                filename, gpx_date, total_dist, total_ele, len(points),
                strava_activity_id=strava_activity_id,
            )
            self.cache.update_activity_gpx(activity_id, gpx_points_json, len(points))
        if gpx_meta:
            self.cache.update_activity_meta(activity_id, **gpx_meta)


        # ── Match segmenti storici già in cache ──────────────────────
        historical_saved = 0
        try:
            from utils.gpx_utils import gpx_bbox
            matcher_h = SegmentMatcher(self.config)
            bbox = gpx_bbox(points)
            buf  = 0.01
            cached_segs = self.cache.get_segments_in_bbox(
                bbox[0]-buf, bbox[1]+buf, bbox[2]-buf, bbox[3]+buf
            )
            cached_segs = [s for s in cached_segs if s.polyline and s.source != 'auto']
            track_bbox  = (bbox[0], bbox[1], bbox[2], bbox[3], buf)
            import calendar as _cal
            act_epoch_h = None
            if gpx_date:
                import datetime as _dt
                dt = _dt.datetime.strptime(gpx_date, "%Y-%m-%dT%H:%M:%S")
                act_epoch_h = float(_cal.timegm(dt.timetuple()))
            for seg in cached_segs:
                existing = self.cache._conn.execute(
                    "SELECT effort_id FROM efforts WHERE activity_id=? AND segment_id=?",
                    (activity_id, seg.segment_id)
                ).fetchone()
                if existing:
                    continue
                result = matcher_h.match_cached_segment(seg, points, track_bbox)
                if result:
                    effort = Effort(
                        effort_id=None,
                        activity_id=activity_id,
                        segment_id=seg.segment_id,
                        strava_effort_id=None,
                        source='historical',
                        elapsed_seconds=result.elapsed_seconds or 0,
                        avg_speed_ms=(result.distance_m / result.elapsed_seconds
                                      if result.elapsed_seconds else 0),
                        avg_grade_pct=seg.avg_grade,
                        distance_m=result.distance_m,
                        elev_gain_m=max(0, seg.elev_difference),
                        frechet_distance_m=result.frechet_distance_m,
                        start_idx=result.start_idx,
                        end_idx=result.end_idx,
                        start_time_s=act_epoch_h,
                    )
                    self.cache.insert_effort(effort)
                    historical_saved += 1
            if historical_saved:
                logger.info(f"Match storico: {historical_saved}/{len(cached_segs)} segmenti in {filename}")
        except Exception as ex:
            logger.warning(f"Match storico fallito: {ex}")
        # Salva segmenti e effort auto-rilevati (solo non coperti da storici/Strava)
        covered_ranges = []
        for row in self.cache._conn.execute(
            """SELECT start_idx, end_idx FROM efforts
               WHERE activity_id=? AND source IN ('historical','strava_api')""",
            (activity_id,)
        ).fetchall():
            covered_ranges.append((row["start_idx"], row["end_idx"]))

        # Riduci frammentazione auto: evita duplicati stesso nome+tratto
        compact_auto = []
        for seg, result, act_epoch in sorted(
            auto_efforts_data,
            key=lambda x: float(getattr(x[1], "distance_m", 0.0) or 0.0),
            reverse=True,
        ):
            seg_name = (seg.name or "").strip().lower()
            is_dup = False
            for s2, r2, _ in compact_auto:
                if (s2.name or "").strip().lower() != seg_name:
                    continue
                if _idx_overlap_ratio(result.start_idx, result.end_idx, r2.start_idx, r2.end_idx) >= 0.60:
                    is_dup = True
                    break
            if not is_dup:
                compact_auto.append((seg, result, act_epoch))

        auto_saved = 0
        for seg, result, act_epoch in compact_auto:
            # Non salvare auto effort se coperto da storico/Strava
            if any(
                _idx_overlap_ratio(result.start_idx, result.end_idx, s0, s1) >= 0.75
                for s0, s1 in covered_ranges
            ):
                continue
            import hashlib
            # ID negativo deterministico basato su coordinate (non collide con ID Strava positivi)
            seg_hash = int(hashlib.md5(
                f"{seg.start_lat:.5f},{seg.start_lng:.5f},{seg.end_lat:.5f},{seg.end_lng:.5f}".encode()
            ).hexdigest()[:8], 16)
            seg_id = -(seg_hash % (2**31))  # negativo, max 31bit
            existing = self.cache._conn.execute(
                "SELECT segment_id FROM segments WHERE segment_id=?", (seg_id,)
            ).fetchone()
            if not existing:
                cs = CachedSegment(
                    segment_id=seg_id,
                    name=seg.name,
                    source="auto",
                    activity_type="cycling",
                    avg_grade=seg.avg_grade_pct,
                    distance=seg.distance_m,
                    elev_difference=seg.elevation_gain_m,
                    start_lat=seg.start_lat,
                    start_lng=seg.start_lng,
                    end_lat=seg.end_lat,
                    end_lng=seg.end_lng,
                    polyline="",
                )
                self.cache.upsert_segment(cs)
            start_time_s = None
            if act_epoch and result.elapsed_seconds:
                start_time_s = act_epoch
            effort = Effort(
                effort_id=None,
                activity_id=activity_id,
                segment_id=seg_id,
                strava_effort_id=None,
                source="auto",
                elapsed_seconds=result.elapsed_seconds or 0,
                avg_speed_ms=(result.distance_m / result.elapsed_seconds
                              if result.elapsed_seconds else 0),
                avg_grade_pct=seg.avg_grade_pct,
                distance_m=result.distance_m,
                elev_gain_m=max(0, seg.elevation_gain_m),
                frechet_distance_m=result.frechet_distance_m,
                start_idx=result.start_idx,
                end_idx=result.end_idx,
                start_time_s=start_time_s,
            )
            self.cache.insert_effort(effort)
            auto_saved += 1
        if auto_saved:
            logger.info(f"Salvati {auto_saved} effort auto-detect per {filename}")

        return {
            "source": "gpx_only",
            "filename": filename,
            "activity_id": activity_id,
            "activity_date": gpx_date,
            "reimport": is_reimport,
            "segments_matched": [r for _, r, _ in auto_efforts_data],
            "gpx_stats": {
                "total_distance_m":       total_dist,
                "total_elevation_gain_m": total_ele,
                "num_points":             len(points),
            },
            "cache_size": self.cache.count(),
        }
