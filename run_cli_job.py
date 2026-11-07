import sys
import time
import logging

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from src.agents.agent5_qa_optimizer.pipeline import ClipFactoryPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def main():
    url = "https://www.youtube.com/watch?v=qjn_zvadIdM"
    print(f"🚀 INICIANDO CLIP FACTORY PRO para: {url}", flush=True)
    t0 = time.time()
    pipeline = ClipFactoryPipeline()
    
    def on_progress(msg: str):
        print(f"👉 {msg}", flush=True)

    try:
        vid_id, candidates = pipeline.run_pipeline(
            video_input=url,
            max_candidates=5,
            render_clips=True,
            subtitle_style="hormozi",
            include_emojis=True,
            aspect_ratio="9:16",
            progress_callback=on_progress
        )
        print(f"\n🎉 ¡PROCESO COMPLETADO en {time.time() - t0:.1f}s!", flush=True)
        print(f"Video ID: {vid_id}", flush=True)
        print(f"Total clips generados: {len(candidates)}", flush=True)
        for c in candidates:
            print(f" - [{c.virality_score}/100] {c.title} -> {c.clip_path}", flush=True)
    except Exception as e:
        print(f"❌ ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
