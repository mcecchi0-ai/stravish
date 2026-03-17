"""
strava/gpx_builder.py

Ricostruisce un file GPX sintetico dagli stream GPS di un'attività Strava.
Include estensioni Garmin TrackPointExtension per: hr, cadence, power, temp.
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Stream richiesti in ordine di priorità
_STREAM_TYPES = ["latlng", "altitude", "time", "heartrate", "cadence", "watts", "temp"]


def build_gpx_from_streams(client, strava_activity_id: int, activity_name: str = "") -> str:
    """
    Fetcha gli stream GPS e restituisce una stringa GPX valida.
    Ritorna None se gli stream latlng non sono disponibili.
    """
    try:
        streams = client.get_activity_streams(
            strava_activity_id,
            types=_STREAM_TYPES,
            resolution="high",
        )
    except Exception as e:
        logger.error(f"get_activity_streams({strava_activity_id}) fallito: {e}")
        return None

    def _data(key):
        s = streams.get(key)
        return s.data if s and hasattr(s, 'data') and s.data else []

    latlng    = _data("latlng")
    altitude  = _data("altitude")
    times     = _data("time")
    heartrate = _data("heartrate")
    cadence   = _data("cadence")
    watts     = _data("watts")
    temp      = _data("temp")

    if not latlng:
        logger.warning(f"Nessun dato latlng per attività {strava_activity_id}")
        return None

    has_extensions = any([heartrate, cadence, watts, temp])

    # Recupera start_date per i timestamp assoluti
    start_dt = None
    try:
        logger.info(
            "Strava get_activity(%s, include_all_efforts=False) (gpx_builder.start_date)",
            int(strava_activity_id),
        )
        activity = client.get_activity(int(strava_activity_id), include_all_efforts=False)
        start_dt = activity.start_date
        if not isinstance(start_dt, datetime):
            start_dt = None
    except Exception:
        pass

    name = activity_name or f"Strava {strava_activity_id}"

    ns_ext = 'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1"' \
             if has_extensions else ""

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<gpx version="1.1" creator="stravish" '
        f'xmlns="http://www.topografix.com/GPX/1/1" {ns_ext}>',
        f'  <trk><name>{_xe(name)}</name><trkseg>',
    ]

    for i, (lat, lng) in enumerate(latlng):
        parts = []

        if i < len(altitude) and altitude[i] is not None:
            parts.append(f'<ele>{altitude[i]:.1f}</ele>')

        if i < len(times) and times[i] is not None and start_dt is not None:
            abs_dt = start_dt + timedelta(seconds=int(times[i]))
            parts.append(f'<time>{abs_dt.strftime("%Y-%m-%dT%H:%M:%SZ")}</time>')

        if has_extensions:
            ext_inner = []
            if i < len(heartrate) and heartrate[i] is not None:
                ext_inner.append(f'<gpxtpx:hr>{int(heartrate[i])}</gpxtpx:hr>')
            if i < len(cadence) and cadence[i] is not None:
                ext_inner.append(f'<gpxtpx:cad>{int(cadence[i])}</gpxtpx:cad>')
            if i < len(watts) and watts[i] is not None:
                ext_inner.append(f'<gpxtpx:power>{int(watts[i])}</gpxtpx:power>')
            if i < len(temp) and temp[i] is not None:
                ext_inner.append(f'<gpxtpx:atemp>{temp[i]:.1f}</gpxtpx:atemp>')
            if ext_inner:
                parts.append(
                    '<extensions><gpxtpx:TrackPointExtension>'
                    + ''.join(ext_inner)
                    + '</gpxtpx:TrackPointExtension></extensions>'
                )

        inner = ''.join(parts)
        lines.append(f'    <trkpt lat="{lat:.7f}" lon="{lng:.7f}">{inner}</trkpt>')

    lines += ['  </trkseg></trk>', '</gpx>']
    return "\n".join(lines)


def _xe(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))
