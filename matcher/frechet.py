"""
matcher/frechet.py

Segment matching usando Fréchet distance discreta.
Confronta la polyline di un segmento con i tratti candidati della traccia GPX.
"""
from typing import List, Optional, Union

import math
import logging
import polyline as polyline_lib  # pip install polyline
from dataclasses import dataclass

from cache.db import CachedSegment
from auto_detect.detector import DetectedSegment
from utils.gpx_utils import haversine_m

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    segment_id: Union[int, str]
    name: str
    source: str            # "strava" | "auto"
    segment_type: str      # "climb" | "descent" | "flat" | "unknown"
    distance_m: float
    avg_grade_pct: float
    elapsed_seconds: Optional[float]
    start_idx: int
    end_idx: int
    frechet_distance_m: float


class SegmentMatcher:

    def __init__(self, config: dict):
        cfg = config.get("matching", {})
        self.proximity_radius_m = cfg.get("proximity_radius_m", 40)
        self.max_frechet_m = cfg.get("max_frechet_distance_m", 25)
        self.min_coverage = cfg.get("min_coverage_ratio", 0.85)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def match_cached_segment(
        self, seg: CachedSegment, track_points: List[dict],
        track_bbox=None
    ) -> Optional[MatchResult]:
        """Matcha un segmento Strava (con polyline encodata) sulla traccia.
        Pre-filtro geografico: scarta subito i segmenti fuori dalla bbox
        della traccia (con buffer), evitando Frechet su segmenti lontani.
        """
        if not seg.polyline:
            return None

        # Pre-filtro: il segmento deve toccare la bbox della traccia
        if track_bbox is not None:
            lat_min, lat_max, lng_min, lng_max, buf = track_bbox
            if not (lat_min - buf <= seg.start_lat <= lat_max + buf and
                    lng_min - buf <= seg.start_lng <= lng_max + buf):
                return None

        seg_coords = polyline_lib.decode(seg.polyline)
        if not seg_coords:
            return None

        return self._match(
            seg_coords=seg_coords,
            track_points=track_points,
            segment_id=seg.segment_id,
            name=seg.name,
            source="strava",
            seg_type="unknown",
            distance_m=seg.distance,
            avg_grade=seg.avg_grade,
        )

    def match_auto_segment(
        self, seg: DetectedSegment, track_points: List[dict]
    ) -> Optional[MatchResult]:
        """Matcha un segmento auto-rilevato (già ha start/end idx)."""
        # I segmenti auto hanno già l'indice — match diretto, nessun search necessario
        elapsed = self._compute_elapsed(track_points, seg.start_idx, seg.end_idx)
        return MatchResult(
            segment_id=f"auto_{seg.start_idx}_{seg.end_idx}",
            name=seg.name,
            source="auto",
            segment_type=seg.type,
            distance_m=seg.distance_m,
            avg_grade_pct=seg.avg_grade_pct,
            elapsed_seconds=elapsed,
            start_idx=seg.start_idx,
            end_idx=seg.end_idx,
            frechet_distance_m=0.0,
        )

    # ------------------------------------------------------------------
    # Core matching
    # ------------------------------------------------------------------

    def _match(
        self,
        seg_coords: List[tuple],
        track_points: List[dict],
        segment_id, name, source, seg_type,
        distance_m, avg_grade,
    ) -> Optional[MatchResult]:

        seg_start = seg_coords[0]
        seg_end   = seg_coords[-1]

        LAT_M, LNG_M = 111000.0, 79850.0
        r = self.proximity_radius_m
        TOP_K = 3

        try:
            import numpy as np
            lats_arr = np.array([p["lat"] for p in track_points])
            lngs_arr = np.array([p["lng"] for p in track_points])

            dlat_s = (lats_arr - seg_start[0]) * LAT_M
            dlng_s = (lngs_arr - seg_start[1]) * LNG_M
            dist2_s = dlat_s**2 + dlng_s**2
            idxs_s = list(np.where(dist2_s <= r**2)[0])
            if not idxs_s:
                min_d = float(np.sqrt(dist2_s.min()))
                logger.debug("NO_START [{:.0f}m]  {}".format(min_d, name))
                return None
            idxs_s.sort(key=lambda i: dist2_s[i])
            top_s = [int(i) for i in idxs_s[:TOP_K]]

            dlat_e = (lats_arr - seg_end[0]) * LAT_M
            dlng_e = (lngs_arr - seg_end[1]) * LNG_M
            dist2_e = dlat_e**2 + dlng_e**2
            idxs_e = list(np.where(dist2_e <= r**2)[0])
            if not idxs_e:
                min_d = float(np.sqrt(dist2_e.min()))
                logger.debug("NO_END   [{:.0f}m]  {}".format(min_d, name))
                return None
            idxs_e.sort(key=lambda i: dist2_e[i])
            top_e = [int(i) for i in idxs_e[:TOP_K]]

            cum_dists = [p.get("dist_from_start_m", 0) for p in track_points]

        except ImportError:
            # Fallback puro Python — nessuna dipendenza esterna
            logger.warning("numpy non disponibile, uso fallback puro Python (più lento)")
            cum_dists = [p.get("dist_from_start_m", 0) for p in track_points]

            def _dist2(p, ref):
                return ((p["lat"] - ref[0]) * LAT_M) ** 2 + ((p["lng"] - ref[1]) * LNG_M) ** 2

            r2 = r ** 2
            cands_s = [(i, _dist2(p, seg_start)) for i, p in enumerate(track_points)
                       if _dist2(p, seg_start) <= r2]
            if not cands_s:
                return None
            top_s = [i for i, _ in sorted(cands_s, key=lambda x: x[1])[:TOP_K]]

            cands_e = [(i, _dist2(p, seg_end)) for i, p in enumerate(track_points)
                       if _dist2(p, seg_end) <= r2]
            if not cands_e:
                return None
            top_e = [i for i, _ in sorted(cands_e, key=lambda x: x[1])[:TOP_K]]
        # Tollera slice fino a 3x la distanza del segmento (minimo 500m)
        max_slice_m = max(distance_m * 3.0, 500.0) if distance_m > 0 else 50000.0

        best_frechet = float("inf")
        best_start_i = best_end_i = None

        for si in top_s:
            for ei in top_e:
                si, ei = int(si), int(ei)
                if ei <= si:
                    continue
                # Scarta slice troppo lunghe rispetto al segmento
                slice_m = cum_dists[ei] - cum_dists[si]
                if slice_m > max_slice_m:
                    logger.debug("LONG_SLICE [{:.0f}m > {:.0f}m]  {}".format(slice_m, max_slice_m, name))
                    continue
                track_slice = [(track_points[i]["lat"], track_points[i]["lng"])
                               for i in range(si, ei + 1)]
                if len(track_slice) < 2:
                    continue
                # Subsample la slice al doppio dei punti del segmento
                # per mantenere la Fréchet O(m²) invece di O(n*m)
                max_pts = max(len(seg_coords) * 2, 20)
                if len(track_slice) > max_pts:
                    step = len(track_slice) // max_pts
                    track_slice = track_slice[::step]
                f = discrete_frechet_distance(track_slice, seg_coords)
                if f < best_frechet:
                    best_frechet = f
                    best_start_i = si
                    best_end_i   = ei

        if best_frechet > self.max_frechet_m or best_start_i is None:
            logger.debug("SKIP  [frechet={:.1f}m > {:.0f}m]  {}".format(
                best_frechet, self.max_frechet_m, name))
            return None
        logger.debug("MATCH [frechet={:.1f}m]  {}".format(best_frechet, name))

        elapsed = self._compute_elapsed(track_points, best_start_i, best_end_i)

        return MatchResult(
            segment_id=segment_id,
            name=name,
            source=source,
            segment_type=seg_type,
            distance_m=distance_m,
            avg_grade_pct=avg_grade,
            elapsed_seconds=elapsed,
            start_idx=best_start_i,
            end_idx=best_end_i,
            frechet_distance_m=best_frechet,
        )

    @staticmethod
    def _compute_elapsed(
        points: List[dict], start_i: int, end_i: int
    ) -> Optional[float]:
        t_start = points[start_i].get("time")
        t_end = points[end_i].get("time")
        if t_start and t_end:
            return (t_end - t_start).total_seconds()
        return None


# ------------------------------------------------------------------
# Fréchet distance discreta (O(n*m) — sufficiente per segmenti <500pt)
# ------------------------------------------------------------------

def discrete_frechet_distance(
    P: List[tuple], Q: List[tuple]
) -> float:
    """
    Fréchet distance discreta tra due polyline P e Q.
    Implementazione iterativa bottom-up (DP) — nessuna ricorsione,
    funziona con tracce di qualsiasi lunghezza.
    """
    n, m = len(P), len(Q)
    # Usa solo due righe di memoria invece di matrice n*m intera
    prev = [0.0] * m
    curr = [0.0] * m

    for i in range(n):
        for j in range(m):
            d = haversine_m(P[i][0], P[i][1], Q[j][0], Q[j][1])
            if i == 0 and j == 0:
                curr[j] = d
            elif i == 0:
                curr[j] = max(curr[j-1], d)
            elif j == 0:
                curr[j] = max(prev[j], d)
            else:
                curr[j] = max(min(prev[j], prev[j-1], curr[j-1]), d)
        prev, curr = curr, [0.0] * m

    return prev[m - 1]
