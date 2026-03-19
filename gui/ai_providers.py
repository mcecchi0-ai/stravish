"""
gui/ai_providers.py — Provider LLM astratti per analisi AI attività.

Ogni provider implementa:
  - id, name, default_model
  - auth_fields: lista di campi richiesti per l'autenticazione
  - models: lista modelli disponibili
  - complete(prompt, model, settings) → str

Supportati: Gemini, OpenAI, OpenRouter, Groq, Mistral, Ollama (locale).
"""

import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


# ── Base ─────────────────────────────────────────────────────────

class AIProvider:
    """Classe base — ogni sottoclasse = un fornitore LLM."""

    id: str = ""
    name: str = ""
    default_model: str = ""
    models: list = []
    auth_fields: list = []        # [{"key": "api_key", "label": "API Key", "type": "password"}]
    hint_html: dict = {}          # {"it": "...", "en": "..."}
    timeout_s: int = 120

    def complete(self, prompt: str, model, auth: dict) -> str:
        """Invia il prompt e restituisce il testo generato."""
        raise NotImplementedError

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "default_model": self.default_model,
            "models": self.models,
            "auth_fields": self.auth_fields,
            "hint_html": self.hint_html,
        }

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _http_post(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
        """POST JSON generico con urllib (nessuna dipendenza esterna)."""
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            body = he.read().decode("utf-8", errors="replace")[:500]
            logger.error("%s HTTP %s: %s", url, he.code, body)
            # Messaggi user-friendly per errori comuni
            if he.code == 429:
                # Tenta di estrarre il tipo di errore dal body JSON
                quota_hint = ""
                try:
                    err_json = json.loads(body)
                    err_type = (err_json.get("error", {}).get("code", "")
                                or err_json.get("error", {}).get("type", ""))
                    if "quota" in err_type or "billing" in str(err_json):
                        quota_hint = " Verifica il piano di billing del provider."
                except Exception:
                    pass
                raise RuntimeError(
                    f"Quota/rate-limit esaurito (HTTP 429).{quota_hint}"
                    f" Prova un provider gratuito come OpenRouter."
                )
            if he.code in (401, 403):
                raise RuntimeError(
                    f"Chiave API non valida o non autorizzata (HTTP {he.code})."
                    f" Controlla la chiave nelle impostazioni."
                )
            raise RuntimeError(f"HTTP {he.code}: {body}")


# ── Gemini (Google) ──────────────────────────────────────────────

class GeminiProvider(AIProvider):
    id = "gemini"
    name = "Google Gemini"
    default_model = "gemini-2.0-flash"
    models = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    auth_fields = [
        {"key": "api_key", "label": "API Key", "type": "password", "placeholder": "AIza…"},
    ]
    hint_html = {
        "it": 'Chiave gratuita su <a href="https://aistudio.google.com/apikey" target="_blank" style="color:var(--blue)">aistudio.google.com</a>',
        "en": 'Free key at <a href="https://aistudio.google.com/apikey" target="_blank" style="color:var(--blue)">aistudio.google.com</a>',
    }

    def complete(self, prompt, model, auth):
        api_key = (auth.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("Gemini API key mancante")
        model = model or self.default_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        body = self._http_post(url, {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048},
        }, {"Content-Type": "application/json"}, self.timeout_s)
        return body["candidates"][0]["content"]["parts"][0]["text"]


# ── OpenAI ───────────────────────────────────────────────────────

class OpenAIProvider(AIProvider):
    id = "openai"
    name = "OpenAI"
    default_model = "gpt-4o-mini"
    models = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1-nano", "o4-mini"]
    auth_fields = [
        {"key": "api_key", "label": "API Key", "type": "password", "placeholder": "sk-…"},
    ]
    hint_html = {
        "it": 'Chiave su <a href="https://platform.openai.com/api-keys" target="_blank" style="color:var(--blue)">platform.openai.com</a>',
        "en": 'Key at <a href="https://platform.openai.com/api-keys" target="_blank" style="color:var(--blue)">platform.openai.com</a>',
    }

    def complete(self, prompt, model, auth):
        api_key = (auth.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("OpenAI API key mancante")
        model = model or self.default_model
        body = self._http_post(
            "https://api.openai.com/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 2048,
            },
            {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            self.timeout_s,
        )
        return body["choices"][0]["message"]["content"]


# ── OpenRouter ───────────────────────────────────────────────────

class OpenRouterProvider(AIProvider):
    id = "openrouter"
    name = "OpenRouter"
    default_model = "google/gemini-2.0-flash-exp:free"
    models = [
        "google/gemini-2.0-flash-exp:free",
        "deepseek/deepseek-chat-v3-0324:free",
        "qwen/qwen3-235b-a22b:free",
        "meta-llama/llama-4-maverick",
        "meta-llama/llama-4-scout",
    ]
    auth_fields = [
        {"key": "api_key", "label": "API Key", "type": "password", "placeholder": "sk-or-…"},
    ]
    hint_html = {
        "it": 'Chiave su <a href="https://openrouter.ai/keys" target="_blank" style="color:var(--blue)">openrouter.ai</a> — molti modelli gratuiti',
        "en": 'Key at <a href="https://openrouter.ai/keys" target="_blank" style="color:var(--blue)">openrouter.ai</a> — many free models',
    }

    def complete(self, prompt, model, auth):
        api_key = (auth.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("OpenRouter API key mancante")
        model = model or self.default_model
        body = self._http_post(
            "https://openrouter.ai/api/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 2048,
            },
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/stravish",
            },
            self.timeout_s,
        )
        return body["choices"][0]["message"]["content"]


# ── Groq ─────────────────────────────────────────────────────────

class GroqProvider(AIProvider):
    id = "groq"
    name = "Groq"
    default_model = "llama-3.3-70b-versatile"
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it", "mixtral-8x7b-32768"]
    auth_fields = [
        {"key": "api_key", "label": "API Key", "type": "password", "placeholder": "gsk_…"},
    ]
    hint_html = {
        "it": 'Chiave gratuita su <a href="https://console.groq.com/keys" target="_blank" style="color:var(--blue)">console.groq.com</a>',
        "en": 'Free key at <a href="https://console.groq.com/keys" target="_blank" style="color:var(--blue)">console.groq.com</a>',
    }

    def complete(self, prompt, model, auth):
        api_key = (auth.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("Groq API key mancante")
        model = model or self.default_model
        body = self._http_post(
            "https://api.groq.com/openai/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 2048,
            },
            {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            self.timeout_s,
        )
        return body["choices"][0]["message"]["content"]


# ── Mistral ──────────────────────────────────────────────────────

class MistralProvider(AIProvider):
    id = "mistral"
    name = "Mistral AI"
    default_model = "mistral-small-latest"
    models = ["mistral-small-latest", "mistral-medium-latest", "mistral-large-latest", "open-mistral-nemo"]
    auth_fields = [
        {"key": "api_key", "label": "API Key", "type": "password", "placeholder": "…"},
    ]
    hint_html = {
        "it": 'Chiave su <a href="https://console.mistral.ai/api-keys" target="_blank" style="color:var(--blue)">console.mistral.ai</a>',
        "en": 'Key at <a href="https://console.mistral.ai/api-keys" target="_blank" style="color:var(--blue)">console.mistral.ai</a>',
    }

    def complete(self, prompt, model, auth):
        api_key = (auth.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("Mistral API key mancante")
        model = model or self.default_model
        body = self._http_post(
            "https://api.mistral.ai/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 2048,
            },
            {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            self.timeout_s,
        )
        return body["choices"][0]["message"]["content"]


# ── Ollama (locale) ──────────────────────────────────────────────

class OllamaProvider(AIProvider):
    id = "ollama"
    name = "Ollama (locale)"
    default_model = "llama3.1"
    models = ["llama3.1", "llama3.2", "gemma2", "mistral", "qwen2.5"]
    auth_fields = [
        {"key": "base_url", "label": "URL", "type": "text", "placeholder": "http://localhost:11434"},
    ]
    hint_html = {
        "it": 'Nessuna chiave — richiede <a href="https://ollama.com" target="_blank" style="color:var(--blue)">Ollama</a> in esecuzione locale',
        "en": 'No key needed — requires <a href="https://ollama.com" target="_blank" style="color:var(--blue)">Ollama</a> running locally',
    }

    def complete(self, prompt, model, auth):
        base_url = (auth.get("base_url") or "http://localhost:11434").rstrip("/")
        model = model or self.default_model
        body = self._http_post(
            f"{base_url}/api/chat",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.7},
            },
            {"Content-Type": "application/json"},
            300,  # timeout più generoso per modelli locali
        )
        return body["message"]["content"]


# ── Registry ─────────────────────────────────────────────────────

PROVIDERS = {}

def _register(*classes):
    for cls in classes:
        p = cls()
        PROVIDERS[p.id] = p

_register(
    GeminiProvider,
    OpenAIProvider,
    OpenRouterProvider,
    GroqProvider,
    MistralProvider,
    OllamaProvider,
)


def get_provider(provider_id: str) -> AIProvider:
    """Ritorna il provider per id, o ValueError."""
    p = PROVIDERS.get(provider_id)
    if not p:
        raise ValueError(f"Provider sconosciuto: {provider_id}")
    return p


def list_providers() -> list[dict]:
    """Lista serializzabile per la UI."""
    return [p.to_dict() for p in PROVIDERS.values()]
