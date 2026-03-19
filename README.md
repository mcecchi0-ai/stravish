# stravish

Strava-like performance tracker with nifty and extra features. Can fetch activities and efforts from Strava and store them persistently.

Ex.:
python3 run.py run IpBike_67.gpx
python3 run.py run <folder>
python3 run.py serve
python3.exe run.py --verbose serve
python3 run.py auth login
python3 run.py cache clear

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
