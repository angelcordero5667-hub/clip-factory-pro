"""Benchmark de renderizado: genera N clips sintéticos de un video local y mide el tiempo.

Uso: python benchmark_render.py [video] [n_clips]
El video de ejemplo dura 25 s y el VAD descarta todo su audio, por lo que el
benchmark completo (benchmark_runner.py) no renderiza nada. Este mide el render.
"""
import sys
import time
from pathlib import Path

from src.common.config import settings
from src.common.models import ViralMomentCandidate, TranscriptSegment, WordTimestamp
from src.agents.agent3_clip_generator.clip_maker import VerticalClipMaker


def make_candidates(n: int, duration: float):
    cands = []
    for i in range(n):
        cands.append(ViralMomentCandidate(
            id=f"bench_{i+1}", start_time=0.0, end_time=duration, duration=duration,
            title=f"Benchmark {i+1}", hook_text="hola", context_text="hola mundo",
            virality_score=80, category="sorpresa", reasoning="benchmark",
        ))
    return cands


def make_segments(duration: float):
    words = [WordTimestamp(word=f"palabra{k}", start=k * 0.5, end=k * 0.5 + 0.4) for k in range(int(duration / 0.5))]
    return [TranscriptSegment(id=0, start=0.0, end=duration, text=" ".join(w.word for w in words), words=words)]


def main():
    video = Path(sys.argv[1]) if len(sys.argv) > 1 else settings.inputs_dir / "ejemplo_podcast.mp4"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    duration = 20.0
    maker = VerticalClipMaker()
    cands = make_candidates(n, duration)
    segs = make_segments(duration)
    t0 = time.time()
    if hasattr(maker, "generate_clips_parallel"):
        maker.generate_clips_parallel(str(video), cands, segs)
    else:
        for c in cands:
            maker.generate_clip(str(video), c, segs)
    total = time.time() - t0
    print(f"RENDER_TOTAL_SECONDS: {total:.2f} ({n} clips de {duration:.0f}s)")
    # Limpia lo generado para no dejar clips de prueba en data/outputs
    for f in settings.outputs_dir.glob(f"{video.stem}_bench_*"):
        f.unlink(missing_ok=True)
    for f in settings.cache_dir.glob("bench_*_subtitles.ass"):
        f.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
