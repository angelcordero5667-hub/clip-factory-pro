import os
import re
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple

from src.common.config import settings
from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp
from src.agents.agent1_transcription.dominican_slang import (
    DOMINICAN_INITIAL_PROMPT,
    normalize_dominican_segments,
    correct_dominican_text
)
from src.agents.agent1_transcription.hybrid_verifier import (
    HybridTranscriptionVerifier,
    QualityReviewReport
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("Agent1_Transcription")

# Sube este número cuando cambie el formato de la transcripción o la lógica que la produce
# (p. ej. la normalización de jerga): invalida de golpe todas las cachés anteriores.
TRANSCRIPT_CACHE_VERSION = 2


def transcript_cache_key(path, language=None, dominican_mode=True, model=None, compute_type=None, beam_size=None) -> str:
    """Clave estable de caché para una transcripción.

    Depende de: nombre, tamaño y fecha del archivo, idioma, modo dominicano, modelo, tipo de cálculo,
    beam y versión de la caché. Cambiar cualquiera de ellos da otra clave, así que nunca se reutiliza un
    resultado hecho con otro modelo o con otros parámetros. El nombre sale seguro para cualquier sistema
    de archivos (el resto va en un hash).
    """
    p = Path(str(path))
    try:
        st = p.stat()
        size, mtime = st.st_size, int(st.st_mtime)
    except OSError:
        size, mtime = 0, 0
    parts = [p.stem, str(size), str(mtime), str(language or "auto"), "dom1" if dominican_mode else "dom0",
             str(model), str(compute_type), f"beam{beam_size}", f"v{TRANSCRIPT_CACHE_VERSION}"]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    safe_stem = re.sub(r"[^\w]", "_", p.stem)[:60]
    return f"{safe_stem}_{digest}"


class AudioTranscriber:
    """
    Agente 1: Responsable de extraer el audio, realizar la transcripción fonética y
    temporal precisa con marcas a nivel palabra (word-level timestamps) y VAD.
    Optimizado para CPU AMD Ryzen 7 5825U (INT8, multihilos).
    Compatible con selección configurable entre small y large-v3-turbo, además de modo híbrido.
    """

    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        cpu_threads: Optional[int] = None,
        beam_size: Optional[int] = None,
        confidence_threshold: Optional[float] = None
    ):
        self.model_size = model_size or settings.hardware.whisper_model_size
        self.device = device or settings.hardware.device
        self.compute_type = compute_type or settings.hardware.compute_type
        self.cpu_threads = cpu_threads or settings.hardware.cpu_threads
        self.beam_size = beam_size or getattr(settings.hardware, "whisper_beam_size", 1)
        self.confidence_threshold = confidence_threshold or getattr(settings.hardware, "whisper_conf_threshold", 0.70)
        self.cache_dir = settings.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._model = None

    def load_model(self):
        """Carga perezosa del modelo Faster-Whisper para preservar memoria RAM."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                
                # Mapeo a repositorio Hugging Face en caso de large-v3-turbo
                target_model = self.model_size
                if self.model_size in ("large-v3-turbo", "large_v3_turbo"):
                    target_model = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"

                logger.info(
                    f"Cargando modelo Faster-Whisper [{target_model}] "
                    f"en {self.device.upper()} ({self.compute_type}) con {self.cpu_threads} hilos..."
                )
                self._model = WhisperModel(
                    target_model,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                    download_root=str(settings.cache_dir / "whisper_models")
                )
                logger.info("Modelo Faster-Whisper cargado exitosamente.")
            except ImportError:
                logger.error("faster-whisper no está instalado. Ejecuta: pip install faster-whisper")
                raise

    def get_cache_path(self, path: Path, language: Optional[str] = None, dominican_mode: bool = True) -> Path:
        key = transcript_cache_key(path, language, dominican_mode, self.model_size, self.compute_type, self.beam_size)
        return self.cache_dir / f"tx_{key}.json"

    def transcribe(
        self,
        video_or_audio_path: str,
        language: Optional[str] = None,
        vad_filter: bool = True,
        initial_prompt: Optional[str] = None,
        dominican_mode: bool = True,
        use_llm: bool = False,
        beam_size: Optional[int] = None,
        use_cache: bool = True
    ) -> TranscriptResult:
        """
        Transcribe un archivo de video o audio generando timestamps por palabra.
        Si dominican_mode es True, condiciona el modelo y normaliza la jerga dominicana.
        Soporta caché persistente para reutilización inmediata (0.01s).
        """
        path = Path(video_or_audio_path)
        if not path.exists():
            raise FileNotFoundError(f"No existe el archivo: {video_or_audio_path}")

        # Caché de transcripciones para evitar re-procesar el mismo audio
        cache_file = None
        if use_cache:
            try:
                cache_file = self.get_cache_path(path, language, dominican_mode)
                if cache_file.exists():
                    with open(cache_file, "r", encoding="utf-8") as cf:
                        data = json.load(cf)
                    logger.info(f"⚡ Transcripción cargada desde caché instantáneo: {cache_file.name}")
                    return TranscriptResult(
                        video_path=data.get("video_path", str(path)),
                        segments=[TranscriptSegment(**s) for s in data["segments"]],
                        language=data["language"],
                        duration=data["duration"],
                        full_text=data.get("full_text", "")
                    )
            except Exception as e:
                logger.debug(f"No se pudo cargar caché de transcripción: {e}")

        self.load_model()

        # Determinar prompt contextual previo para guiar el modelo
        prompt = initial_prompt
        if prompt is None and dominican_mode:
            prompt = DOMINICAN_INITIAL_PROMPT
            logger.info("Modo Jerga Dominicana activado: inyectando contexto urbano y de dembow en Faster-Whisper.")

        chosen_beam = beam_size if beam_size is not None else self.beam_size

        logger.info(f"Iniciando transcripción para: {path.name} (beam_size={chosen_beam})")
        segments_raw, info = self._model.transcribe(
            str(path),
            language=language or ("es" if not getattr(settings.asr, "auto_detect_lang", False) else None),
            word_timestamps=True,
            beam_size=chosen_beam,
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
                            probability=round(w.probability, 3) if w.probability is not None else 1.0
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

        if cache_file:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as cf:
                    json.dump({
                        "language": detected_language,
                        "duration": round(duration, 3),
                        "segments": [s.model_dump() for s in parsed_segments],
                        "full_text": full_transcript.full_text
                    }, cf, ensure_ascii=False)
            except Exception as e:
                logger.debug(f"No se pudo guardar caché de transcripción: {e}")

        return full_transcript

    def transcribe_with_review(
        self,
        video_or_audio_path: str,
        language: Optional[str] = None,
        vad_filter: bool = True,
        initial_prompt: Optional[str] = None,
        dominican_mode: bool = True,
        use_llm: bool = False,
        beam_size: Optional[int] = None
    ) -> Tuple[TranscriptResult, QualityReviewReport]:
        """
        Transcribe con análisis de confianza e informe de fidelidad acústica.
        Retorna (TranscriptResult, QualityReviewReport).
        """
        raw_result = self.transcribe(
            video_or_audio_path=video_or_audio_path,
            language=language,
            vad_filter=vad_filter,
            initial_prompt=initial_prompt,
            dominican_mode=dominican_mode,
            use_llm=use_llm,
            beam_size=beam_size
        )

        verifier = HybridTranscriptionVerifier(
            confidence_threshold=self.confidence_threshold,
            enable_cloud=getattr(settings.asr, "cloud_enabled", False),
            enable_secondary=False
        )

        verified_result, report = verifier.process_and_verify(
            primary_result=raw_result,
            audio_path=video_or_audio_path,
            apply_dominican_rules=dominican_mode
        )

        return verified_result, report

    def save_transcript_json(self, transcript: TranscriptResult, output_path: str) -> str:
        """Guarda el resultado estructurado de la transcripción en JSON."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(transcript.model_dump(), f, ensure_ascii=False, indent=2)
        logger.info(f"Transcripción guardada en: {out}")
        return str(out)
