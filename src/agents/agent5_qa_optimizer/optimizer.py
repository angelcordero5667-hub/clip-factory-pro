import gc
import logging
import psutil
from src.common.config import settings

logger = logging.getLogger("Agent5_Optimizer")

class MemoryOptimizer:
    """
    Monitor de memoria del PROCESO (RSS de Python + procesos hijos como FFmpeg),
    no de todo el sistema, para respetar el límite configurado.
    """

    def __init__(self, max_ram_gb: float = 18.0):
        self.max_ram_gb = max_ram_gb

    def get_memory_usage_gb(self) -> float:
        """Memoria residente (GB) del proceso actual más sus hijos."""
        proc = psutil.Process()
        total = proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except psutil.Error:
                continue
        return round(total / (1024 ** 3), 2)

    def check_memory_safe(self) -> bool:
        """True si el proceso está dentro del umbral. Si no, libera memoria y devuelve False."""
        used = self.get_memory_usage_gb()
        if used > self.max_ram_gb:
            logger.warning(
                f"ALERTA DE MEMORIA: el proceso usa {used} GB y superó el umbral seguro ({self.max_ram_gb} GB)."
            )
            self.collect_garbage()
            return False
        return True

    def collect_garbage(self):
        """Libera referencias huérfanas en Python para recuperar memoria."""
        gc.collect()
        logger.info(f"Recolección de basura ejecutada. Memoria del proceso: {self.get_memory_usage_gb()} GB")
