from typing import Optional
# sys.path fix — MUST be before any local imports
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

"""
cli/__main__.py — strava-oss-segmentizer

Uso:
    python run.py --help
    python run.py auth login
    python run.py auth status
    python run.py auth logout
    python run.py run FILE.gpx
    python run.py run FILE.gpx --type running --output results.json
    python run.py cache stats
    python run.py cache clear
"""

import argparse
import json
import logging
import yaml

from strava.auth import StravaAuth
from segmentizer.pipeline import Segmentizer


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def load_config(config_path):
    p = Path(config_path)
    if not p.exists():
        print("❌ Config non trovata: {}".format(config_path))
        print("   Compila client_id e client_secret in config.yml")
        sys.exit(1)
    with open(p) as f:
        return yaml.safe_load(f)


def setup_logging(verbose):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s", level=level)


def make_auth(config):
    strava_cfg = config.get("strava", {})
    client_id = strava_cfg.get("client_id", "")
    client_secret = strava_cfg.get("client_secret", "")
    if not client_id or not client_secret:
        print("❌ client_id e client_secret mancanti in config.yml")
        print("   Registra un'app su https://www.strava.com/settings/api")
        sys.exit(1)
    return StravaAuth(client_id, client_secret)


def format_time(seconds):
    # type: (Optional[float]) -> str
    if seconds is None:
        return "N/A"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return "{}h {:02d}m {:02d}s".format(h, m, s)
    return "{}m {:02d}s".format(m, s)


def format_distance(meters):
    if meters >= 1000:
        return "{:.2f} km".format(meters / 1000)
    return "{:.0f} m".format(meters)


# ------------------------------------------------------------------
# auth
# ------------------------------------------------------------------

def cmd_auth_login(args, config):
    auth = make_auth(config)
    success = auth.login()
    sys.exit(0 if success else 1)


def cmd_auth_status(args, config):
    auth = make_auth(config)
    status = auth.status()
    if not status["authenticated"]:
        print("❌ Non autenticato. Esegui: python run.py auth login")
        sys.exit(1)
    if status["expired"]:
        print("⚠️  Token scaduto (verrà rinnovato automaticamente alla prossima run)")
    else:
        mins = status["expires_in_seconds"] // 60
        print("✅ Autenticato | Token valido per ancora {} minuti".format(mins))
    if status.get("athlete_id"):
        print("   Athlete ID: {}".format(status["athlete_id"]))


def cmd_auth_logout(args, config):
    make_auth(config).logout()


# ------------------------------------------------------------------
# run
# ------------------------------------------------------------------

def _resolve_token(args, config):
    """Recupera e inietta il token Strava nel config. Ritorna True se disponibile."""
    auth = make_auth(config)
    token = auth.get_valid_access_token()
    if token:
        config["strava"]["access_token"] = token
        return True
    print("⚠️  Nessun token Strava — uso cache locale e auto-detection")
    print("   Per autenticarti: python run.py auth login\n")
    return False


def _serialize_results(results):
    serializable = {k: v for k, v in results.items() if k != "segments_matched"}
    serializable["segments_matched"] = [
        seg.__dict__ for seg in results["segments_matched"]
    ]
    return serializable


def cmd_run(args, config):
    _resolve_token(args, config)

    # Determina se è un file singolo o una cartella
    target = Path(args.gpx)
    if target.is_dir():
        _cmd_run_folder(args, config, target)
    else:
        _cmd_run_single(args, config, target)


def _cmd_run_single(args, config, gpx_path):
    if not gpx_path.exists():
        print("❌ File non trovato: {}".format(gpx_path))
        sys.exit(1)

    print("📂 Processing: {}".format(gpx_path.name))

    try:
        s = Segmentizer(config=config)
        results = s.process(str(gpx_path), activity_type=args.type)
    except Exception as e:
        print("❌ Errore: {}".format(e))
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    _print_results(results, gpx_path.name)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(_serialize_results(results), indent=2, default=str))
        print("\n💾 Risultati salvati in: {}".format(out_path))


def _cmd_run_folder(args, config, folder):
    gpx_files = sorted(folder.glob("**/*.gpx") if args.recursive else folder.glob("*.gpx"))

    if not gpx_files:
        print("❌ Nessun file .gpx trovato in: {}".format(folder))
        sys.exit(1)

    print("📁 Cartella: {}".format(folder))
    print("   {} file GPX trovati{}\n".format(
        len(gpx_files),
        " (ricerca ricorsiva)" if args.recursive else ""
    ))

    s = Segmentizer(config=config)

    all_results = []
    ok = 0
    errors = 0

    for i, gpx_path in enumerate(gpx_files, 1):
        print("[{}/{}] {}".format(i, len(gpx_files), gpx_path.name), end=" ... ", flush=True)
        try:
            results = s.process(str(gpx_path), activity_type=args.type)
            status = "reimport" if results["reimport"] else "importata"
            dist = results["gpx_stats"]["total_distance_m"]
            print("✓  {} ({:.1f} km)".format(status, dist / 1000))
            all_results.append({"file": str(gpx_path), "results": _serialize_results(results)})
            ok += 1
        except Exception as e:
            print("❌ {}".format(e))
            if args.verbose:
                import traceback
                traceback.print_exc()
            errors += 1

    # Riepilogo finale
    print("\n" + "─" * 55)
    print("  Completati: {}  |  Errori: {}  |  Cache: {} segmenti".format(
        ok, errors, s.cache.count()
    ))
    print("─" * 55)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(all_results, indent=2, default=str))
        print("\n💾 Risultati bulk salvati in: {}".format(out_path))


def _print_results(results, filename):
    stats = results["gpx_stats"]

    print("\n" + "─" * 55)
    print("  {}".format(filename))
    print("─" * 55)
    print("  Distanza totale : {}".format(format_distance(stats["total_distance_m"])))
    print("  Dislivello +    : {:.0f} m".format(stats["total_elevation_gain_m"]))
    print("  Punti GPS       : {}".format(stats["num_points"]))
    print("  Stato           : {}".format("già presente" if results["reimport"] else "importata"))
    print("─" * 55)


# ------------------------------------------------------------------
# cache
# ------------------------------------------------------------------

def cmd_cache_stats(args, config):
    from cache.db import SegmentCache, resolve_cache_db_path
    cache = SegmentCache(str(resolve_cache_db_path(config.get("cache", {}))))
    conn = cache._conn
    total  = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
    strava = conn.execute("SELECT COUNT(*) FROM segments WHERE source='strava'").fetchone()[0]
    auto   = conn.execute("SELECT COUNT(*) FROM segments WHERE source='auto'").fetchone()[0]
    tiles  = conn.execute("SELECT COUNT(*) FROM fetched_tiles").fetchone()[0]
    db_path = resolve_cache_db_path(config.get("cache", {}))
    db_size = db_path.stat().st_size / 1024 if db_path.exists() else 0
    print("\n📦 Cache: {}".format(config["cache"]["db_path"]))
    print("   Segmenti : {}  (Strava: {} | auto: {})".format(total, strava, auto))
    print("   Tile     : {}".format(tiles))
    print("   Dimensione: {:.1f} KB\n".format(db_size))
    cache.close()


def cmd_cache_clear(args, config):
    from cache.db import SegmentCache, resolve_cache_db_path
    confirm = input("⚠️  Cancellare tutta la cache? [s/N] ").strip().lower()
    if confirm != "s":
        print("Operazione annullata.")
        return
    cache = SegmentCache(str(resolve_cache_db_path(config.get("cache", {}))))
    cache._conn.execute("DELETE FROM segments")
    cache._conn.execute("DELETE FROM fetched_tiles")
    cache._conn.execute("DELETE FROM efforts")
    cache._conn.execute("UPDATE activities SET strava_effort_source='local'")
    cache._conn.commit()
    cache.close()
    print("✅ Cache svuotata (segmenti, effort e stato fetch resettati).")




# ------------------------------------------------------------------
# serve
# ------------------------------------------------------------------

def cmd_serve(args, config):
    from gui.server import run_server
    run_server(config, host=args.host, port=args.port, open_browser=not args.no_browser)

# ------------------------------------------------------------------
# Parser + main
# ------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="python run.py",
        description="strava-oss-segmentizer — analisi GPX strava-like",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "esempi:\n"
            "  python run.py auth login\n"
            "  python run.py run uscita.gpx\n"
            "  python run.py run uscita.gpx --type running -o risultati.json\n"
            "  python run.py cache stats\n"
        ),
    )
    parser.add_argument("--config", default="config.yml")
    parser.add_argument("--verbose", "-v", action="store_true")

    sub = parser.add_subparsers(dest="command", metavar="comando")
    sub.required = True

    auth_p = sub.add_parser("auth", help="Gestione autenticazione Strava")
    auth_sub = auth_p.add_subparsers(dest="auth_command", metavar="azione")
    auth_sub.required = True
    auth_sub.add_parser("login",  help="Apre il browser per autorizzare l'app")
    auth_sub.add_parser("status", help="Stato del token corrente")
    auth_sub.add_parser("logout", help="Rimuovi il token salvato")

    run_p = sub.add_parser("run", help="Analizza un file GPX o una cartella di GPX")
    run_p.add_argument("gpx", metavar="FILE.gpx o CARTELLA")
    run_p.add_argument("--type", choices=["cycling", "running"], default="cycling")
    run_p.add_argument("--output", "-o", metavar="FILE.json",
                       help="Salva risultati JSON (bulk: array di tutti i file)")
    run_p.add_argument("--recursive", "-r", action="store_true",
                       help="Cerca GPX nelle sottocartelle (solo con cartella)")

    serve_p = sub.add_parser("serve", help="Avvia GUI web locale")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=5757)
    serve_p.add_argument("--no-browser", action="store_true", help="Non aprire il browser")

    cache_p = sub.add_parser("cache", help="Gestione cache locale")
    cache_sub = cache_p.add_subparsers(dest="cache_command", metavar="azione")
    cache_sub.required = True
    cache_sub.add_parser("stats", help="Statistiche cache")
    cache_sub.add_parser("clear", help="Svuota la cache")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)
    config = load_config(args.config)

    if args.command == "auth":
        {"login": cmd_auth_login, "status": cmd_auth_status, "logout": cmd_auth_logout}[args.auth_command](args, config)
    elif args.command == "run":
        cmd_run(args, config)
    elif args.command == "serve":
        cmd_serve(args, config)
    elif args.command == "cache":
        {"stats": cmd_cache_stats, "clear": cmd_cache_clear}[args.cache_command](args, config)


if __name__ == "__main__":
    main()
