import os
from pathlib import Path
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
    whisper_model_size: str = os.environ.get("CLIP_WHISPER_MODEL", "small")  # Options: 'tiny', 'base', 'small', 'medium'
    max_ram_usage_gb: int = 18        # Out of 24 GB RAM

class OllamaConfig(BaseModel):
    base_url: str = "http://127.0.0.1:11434"
    model: str = "llama3.2:3b"
    timeout_seconds: int = 120

class VideoConfig(BaseModel):
    target_width: int = 1080
    target_height: int = 1920
    target_fps: int = 30
    min_clip_duration_sec: float = 20.0
    max_clip_duration_sec: float = 65.0
    max_candidates: int = 20

class RenderConfig(BaseModel):
    parallel_clips: int = 2           # clips renderizados en paralelo
    threads_per_clip: int = 4         # -threads de FFmpeg por clip
    preset: str = "veryfast"          # preset base
    speed_mode: str = "turbo"         # turbo (superfast), fast (veryfast), studio (medium)
    crf: int = 24
    use_hw_encoder: bool = os.environ.get("CLIP_HW_ENCODER", "1") != "0"  # h264_amf si existe, con fallback a libx264
    bg_scale_div: int = 4             # el fondo se desenfoca a 1/4 de resolución
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

