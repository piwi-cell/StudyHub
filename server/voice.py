"""Sprache über ElevenLabs: Speech-to-Text (Antwort einsprechen), Text-to-Speech (Tutor spricht)
und Signed URLs für den Gesprächsmodus mit einem ElevenLabs Agent.

Der API-Key liegt im Schlüsselbund und verlässt den lokalen Server nie; der Browser
schickt nur Audio hin und bekommt fertiges Audio (MP3) bzw. eine kurzlebige Signed URL zurück.
"""

import os

import httpx2 as httpx  # kommt mit dem Anthropic-SDK, gleiche API wie httpx
import keyring

import core

API = "https://api.elevenlabs.io/v1"
KEY_ACCOUNT = "ElevenLabs-API-Key"
STT_MODEL = "scribe_v2"
TTS_MODEL = "eleven_multilingual_v2"  # spricht Deutsch
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"  # Beispielstimme aus der ElevenLabs-Doku; in den Einstellungen änderbar
MAX_TTS_CHARS = 1500
AUDIO_SUFFIX = {"audio/webm": "webm", "audio/mp4": "mp4", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/wav": "wav"}


class VoiceError(Exception):
    pass


def api_key() -> str | None:
    return keyring.get_password(core.KEYCHAIN_SERVICE, KEY_ACCOUNT) or os.environ.get("ELEVENLABS_API_KEY")


def set_api_key(key: str) -> None:
    if key:
        keyring.set_password(core.KEYCHAIN_SERVICE, KEY_ACCOUNT, key.strip())
    else:
        try:
            keyring.delete_password(core.KEYCHAIN_SERVICE, KEY_ACCOUNT)
        except keyring.errors.PasswordDeleteError:
            pass


def _headers() -> dict:
    key = api_key()
    if not key:
        raise VoiceError("Kein ElevenLabs-API-Key hinterlegt (Einstellungen › Tutor)")
    return {"xi-api-key": key}


def _check(response) -> None:
    if response.status_code < 400:
        return
    try:
        detail = response.json().get("detail")
        detail = detail.get("message", "") if isinstance(detail, dict) else str(detail or "")
    except ValueError:
        detail = ""
    raise VoiceError({401: "ElevenLabs-API-Key ungültig", 429: "ElevenLabs-Limit oder Guthaben erreicht"}
                     .get(response.status_code) or f"ElevenLabs-Fehler {response.status_code}: {detail[:200]}")


def transcribe(audio: bytes, content_type: str, language: str = "de") -> str:
    """Audio aus dem Browser (webm/mp4/ogg) → Text."""
    if len(audio) < 1000:
        raise VoiceError("Aufnahme zu kurz, Taste etwas länger gedrückt halten")
    mime = content_type.split(";")[0].strip().lower()
    filename = f"antwort.{AUDIO_SUFFIX.get(mime, 'webm')}"
    try:
        response = httpx.post(f"{API}/speech-to-text", headers=_headers(), timeout=60,
                              data={"model_id": STT_MODEL, "language_code": language},
                              files={"file": (filename, audio, mime or "application/octet-stream")})
    except httpx.HTTPError:
        raise VoiceError("Keine Verbindung zu ElevenLabs") from None
    _check(response)
    return (response.json().get("text") or "").strip()


def speak(text: str, voice_id: str | None = None) -> bytes:
    """Text → MP3."""
    text = text.strip()[:MAX_TTS_CHARS]
    if not text:
        raise VoiceError("Kein Text zum Vorlesen")
    try:
        response = httpx.post(f"{API}/text-to-speech/{voice_id or DEFAULT_VOICE}", headers=_headers(), timeout=60,
                              params={"output_format": "mp3_44100_128"},
                              json={"text": text, "model_id": TTS_MODEL})
    except httpx.HTTPError:
        raise VoiceError("Keine Verbindung zu ElevenLabs") from None
    _check(response)
    return response.content


def signed_url(agent_id: str) -> str:
    """Kurzlebige URL, mit der der Browser ein Gespräch mit dem Agent startet (Agent mit Authentifizierung)."""
    if not agent_id.strip():
        raise VoiceError("Keine ElevenLabs Agent-ID hinterlegt (Einstellungen › Study-Tutor)")
    try:
        response = httpx.get(f"{API}/convai/conversation/get-signed-url", headers=_headers(), timeout=20,
                             params={"agent_id": agent_id.strip()})
    except httpx.HTTPError:
        raise VoiceError("Keine Verbindung zu ElevenLabs") from None
    if response.status_code == 404:
        raise VoiceError("ElevenLabs-Agent nicht gefunden, Agent-ID prüfen")
    _check(response)
    url = response.json().get("signed_url")
    if not url:
        raise VoiceError("ElevenLabs hat keine Signed URL geliefert")
    return url
