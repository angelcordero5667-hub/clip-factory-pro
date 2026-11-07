import time
import sys
from pathlib import Path

# Configurar UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from src.agents.agent5_qa_optimizer.pipeline import ClipFactoryPipeline

def run_benchmark():
    video_path = Path("data/inputs/ejemplo_podcast.mp4")
    if not video_path.exists():
        print(f"ERROR: {video_path} no existe.")
        sys.exit(1)

    print(f"Corriendo benchmark con {video_path}...")
    pipeline = ClipFactoryPipeline()
    t0 = time.time()
    vid_id, candidates = pipeline.run_pipeline(
        str(video_path),
        max_candidates=1,
        render_clips=True,
        use_cache=False
    )
    total_time = time.time() - t0
    print(f"BENCHMARK_TOTAL_SECONDS: {total_time:.2f}")
    print(f"Candidatos generados: {len(candidates)}")
    return total_time

if __name__ == "__main__":
    run_benchmark()
