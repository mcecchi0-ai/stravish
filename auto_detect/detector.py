"""
auto_detect/detector.py

Rilevamento automatico di segmenti (climb, descent, flat) da traccia GPX.
Attivato quando Strava non restituisce risultati per una zona.

Configurabile da config.yml → auto_detect.*
"""
from typing import List, Tuple, Optional, Literal

import logging
import numpy as np
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

SegmentType = Literal["climb", "descent", "flat"]


@dataclass
class DetectedSegment:
    type: SegmentType
    start_idx: int       # Indice del punto iniziale nella traccia
    end_idx: int         # Indice del punto finale nella traccia
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float
    distance_m: float
    elevation_gain_m: float   # Positivo = salita
    avg_grade_pct: float
    name: str = ""            # Generato automaticamente se vuoto
    points: list = field(default_factory=list)  # [(lat, lng), ...]

    def __post_init__(self):
        if not self.name:
            direction = "↑" if self.type == "climb" else "↓" if self.type == "descent" else "→"
            self.name = (
                f"{direction} {self.avg_grade_pct:.1f}% "
                f"{self.distance_m:.0f}m +{self.elevation_gain_m:.0f}m"
            )


class AutoSegmentDetector:
    """
    Rileva automaticamente segmenti significativi in una traccia GPX.

    Algoritmo:
      1. Smoothing dell'elevazione (media mobile) per ridurre rumore GPS
      2. Calcolo gradiente punto per punto
      3. Identificazione dei "run" continui sopra soglia di pendenza
      4. Filtro per dislivello minimo, lunghezza minima, pendenza media
      5. Merge di run separati da brevi interruzioni
    """

    def __init__(self, config: dict):
        cfg = config.get("auto_detect", {})
        self.enabled = cfg.get("enabled", True)
        self.climb_cfg = cfg.get("climb", {})
        self.descent_cfg = cfg.get("descent", {})
        self.flat_cfg = cfg.get("flat", {})
        self.min_gap_m = cfg.get("min_gap_between_segments_m", 50)

    def detect(self, points: List[dict]) -> List[DetectedSegment]:
        """
        points: lista di dict con chiavi lat, lng, ele, dist_from_start_m
        Ritorna la lista di segmenti rilevati, ordinati per posizione nella traccia.
        """
        if not self.enabled or len(points) < 10:
            return []

        elevations = np.array([p["ele"] for p in points])
        distances = np.array([p["dist_from_start_m"] for p in points])

        results: List[DetectedSegment] = []

        if self.climb_cfg:
            results += self._detect_type(points, elevations, distances, "climb")

        if self.descent_cfg.get("enabled", True):
            results += self._detect_type(points, elevations, distances, "descent")

        if self.flat_cfg.get("enabled", False):
            results += self._detect_type(points, elevations, distances, "flat")

        results.sort(key=lambda s: s.start_idx)
        return self._remove_overlaps(results)

    # ------------------------------------------------------------------
    # Core detection per tipo
    # ------------------------------------------------------------------

    def _detect_type(
        self,
        points: List[dict],
        elevations: np.ndarray,
        distances: np.ndarray,
        seg_type: SegmentType,
    ) -> List[DetectedSegment]:

        cfg = self._cfg_for_type(seg_type)
        window = cfg.get("elevation_smoothing_window", 7)

        # 1. Smooth elevazione
        smoothed = self._smooth(elevations, window)

        # 2. Gradiente punto per punto (%)
        grades = self._compute_grades(smoothed, distances)

        # 3. Threshold per il tipo
        threshold = cfg.get("min_grade_threshold_pct", 1.5)
        if seg_type == "descent":
            threshold = -threshold
            in_segment = grades < threshold  # booleano
        elif seg_type == "flat":
            max_grade = cfg.get("max_avg_grade_pct", 1.5)
            in_segment = np.abs(grades) <= max_grade
        else:  # climb
            in_segment = grades > threshold

        # 4. Trova i "run" continui
        runs = self._find_runs(in_segment)

        # 5. Filtra e costruisci DetectedSegment
        segments = []
        for start_i, end_i in runs:
            seg = self._build_segment(
                points, smoothed, distances, start_i, end_i, seg_type, cfg
            )
            if seg is not None:
                segments.append(seg)

        return segments

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cfg_for_type(self, seg_type: SegmentType) -> dict:
        return {
            "climb": self.climb_cfg,
            "descent": self.descent_cfg,
            "flat": self.flat_cfg,
        }[seg_type]

    @staticmethod
    def _smooth(arr: np.ndarray, window: int) -> np.ndarray:
        """Media mobile semplice. Preserva lunghezza array."""
        if window < 2:
            return arr.copy()
        kernel = np.ones(window) / window
        return np.convolve(arr, kernel, mode="same")

    @staticmethod
    def _compute_grades(elevations: np.ndarray, distances: np.ndarray) -> np.ndarray:
        """Gradiente in % tra punti consecutivi."""
        delta_ele = np.diff(elevations, prepend=elevations[0])
        delta_dist = np.diff(distances, prepend=distances[0])
        # Evita divisione per zero
        delta_dist = np.where(delta_dist == 0, 0.001, delta_dist)
        return (delta_ele / delta_dist) * 100

    @staticmethod
    def _find_runs(mask: np.ndarray) -> List[Tuple[int, int]]:
        """
        Trova intervalli contigui dove mask è True.
        Ritorna lista di (start_idx, end_idx) inclusi.
        """
        runs = []
        in_run = False
        start = 0
        for i, val in enumerate(mask):
            if val and not in_run:
                start = i
                in_run = True
            elif not val and in_run:
                runs.append((start, i - 1))
                in_run = False
        if in_run:
            runs.append((start, len(mask) - 1))
        return runs

    def _build_segment(
        self,
        points: List[dict],
        smoothed_ele: np.ndarray,
        distances: np.ndarray,
        start_i: int,
        end_i: int,
        seg_type: SegmentType,
        cfg: dict,
    ) -> Optional[DetectedSegment]:
        """
        Costruisce un DetectedSegment e applica i filtri di qualità.
        Ritorna None se il segmento non supera i filtri.
        """
        seg_points = points[start_i:end_i + 1]
        if len(seg_points) < 2:
            return None

        dist_m = distances[end_i] - distances[start_i]
        ele_diff = smoothed_ele[end_i] - smoothed_ele[start_i]

        # Filtro lunghezza minima
        min_len = cfg.get("min_length_m", 200)
        if dist_m < min_len:
            return None

        # Filtro dislivello
        if seg_type == "climb":
            if ele_diff < cfg.get("min_elevation_gain_m", 20):
                return None
        elif seg_type == "descent":
            if abs(ele_diff) < cfg.get("min_elevation_loss_m", 20):
                return None

        avg_grade = (ele_diff / dist_m) * 100 if dist_m > 0 else 0

        # Filtro pendenza media
        min_grade = cfg.get("min_avg_grade_pct", 3.0)
        if seg_type in ("climb", "descent") and abs(avg_grade) < min_grade:
            return None

        return DetectedSegment(
            type=seg_type,
            start_idx=start_i,
            end_idx=end_i,
            start_lat=seg_points[0]["lat"],
            start_lng=seg_points[0]["lng"],
            end_lat=seg_points[-1]["lat"],
            end_lng=seg_points[-1]["lng"],
            distance_m=dist_m,
            elevation_gain_m=ele_diff,
            avg_grade_pct=avg_grade,
            points=[(p["lat"], p["lng"]) for p in seg_points],
        )

    def _remove_overlaps(self, segments: List[DetectedSegment]) -> List[DetectedSegment]:
        """
        Rimuove segmenti che si sovrappongono eccessivamente.
        Strategia semplice: tieni il più lungo in caso di overlap.
        """
        if not segments:
            return []
        result = [segments[0]]
        for seg in segments[1:]:
            last = result[-1]
            # Overlap se il nuovo inizia prima che l'ultimo sia finito
            gap_m = seg.start_idx - last.end_idx  # in punti, non metri
            if gap_m < 0:
                # Overlap: tieni il più lungo
                if seg.distance_m > last.distance_m:
                    result[-1] = seg
            else:
                result.append(seg)
        return result
