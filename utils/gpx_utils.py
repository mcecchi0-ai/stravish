"""
utils/gpx_utils.py
"""

import math
import gpxpy
from strava.client import BBox


def parse_gpx_points(gpx_path: str) -> list[dict]:
    with open(gpx_path) as f:
        gpx = gpxpy.parse(f)

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                points.append({
                    "lat": pt.latitude,
                    "lng": pt.longitude,
                    "ele": pt.elevation or 0.0,
                    "time": pt.time,
                    "dist_from_start_m": 0.0,
                })
    return points


def haversine_m(lat1, lng1, lat2, lng2) -> float:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_distances(points: list[dict]) -> list[dict]:
    cum = 0.0
    for i in range(1, len(points)):
        cum += haversine_m(
            points[i-1]["lat"], points[i-1]["lng"],
            points[i]["lat"],   points[i]["lng"],
        )
        points[i]["dist_from_start_m"] = cum
    return points


def gpx_bbox(points: list[dict]) -> BBox:
    lats = [p["lat"] for p in points]
    lngs = [p["lng"] for p in points]
    return BBox(
        lat_min=min(lats), lat_max=max(lats),
        lng_min=min(lngs), lng_max=max(lngs),
    )
