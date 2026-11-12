import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
INPUTS_DIR = DATA_DIR / "inputs"
OUTPUTS_DIR = DATA_DIR / "outputs"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = Path(os.environ.get("CLIP_DB_PATH") or (DATA_DIR / "clip_factory.db"))
TOOLS_DIR = BASE_DIR / "tools"
FFMPEG_BIN = TOOLS_DIR / "ffmpeg" / "bin"
OLLAMA_BIN = Path(os.path.expanduser(r"~\AppData\Local\Programs\Ollama"))

# Auto-inject local FFmpeg and Ollama into system PATH
extra_paths = [str(FFMPEG_BIN), str(OLLAMA_BIN)]
for p in extra_paths:
    if os.path.exists(p) and p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{p};{os.environ.get('PATH', '')}"

class HardwareConfig(BaseModel):
    # AMD Ryzen 7 5825U (8 cores, 16 threads) + Integrated GPU
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = 8
    whisper_model_size: str = os.environ.get("CLIP_WHISPER_MODEL", "large-v3-turbo")  # Activado por defecto en alta fidelidad
    whisper_beam_size: int = int(os.environ.get("CLIP_WHISPER_BEAM_SIZE", "1"))
    whisper_conf_threshold: float = float(os.environ.get("CLIP_WHISPER_CONF_THRESHOLD", "0.7"))
    max_ram_usage_gb: int = 18        # Out of 24 GB RAM

class ASRConfig(BaseModel):
    mode: str = os.environ.get("CLIP_ASR_MODE", "hybrid")  # Modo híbrido activado por defecto
    primary: str = os.environ.get("CLIP_ASR_PRIMARY", "whisper")
    secondary: str = os.environ.get("CLIP_ASR_SECONDARY", "qwen3")
    cloud_enabled: bool = os.environ.get("CLIP_ASR_CLOUD_ENABLED", "0").lower() in ("1", "true")
    aligner_enabled: bool = os.environ.get("CLIP_ASR_ALIGNER_ENABLED", "1").lower() in ("1", "true")
    language: str = os.environ.get("CLIP_ASR_LANGUAGE", "es")
    auto_detect_lang: bool = os.environ.get("CLIP_ASR_AUTO_DETECT", "0").lower() in ("1", "true")
    dominican_mode: bool = os.environ.get("CLIP_ASR_DOMINICAN", "1").lower() in ("1", "true")  # Activado por defecto
    low_confidence_threshold: float = float(os.environ.get("CLIP_ASR_CONF_THRESHOLD", "0.7"))
    elevenlabs_api_key: Optional[str] = os.environ.get("ELEVENLABS_API_KEY", None)

class OllamaConfig(BaseModel):
    base_url: str = "http://127.0.0.1:11434"
    model: str = "llama3.2:3b"
    timeout_seconds: int = int(os.environ.get("CLIP_OLLAMA_TIMEOUT", "180"))

class VideoConfig(BaseModel):
    target_width: int = 1080
    target_height: int = 1920
    target_fps: int = 30
    min_clip_duration_sec: float = 20.0
    max_clip_duration_sec: float = 65.0
    max_candidates: int = 20

class RenderConfig(BaseModel):
    parallel_clips: int = 3           # clips renderizados en paralelo (3 concurrentes optimizados)
    threads_per_clip: int = 4         # -threads de FFmpeg por clip (12 hilos para 3 renders en CPU de 16 hilos)
    preset: str = "veryfast"          # preset base ultra veloz (veryfast) para producción rápida
    speed_mode: str = "fast"          # fast (veryfast/crf 21), quality (medium/crf 18), studio (slow/crf 17)
    crf: int = 24                     # CRF 24 base (configurable entre 17-24 según speed_mode)
    use_hw_encoder: bool = os.environ.get("CLIP_HW_ENCODER", "1") != "0"  # h264_amf si existe, con fallback a libx264
    bg_scale_div: int = 4             # desenfoque optimizado a 1/4 resolución (270x480) reescalado con blur rápido
    smart_framing: bool = os.environ.get("CLIP_SMART_FRAMING", "1") != "0"  # auto-encuadre al hablante
    trim_silences: bool = os.environ.get("CLIP_TRIM_SILENCES", "1") != "0"  # quita pausas largas y muletillas
    hook_zoom: bool = True            # punch-in zoom en los primeros 2.5s para retención estilo TikTok

class Settings(BaseModel):
    base_dir: Path = BASE_DIR
    inputs_dir: Path = INPUTS_DIR
    outputs_dir: Path = OUTPUTS_DIR
    cache_dir: Path = CACHE_DIR
    db_path: Path = DB_PATH
    hardware: HardwareConfig = HardwareConfig()
    ollama: OllamaConfig = OllamaConfig()
    video: VideoConfig = VideoConfig()
    render: RenderConfig = RenderConfig()
    asr: ASRConfig = ASRConfig()

    @property
    def face_model_path(self) -> Path:
        """Modelo YuNet (ONNX) para detección de rostros; ver docs/AUTOENCUADRE.md."""
        return DATA_DIR / "models" / "face_detection_yunet_2023mar.onnx"

    @property
    def ffmpeg_exe(self) -> str:
        """Ruta al ejecutable de FFmpeg local (o 'ffmpeg' del PATH si no existe)."""
        local = FFMPEG_BIN / "ffmpeg.exe"
        return str(local) if local.exists() else "ffmpeg"

    @property
    def ffmpeg_encoder(self) -> str:
        """Encoder preferido según configuración y hardware (h264_amf o libx264)."""
        from src.agents.agent3_clip_generator.clip_maker import pick_encoder
        return pick_encoder()

settings = Settings()

# Ensure directories exist
for folder in [INPUTS_DIR, OUTPUTS_DIR, CACHE_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

