# strava-oss-segmentizer

Open-source GPX segmentizer con rilevamento strava-like.

Es.:
python3 run.py run IpBike_67.gpx
python3 run.py run <cartella>
python3 run.py serve
python3 run.py auth login # rifare il token
python3 run.py cache clear
python3.exe run.py --verbose serve

## Architettura

```
strava-oss/
├── config.yml                  ← Tutti i parametri configurabili
│
├── segmentizer/
│   └── pipeline.py             ← Orchestratore principale
│
├── strava/
│   └── client.py               ← API Strava + recursive bbox tiling + rate limit
│
├── cache/
│   └── db.py                   ← SQLite cache locale (segmenti + tile fetched)
│
├── auto_detect/
│   └── detector.py             ← Rilevamento automatico climb/descent/flat
│
├── matcher/
│   └── frechet.py              ← Segment matching (Fréchet distance discreta)
│
└── utils/
    └── gpx_utils.py            ← Parse GPX, haversine, bbox
```

## Flow principale

```
GPX in input
    ↓
Parse punti + calcolo distanze cumulative
    ↓
Calcola bounding box della traccia
    ↓
Strava /segments/explore (recursive tile subdivision se ≥10 risultati)
    ↓  (cache locale, nessuna ri-fetch di tile già viste)
    ├─ Risultati → Segment matching (Fréchet distance)
    │
    └─ Nessun risultato → Auto-detection (climb/descent/flat)
                              ↓ parametri da config.yml
                          Smoothing elevazione
                              ↓
                          Gradiente punto per punto
                              ↓
                          Rilevamento run sopra soglia
                              ↓
                          Filtri (dislivello, lunghezza, pendenza media)
    ↓
Output: segmenti percorsi + elapsed time + statistiche traccia
```

## Setup Strava API (una volta sola)

### 1. Registra l'app su Strava
1. Vai su **https://www.strava.com/settings/api**
2. Crea una nuova applicazione (nome, categoria, sito — qualsiasi valore va bene)
3. Imposta **"Authorization Callback Domain"** → `localhost`
4. Copia **Client ID** e **Client Secret**


### 2. Configura config.yml
```yaml
strava:
  client_id: "1234"
  client_secret: ".ae321fb4.."
```

### 3. Login (apre il browser)
```bash
python -m cli auth login
```
Strava aprirà una pagina di autorizzazione. Dopo aver cliccato "Autorizza",
il token viene salvato automaticamente in `~/.strava-oss/tokens.json`
e rinnovato in automatico ogni 6 ore.

---

## CLI

```bash
pip install -r requirements.txt
```

### Autenticazione
```bash
python -m cli auth login       # Prima autenticazione (apre browser)
python -m cli auth status      # Controlla stato token
python -m cli auth logout      # Rimuovi token salvato
```

### Analisi GPX
```bash
# Analisi base
python -m cli run uscita.gpx

# Specificare tipo attività
python -m cli run corsa.gpx --type running

# Salvare risultati in JSON
python -m cli run uscita.gpx --output risultati.json

# Output verboso (debug)
python -m cli run uscita.gpx -v
```

### Gestione cache
```bash
python -m cli cache stats      # Quanti segmenti in cache, dimensione DB
python -m cli cache clear      # Svuota la cache (chiede conferma)
```

### GUI
python run.py serve

### Output esempio
```
───────────────────────────────────────────────────
  uscita_sabato.gpx
───────────────────────────────────────────────────
  Distanza totale : 48.32 km
  Dislivello +    : 1240 m
  Punti GPS       : 4821
  Sorgente segm.  : Strava API
  Cache locale    : 47 segmenti
───────────────────────────────────────────────────
  5 segmenti percorsi:

   1. [S] ↑ Muro di Sormano
      2.42 km  +10.3%  ⏱ 18m 34s  Δ8m
   2. [S] ↑ San Primo da Civenna
      5.10 km  +6.8%   ⏱ 24m 02s  Δ12m
   3. [A] ↓ auto ↓ -5.2% 1840m -96m
      1.84 km  -5.2%   ⏱ 4m 11s

  [S] = segmento Strava   [A] = rilevato automaticamente
```

## Configurazione auto-detection

Tutto in `config.yml` → sezione `auto_detect`:

| Parametro | Default | Descrizione |
|-----------|---------|-------------|
| `climb.min_elevation_gain_m` | 20 | Dislivello minimo salita |
| `climb.min_avg_grade_pct` | 3.0 | Pendenza media minima (%) |
| `climb.min_grade_threshold_pct` | 1.5 | Soglia per iniziare a contare la salita |
| `climb.min_length_m` | 200 | Lunghezza minima segmento |
| `climb.elevation_smoothing_window` | 7 | Finestra smoothing elevazione GPS |
| `descent.*` | simmetrico | Stessi parametri per le discese |
| `flat.enabled` | false | Rilevamento sprint/tratti pianeggianti |

## Strategia cache

La cache SQLite accumula segmenti nel tempo, guidata dalle zone geografiche degli utenti:
- Ogni tile bbox fetchata viene marcata come "già vista" → nessuna chiamata API ridondante
- I segmenti auto-rilevati hanno `source="auto"` e ID sintetico
- La cache può essere condivisa tra utenti (DB condiviso) o tenuta locale

## TODO

- [ ] Fréchet → ottimizzazione con pruning (O(n log n))
- [ ] Export risultati JSON / CSV
- [ ] CLI (`python -m segmentizer mia_uscita.gpx`)
- [ ] Test con tracce reali
- [ ] OAuth2 flow per token Strava automatico
- [ ] Elevazione da DEM (fallback quando il GPX non ha elevazione)
