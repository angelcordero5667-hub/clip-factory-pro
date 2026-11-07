"""Seguimiento de rostros por muestreo (1 muestra por segundo).

Backends, en orden de preferencia:
1. YuNet (`cv2.FaceDetectorYN`) si el modelo ONNX existe en `settings.face_model_path`.
   Es el único disponible con OpenCV >= 5, que ya no trae Haar cascades.
2. Haar cascade (`cv2.CascadeClassifier`) si la versión de OpenCV lo incluye (4.x).
3. Sin backend -> `available == False` y el pipeline usa el layout con fondo desenfocado.
"""
import logging
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2

from src.common.config import settings
from src.agents.agent3_clip_generator.framing import FaceSample

logger = logging.getLogger("Agent3_FaceTracker")

# detect(frame_bgr) -> lista de (centro_x_normalizado, ancho_normalizado)
Detector = Callable[["cv2.Mat"], List[Tuple[float, float]]]

MAX_FRAME_WIDTH = 640     # los frames se reducen para acelerar la detección
MIN_FACE_WIDTH_RATIO = 0.04


def _make_yunet(frame_w: int, frame_h: int) -> Optional[Detector]:
    model = Path(settings.face_model_path)
    if not (hasattr(cv2, "FaceDetectorYN") and model.exists()):
        return None
    try:
        det = cv2.FaceDetectorYN.create(str(model), "", (frame_w, frame_h), 0.7, 0.3, 20)
    except Exception as e:  # modelo corrupto o API distinta
        logger.warning(f"No se pudo cargar YuNet: {e}")
        return None

    def detect(frame):
        det.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = det.detect(frame)
        out = []
        if faces is not None:
            for f in faces:
                x, y, w, h = f[:4]
                out.append(((x + w / 2) / frame.shape[1], w / frame.shape[1]))
        return out

    return detect


def _make_haar() -> Optional[Detector]:
    if not (hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades")):
        return None
    try:
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            return None
    except Exception:
        return None

    def detect(frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        min_w = max(24, int(frame.shape[1] * MIN_FACE_WIDTH_RATIO))
        faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(min_w, min_w))
        return [((x + w / 2) / frame.shape[1], w / frame.shape[1]) for (x, y, w, h) in faces]

    return detect


def backend_name() -> str:
    if hasattr(cv2, "FaceDetectorYN") and Path(settings.face_model_path).exists():
        return "yunet"
    if _make_haar() is not None:
        return "haar"
    return "ninguno"


class FaceTracker:
    """Muestrea el clip una vez por segundo y devuelve las posiciones de rostros."""

    def __init__(self, detector_factory: Optional[Callable[[int, int], Optional[Detector]]] = None):
        # Inyectable para pruebas. Por defecto: YuNet -> Haar.
        self._factory = detector_factory

    def _build(self, w: int, h: int) -> Optional[Detector]:
        if self._factory:
            return self._factory(w, h)
        return _make_yunet(w, h) or _make_haar()

    @property
    def available(self) -> bool:
        if self._factory:
            return True
        return backend_name() != "ninguno"

    def sample(
        self, video_path: str, start_time: float, duration: float, step: float = 1.0
    ) -> Tuple[List[FaceSample], int, int]:
        """Devuelve (muestras, ancho_fuente, alto_fuente). Lista vacía si no hay backend o falla."""
        cap = cv2.VideoCapture(str(video_path))
        try:
            src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if src_w <= 0 or src_h <= 0:
                return [], 0, 0
            scale = min(1.0, MAX_FRAME_WIDTH / src_w)
            small = (int(src_w * scale), int(src_h * scale))
            detector = self._build(*small)
            if detector is None:
                return [], src_w, src_h

            samples: List[FaceSample] = []
            t = 0.0
            while t < duration:
                cap.set(cv2.CAP_PROP_POS_MSEC, (start_time + t) * 1000.0)
                ok, frame = cap.read()
                if not ok:
                    break
                if scale < 1.0:
                    frame = cv2.resize(frame, small, interpolation=cv2.INTER_AREA)
                faces = [f for f in detector(frame) if f[1] >= MIN_FACE_WIDTH_RATIO]
                # los rostros más grandes primero (hablante principal), máx. 2; salida ordenada por x
                faces = sorted(faces, key=lambda f: f[1], reverse=True)[:2]
                samples.append(FaceSample(t=round(t, 2), xs=sorted(f[0] for f in faces)))
                t += step
            return samples, src_w, src_h
        except Exception as e:
            logger.debug(f"Error en seguimiento de rostros: {e}")
            return [], 0, 0
        finally:
            cap.release()
