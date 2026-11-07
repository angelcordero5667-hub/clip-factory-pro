import sys
import argparse
from pathlib import Path
from src.agents.agent5_qa_optimizer.pipeline import ClipFactoryPipeline

def main():
    parser = argparse.ArgumentParser(description="Clip Factory Pro - CLI Runner")
    parser.add_argument("video_path", type=str, help="Ruta al archivo de video de larga duración")
    parser.add_argument("--max-clips", type=int, default=5, help="Número máximo de clips candidatos a generar (1-20)")
    parser.add_argument("--no-render", action="store_true", help="Solo transcribir y detectar candidatos sin renderizar clips")

    parser.add_argument("--fast", action="store_true", help="Modo rápido: omite el LLM y usa solo el detector heurístico")
    parser.add_argument("--language", type=str, default=None, help="Idioma del audio (p. ej. es). Por defecto se autodetecta")

    args = parser.parse_args()

    video_file = Path(args.video_path)
    if not video_file.exists():
        print(f"Error: No se encontró el archivo de video: {args.video_path}")
        sys.exit(1)

    print("==========================================================")
    print(" Clip Factory Profesional 🎬 - Pipeline Multiagente ")
    print("==========================================================")
    print(f"Video de entrada: {video_file.name}")
    print(f"Máximo de clips: {args.max_clips}")
    print("Iniciando procesamiento...\n")

    pipeline = ClipFactoryPipeline()
    video_id, candidates = pipeline.run_pipeline(
        str(video_file),
        max_candidates=args.max_clips,
        render_clips=not args.no_render,
        fast=args.fast,
        language=args.language
    )

    print("\n==========================================================")
    print(" Resumen de Candidatos Virales Generados ")
    print("==========================================================")
    print(f"ID del Video: {video_id}")
    print(f"Total momentos identificados: {len(candidates)}\n")

    for idx, c in enumerate(candidates, 1):
        print(f"[{idx}] Score: {c.virality_score:.0f}/100 | Cat: {c.category.upper()} | Duración: {c.duration:.1f}s ({c.start_time:.1f}s - {c.end_time:.1f}s)")
        print(f"    Gancho: \"{c.hook_text}\"")
        print(f"    Razonamiento: {c.reasoning}\n")

    print("Puedes revisar y aprobar estos clips en el Dashboard web ejecutando: start_dashboard.bat\n")

if __name__ == "__main__":
    main()


