import os
import json
import logging
from pathlib import Path
from typing import Optional

from src.common.config import settings
from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp
from src.agents.agent1_transcription.dominican_slang import (
    DOMINICAN_INITIAL_PROMPT,
    normalize_dominican_segments,
    correct_dominican_text
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("Agent1_Transcription")

class AudioTranscriber:
    """
    Agente 1: Responsable de extraer el audio, realizar la transcripción fonética y
    temporal precisa con marcas a nivel palabra (word-level timestamps) y VAD.
    Optimizado para CPU AMD Ryzen 7 5825U (INT8, multihilos).
    """

    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        cpu_threads: Optional[int] = None
    ):
        self.model_size = model_size or settings.hardware.whisper_model_size
        self.device = device or settings.hardware.device
        self.compute_type = compute_type or settings.hardware.compute_type
        self.cpu_threads = cpu_threads or settings.hardware.cpu_threads
        self._model = None

    def load_model(self):
        """Carga perezosa del modelo Faster-Whisper para preservar memoria RAM."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                logger.info(
                    f"Cargando modelo Faster-Whisper [{self.model_size}] "
                    f"en {self.device.upper()} ({self.compute_type}) con {self.cpu_threads} hilos..."
                )
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                    download_root=str(settings.cache_dir / "whisper_models")
                )
                logger.info("Modelo Faster-Whisper cargado exitosamente.")
            except ImportError:
                logger.error("faster-whisper no está instalado. Ejecuta: pip install faster-whisper")
                raise

    def transcribe(
        self,
        video_or_audio_path: str,
        language: Optional[str] = None,
        vad_filter: bool = True,
        initial_prompt: Optional[str] = None,
        dominican_mode: bool = True,
        use_llm: bool = False
    ) -> TranscriptResult:
        """
        Transcribe un archivo de video o audio generando timestamps por palabra.
        Si dominican_mode es True, condiciona el modelo y normaliza la jerga dominicana.
        """
        path = Path(video_or_audio_path)
        if not path.exists():
            raise FileNotFoundError(f"No existe el archivo: {video_or_audio_path}")

        self.load_model()

        # Determinar prompt contextual previo para guiar el modelo
        prompt = initial_prompt
        if prompt is None and dominican_mode:
            prompt = DOMINICAN_INITIAL_PROMPT
            logger.info("Modo Jerga Dominicana activado: inyectando contexto urbano y de dembow en Faster-Whisper.")

        logger.info(f"Iniciando transcripción para: {path.name}")
        segments_raw, info = self._model.transcribe(
            str(path),
            language=language,
            word_timestamps=True,
            beam_size=1,
            condition_on_previous_text=False,
            vad_filter=vad_filter,
            vad_parameters=dict(min_silence_duration_ms=500),
            initial_prompt=prompt
        )

        detected_language = info.language
        duration = info.duration
        logger.info(f"Idioma detectado: {detected_language} (probabilidad: {info.language_probability:.2f}), Duración: {duration:.2f}s")

        parsed_segments = []
        full_text_chunks = []

        for seg_idx, seg in enumerate(segments_raw):
            words_list = []
            if seg.words:
                for w in seg.words:
                    words_list.append(
                        WordTimestamp(
                            word=w.word.strip(),
                            start=round(w.start, 3),
                            end=round(w.end, 3),
                            probability=round(w.probability, 3)
                        )
                    )

            text_cleaned = seg.text.strip()
            full_text_chunks.append(text_cleaned)

            parsed_segments.append(
                TranscriptSegment(
                    id=seg_idx,
                    start=round(seg.start, 3),
                    end=round(seg.end, 3),
                    text=text_cleaned,
                    words=words_list
                )
            )

        if dominican_mode and parsed_segments:
            logger.info("Aplicando normalización de fonética y jerga urbana dominicana a los segmentos...")
            parsed_segments = normalize_dominican_segments(parsed_segments, use_llm=use_llm)
            full_text_chunks = [s.text for s in parsed_segments]

        full_transcript = TranscriptResult(
            video_path=str(path.resolve()),
            language=detected_language,
            duration=round(duration, 3),
            segments=parsed_segments,
            full_text=" ".join(full_text_chunks)
        )

        return full_transcript

    def save_transcript_json(self, transcript: TranscriptResult, output_path: str) -> str:
        """Guarda el resultado estructurado de la transcripción en JSON."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(transcript.model_dump(), f, ensure_ascii=False, indent=2)
        logger.info(f"Transcripción guardada en: {out}")
        return str(out)

