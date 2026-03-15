import sys
from pathlib import Path

# Aggiunge la root del progetto al path PRIMA di qualsiasi import locale.
# Necessario quando si lancia da una directory diversa dalla root del progetto,
# es: python /Users/marcocecchi/Drive/stravish/run.py run file.gpx
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Ora tutti i moduli locali (cache, strava, matcher, …) sono risolvibili
from cli.__main__ import main

if __name__ == "__main__":
    main()
