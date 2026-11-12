"""
Módulo de Verificación Externa y Cloud ASR (ElevenLabs Scribe / Speech-to-Text).
Solo opera cuando CLIP_ASR_CLOUD_ENABLED=true y existe ELEVENLABS_API_KEY.
Se utiliza exclusivamente para verificar segmentos de baja confianza sin enviar
el video completo, ahorrando cuota, ancho de banda y latencia.
"""

import os
import json
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger("ElevenLabsScribe")


class ElevenLabsScribeVerifier:
    """
    Cliente liviano para verificación de fragmentos dudosos vía ElevenLabs STT API.
    Totalmente seguro: no almacena keys en código, solo lee de variables de entorno.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self.endpoint = "https://api.elevenlabs.io/v1/speech-to-text"

    @property
    def is_available(self) -> bool:
        """Verifica si el servicio está configurado y habilitado por el usuario."""
        cloud_enabled = os.environ.get("CLIP_ASR_CLOUD_ENABLED", "0").lower() in ("1", "true")
        return bool(self.api_key and cloud_enabled)

    def verify_audio_clip(
        self,
        audio_clip_path: str,
        language_code: str = "es",
        timeout_seconds: int = 15
    ) -> Optional[Dict[str, Any]]:
        """
        Envía un pequeño fragmento de audio (ej. 3-5 segundos) para resolver dudas fonéticas.
        Retorna la transcripción con palabras y confianza, o None si hay error o está desactivado.
        """
        if not self.is_available:
            logger.debug("ElevenLabs Scribe no está habilitado o falta ELEVENLABS_API_KEY. Omitiendo.")
            return None

        p = Path(audio_clip_path)
        if not p.exists():
            logger.warning(f"Audio para verificar no encontrado: {audio_clip_path}")
            return None

        try:
            boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
            body = []

            # Part 1: language_code
            body.append(f"--{boundary}".encode("utf-8"))
            body.append(b'Content-Disposition: form-data; name="language_code"')
            body.append(b"")
            body.append(language_code.encode("utf-8"))

            # Part 2: file
            body.append(f"--{boundary}".encode("utf-8"))
            body.append(f'Content-Disposition: form-data; name="file"; filename="{p.name}"'.encode("utf-8"))
            body.append(b"Content-Type: audio/wav")
            body.append(b"")
            with open(p, "rb") as f:
                body.append(f.read())

            body.append(f"--{boundary}--".encode("utf-8"))
            body.append(b"")
            payload = b"\r\n".join(body)

            req = urllib.request.Request(
                self.endpoint,
                data=payload,
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": f"multipart/form-data; boundary={boundary}"
                }
            )

            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {
                    "text": data.get("text", "").strip(),
                    "words": data.get("words", []),
                    "language_code": data.get("language_code", language_code)
                }

        except urllib.error.HTTPError as e:
            logger.warning(f"Error HTTP en ElevenLabs Scribe API ({e.code}): {e.reason}")
            return None
        except Exception as e:
            logger.warning(f"Fallo de conexión o timeout con ElevenLabs Scribe: {e}")
            return None
