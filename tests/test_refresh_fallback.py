import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from cache.db import SegmentCache, CachedSegment, Effort
from gui import server


def test_refresh_fallback_without_gpx_recomputes_from_efforts(tmp_path):
    db_path = tmp_path / "segments.db"
    cache = SegmentCache(str(db_path))

    # Wire isolated app globals
    cfg = yaml.safe_load(open("config.yml"))
    server._config = cfg
    server._cache = cache

    aid = cache.insert_activity(
        filename="legacy.gpx",
        activity_date="2024-01-01T10:00:00",
        total_distance_m=0.0,
        total_elevation_m=0.0,
        num_points=0,
        strava_activity_id=None,
    )

    cache.upsert_segment(
        CachedSegment(
            segment_id=123,
            name="Test Segment",
            source="strava",
            activity_type="cycling",
            avg_grade=5.0,
            distance=1000.0,
            elev_difference=50.0,
            start_lat=0.0,
            start_lng=0.0,
            end_lat=0.1,
            end_lng=0.1,
            polyline="abcd",
        )
    )

    cache.insert_effort(
        Effort(
            effort_id=None,
            activity_id=aid,
            segment_id=123,
            elapsed_seconds=200.0,
            avg_speed_ms=5.0,
            avg_grade_pct=5.0,
            distance_m=1000.0,
            elev_gain_m=50.0,
            frechet_distance_m=0.0,
            start_idx=10,
            end_idx=110,
            source="historical",
            start_time_s=1000.0,
        )
    )

    # Explicitly no GPX path => fallback branch
    cache._conn.execute("UPDATE activities SET gpx_path=NULL WHERE activity_id=?", (aid,))
    cache._conn.commit()

    client = server.app.test_client()
    resp = client.post(f"/api/activities/{aid}/refresh", json={"activity_type": "cycling"})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["mode"] == "efforts_only"
    assert payload["gpx_stats"]["total_distance_m"] > 0
    assert payload["gpx_stats"]["total_elevation_m"] > 0

    row = cache._conn.execute(
        "SELECT total_distance_m, total_elevation_m FROM activities WHERE activity_id=?",
        (aid,),
    ).fetchone()
    assert row["total_distance_m"] > 0
    assert row["total_elevation_m"] > 0

    cache.close()
    server._cache = None
