#!/usr/bin/env python3
"""
Cleanup shallow del DB:
- rimuove effort locali/importati non necessari quando esiste già almeno un effort Strava per attività
- ricalcola e persiste i summary (total_distance_m / total_elevation_m) per tutte le attività

Uso:
  python3 cleanup_shallow.py
  python3 cleanup_shallow.py --dry-run
  python3 cleanup_shallow.py --config /path/to/config.yml
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import yaml

from cache.db import SegmentCache, resolve_cache_db_path
import gui.server as server

LOG = logging.getLogger("cleanup_shallow")


LOCAL_SOURCES = ("auto", "historical", "frechet")


def cleanup_local_efforts(cache: SegmentCache, dry_run: bool = False) -> tuple[int, int]:
    """Rimuove effort locali solo per attività che hanno già effort Strava."""
    rows = cache._conn.execute(
        """
        SELECT activity_id,
               SUM(CASE WHEN source='strava_api' THEN 1 ELSE 0 END) AS strava_n,
               SUM(CASE WHEN source IN ('auto','historical','frechet') THEN 1 ELSE 0 END) AS local_n
        FROM efforts
        GROUP BY activity_id
        """
    ).fetchall()

    touched_activities = 0
    deleted_efforts = 0

    for r in rows:
        aid = int(r["activity_id"])
        strava_n = int(r["strava_n"] or 0)
        local_n = int(r["local_n"] or 0)

        if strava_n <= 0 or local_n <= 0:
            continue

        touched_activities += 1
        deleted_efforts += local_n

        LOG.info(
            "activity_id=%s: cleanup locali (%s) con Strava presente (%s)",
            aid,
            local_n,
            strava_n,
        )

        if not dry_run:
            cache._conn.execute(
                "DELETE FROM efforts WHERE activity_id=? AND source IN ('auto','historical','frechet')",
                (aid,),
            )

    if not dry_run:
        cache._conn.commit()

    return touched_activities, deleted_efforts


def recompute_all_summaries(cfg: dict, cache: SegmentCache, dry_run: bool = False) -> int:
    """Ricalcola summary per tutte le attività in modo persistente."""
    aids = [
        int(r[0])
        for r in cache._conn.execute(
            "SELECT activity_id FROM activities ORDER BY activity_id"
        ).fetchall()
    ]

    if dry_run:
        for aid in aids:
            LOG.info("dry-run recompute activity_id=%s", aid)
        return len(aids)

    # Inietta config/cache nel modulo server per riusare la logica ufficiale di recompute.
    server._config = cfg
    server._cache = cache

    for aid in aids:
        server._recompute_activity_totals_from_efforts(aid)

    return len(aids)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup shallow + ricalcolo summary")
    parser.add_argument("--config", default="config.yml", help="Path al config.yml")
    parser.add_argument("--dry-run", action="store_true", help="Non scrive sul DB")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        raise SystemExit(f"Config non trovato: {cfg_path}")

    cfg = yaml.safe_load(cfg_path.read_text())
    db_path = resolve_cache_db_path(cfg.get("cache", {}))

    cache = SegmentCache(str(db_path))
    try:
        touched, deleted = cleanup_local_efforts(cache, dry_run=args.dry_run)
        recomputed = recompute_all_summaries(cfg, cache, dry_run=args.dry_run)

        LOG.info("attività con cleanup locali: %s", touched)
        LOG.info("effort locali rimossi: %s", deleted)
        LOG.info("summary ricalcolati: %s", recomputed)
    finally:
        cache.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
