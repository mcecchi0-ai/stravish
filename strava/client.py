"""
strava/client.py
"""

import os
import logging
from dataclasses import dataclass
from typing import List, Optional

os.environ.setdefault("SILENCE_TOKEN_WARNINGS", "true")

from stravalib.client import Client
from stravalib.util.limiter import DefaultRateLimiter

from cache.db import SegmentCache, CachedSegment

logger = logging.getLogger(__name__)

MIN_SPAN_DEG = 0.005

ACTIVITY_TYPE_MAP = {
    "cycling": "riding",
    "running": "running",
    "riding":  "riding",
}


@dataclass
class BBox:
    lat_min: float
    lat_max: float
    lng_min: float
    lng_max: float

    def tile_key(self):
        return "{:.5f}_{:.5f}_{:.5f}_{:.5f}".format(
            self.lat_min, self.lng_min, self.lat_max, self.lng_max
        )

    @classmethod
    def from_points(cls, points):
        lats = [p["lat"] for p in points]
        lngs = [p["lng"] for p in points]
        return cls(
            lat_min=min(lats), lat_max=max(lats),
            lng_min=min(lngs), lng_max=max(lngs),
        )

    def ensure_min_span(self):
        if (self.lat_max - self.lat_min) < MIN_SPAN_DEG:
            mid = (self.lat_min + self.lat_max) / 2
            self.lat_min = mid - MIN_SPAN_DEG / 2
            self.lat_max = mid + MIN_SPAN_DEG / 2
        if (self.lng_max - self.lng_min) < MIN_SPAN_DEG:
            mid = (self.lng_min + self.lng_max) / 2
            self.lng_min = mid - MIN_SPAN_DEG / 2
            self.lng_max = mid + MIN_SPAN_DEG / 2
        return self


class StravaClient:

    def __init__(self, config, cache):
        self.cache = cache
        self._config = config
        access_token = config["strava"].get("access_token", "")
        priority = config["strava"].get("rate_limit_priority", "medium")
        self.chunk_km = config["strava"].get("chunk_km", 10.0)

        if access_token:
            self._client = Client(
                access_token=access_token,
                rate_limiter=DefaultRateLimiter(priority=priority),
            )
        else:
            self._client = None

    def fetch_segments_for_track(self, track_points, activity_type="cycling"):
        results = []
        if self._client is None:
            logger.warning("Nessun access_token - skip fetch Strava")
            return results

        stravalib_type = ACTIVITY_TYPE_MAP.get(activity_type, "riding")
        seen_ids = set()
        chunks = self._split_track_into_chunks(track_points, self.chunk_km)
        total = len(chunks)
        logger.info("Traccia suddivisa in {} chunk da ~{}km".format(total, self.chunk_km))

        for i, chunk_points in enumerate(chunks):
            bbox = BBox.from_points(chunk_points).ensure_min_span()
            tile_key = bbox.tile_key()
            dist_km = chunk_points[-1].get("dist_from_start_m", 0) / 1000

            if self.cache.is_tile_fetched(tile_key):
                # Prendi tutti i segmenti in cache: il filtro per bbox
                # escluderebbe segmenti che iniziano fuori dal chunk
                # ma lo attraversano. La dedup per seen_ids evita duplicati.
                cached = self.cache.get_all_segments()
                new_count = 0
                for seg in cached:
                    if seg.segment_id not in seen_ids:
                        seen_ids.add(seg.segment_id)
                        results.append(seg)
                        new_count += 1
                self._print_progress(i + 1, total, dist_km, new_count, True, [])
                continue

            chunk_results = []
            self._fetch_chunk(bbox, stravalib_type, chunk_results)
            self.cache.mark_tile_fetched(tile_key, len(chunk_results))

            new_count = 0
            for seg in chunk_results:
                if seg.segment_id not in seen_ids:
                    seen_ids.add(seg.segment_id)
                    results.append(seg)
                    new_count += 1

            names = [s.name for s in chunk_results[:2]]
            self._print_progress(i + 1, total, dist_km, new_count, False, names)

        print()
        return results

    def _fetch_chunk(self, bbox, activity_type, accumulator):
        try:
            bounds = (bbox.lat_min, bbox.lng_min, bbox.lat_max, bbox.lng_max)
            raw = list(self._client.explore_segments(bounds, activity_type=activity_type))
        except Exception as e:
            logger.warning("Strava API error: {} - {}".format(type(e).__name__, e))
            return
        for s in raw:
            seg = self._convert(s)
            self.cache.upsert_segment(seg)
            accumulator.append(seg)

    @staticmethod
    def _print_progress(chunk_n, total, dist_km, new_segs, from_cache, names):
        bar_width = 20
        filled = int(bar_width * chunk_n / total)
        bar = filled * "\u2588" + (bar_width - filled) * "\u2591"
        pct = int(100 * chunk_n / total)
        source = "cache" if from_cache else "API  "
        seg_info = "+{} segm.".format(new_segs) if new_segs else "nessun segm."
        preview = ""
        if names:
            preview = "  ({})".format(", ".join(names))
        print("\r  [{}] {:3d}%  chunk {:2d}/{:2d}  {:5.1f}km  {}  {}{}".format(
            bar, pct, chunk_n, total, dist_km, source, seg_info, preview
        ), end="", flush=True)

    @staticmethod
    def _split_track_into_chunks(points, chunk_km):
        if not points:
            return []
        chunk_m = chunk_km * 1000
        chunks = []
        current_chunk = [points[0]]
        chunk_start_dist = points[0].get("dist_from_start_m", 0)
        for pt in points[1:]:
            current_chunk.append(pt)
            dist = pt.get("dist_from_start_m", 0)
            if dist - chunk_start_dist >= chunk_m:
                chunks.append(current_chunk)
                current_chunk = [pt]
                chunk_start_dist = dist
        if len(current_chunk) > 1:
            chunks.append(current_chunk)
        return chunks

    @staticmethod
    def _convert(s):
        start = s.start_latlng
        end = s.end_latlng
        return CachedSegment(
            segment_id=s.id,
            name=s.name,
            source="strava",
            activity_type="cycling",
            avg_grade=float(s.avg_grade) if s.avg_grade else 0.0,
            distance=float(s.distance) if s.distance else 0.0,
            elev_difference=float(s.elev_difference) if s.elev_difference else 0.0,
            start_lat=float(start.lat) if start else 0.0,
            start_lng=float(start.lon) if start else 0.0,
            end_lat=float(end.lat) if end else 0.0,
            end_lng=float(end.lon) if end else 0.0,
            polyline=s.points or "",
        )
