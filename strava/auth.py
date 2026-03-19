"""
strava/auth.py

OAuth2 flow per Strava via stravalib.
Gestisce login browser, salvataggio token e refresh automatico.

Setup:
  1. https://www.strava.com/settings/api → crea app, callback domain = localhost
  2. Copia client_id e client_secret in config.yml
  3. python run.py auth login
"""

import json
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from stravalib.client import Client

TOKEN_FILE = Path.home() / ".strava-oss" / "tokens.json"
REDIRECT_PORT = 8765
REDIRECT_URI = "http://localhost:{}/callback".format(REDIRECT_PORT)


class _CallbackHandler(BaseHTTPRequestHandler):
    auth_code = None
    error = None

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _CallbackHandler.auth_code = params["code"][0]
            self._respond("Autorizzazione ricevuta. Puoi chiudere questa finestra.")
        else:
            _CallbackHandler.error = params.get("error", ["unknown"])[0]
            self._respond("Errore: {}".format(_CallbackHandler.error))

    def _respond(self, msg):
        body = "<html><body><h2>{}</h2></body></html>".format(msg).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class StravaAuth:

    def __init__(self, client_id, client_secret):
        self.client_id = str(client_id)
        self.client_secret = client_secret

    def get_valid_access_token(self):
        tokens = self._load_tokens()
        if not tokens:
            return None
        client = Client()
        # Refresh automatico se scaduto (margine 5 min)
        if time.time() > tokens["expires_at"] - 300:
            refreshed = client.refresh_access_token(
                client_id=self.client_id,
                client_secret=self.client_secret,
                refresh_token=tokens["refresh_token"],
            )
            tokens.update({
                "access_token":  refreshed["access_token"],
                "refresh_token": refreshed["refresh_token"],
                "expires_at":    refreshed["expires_at"],
            })
            self._save_tokens(tokens)
        return tokens["access_token"]

    def login(self):
        client = Client()
        auth_url = client.authorization_url(
            client_id=self.client_id,
            redirect_uri=REDIRECT_URI,
            scope=["read", "activity:read_all"],
        )

        print("\nApertura browser per autorizzazione Strava...")
        print("Se non si apre, vai a:\n{}\n".format(auth_url))
        webbrowser.open(auth_url)

        _CallbackHandler.auth_code = None
        _CallbackHandler.error = None
        server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
        server.timeout = 120
        print("In attesa su localhost:{}...".format(REDIRECT_PORT))

        while _CallbackHandler.auth_code is None and _CallbackHandler.error is None:
            server.handle_request()
        server.server_close()

        if _CallbackHandler.error:
            print("Autorizzazione rifiutata: {}".format(_CallbackHandler.error))
            return False

        token_response = client.exchange_code_for_token(
            client_id=self.client_id,
            client_secret=self.client_secret,
            code=_CallbackHandler.auth_code,
        )
        tokens = {
            "access_token":  token_response["access_token"],
            "refresh_token": token_response["refresh_token"],
            "expires_at":    token_response["expires_at"],
        }
        self._save_tokens(tokens)

        client.access_token = tokens["access_token"]
        athlete = client.get_athlete()
        print("Autenticato come: {} {}".format(athlete.firstname, athlete.lastname))
        print("Token salvato in: {}".format(TOKEN_FILE))
        return True

    def logout(self):
        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()
            print("Token rimosso.")
        else:
            print("Nessun token salvato.")

    def force_refresh(self):
        """Forza il refresh del token, anche se non ancora scaduto."""
        tokens = self._load_tokens()
        if not tokens or "refresh_token" not in tokens:
            return {"ok": False, "error": "no_token"}
        client = Client()
        try:
            refreshed = client.refresh_access_token(
                client_id=self.client_id,
                client_secret=self.client_secret,
                refresh_token=tokens["refresh_token"],
            )
            tokens.update({
                "access_token":  refreshed["access_token"],
                "refresh_token": refreshed["refresh_token"],
                "expires_at":    refreshed["expires_at"],
            })
            self._save_tokens(tokens)
            return {
                "ok": True,
                "expires_in_seconds": max(0, int(tokens["expires_at"] - time.time())),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def status(self):
        tokens = self._load_tokens()
        if not tokens:
            return {"authenticated": False}
        expired = time.time() > tokens["expires_at"] - 300
        return {
            "authenticated": True,
            "expired": expired,
            "expires_in_seconds": max(0, int(tokens["expires_at"] - time.time())),
        }

    @staticmethod
    def _load_tokens():
        if not TOKEN_FILE.exists():
            return None
        try:
            return json.loads(TOKEN_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _save_tokens(tokens):
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
        TOKEN_FILE.chmod(0o600)
