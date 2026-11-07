"""Limpia archivos temporales de data/cache (subtítulos .ass y recortes yt_sec_*.mp4).

Por defecto solo MUESTRA lo que borraría (dry-run). Usa --apply para borrar de verdad.
Nunca toca: modelos de Whisper, transcripciones en caché, data/inputs ni data/outputs.

    .venv\\python.exe scripts\\clean_cache.py            # vista previa
    .venv\\python.exe scripts\\clean_cache.py --apply    # borrar
    .venv\\python.exe scripts\\clean_cache.py --days 7   # solo los de más de 7 días
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
PATTERNS = ("*_subtitles.ass", "yt_sec_*.mp4")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="borrar de verdad (por defecto, vista previa)")
    parser.add_argument("--days", type=float, default=0, help="solo archivos con más de N días")
    args = parser.parse_args()

    if not CACHE.is_dir():
        print(f"No existe {CACHE}")
        return 0

    cutoff = time.time() - args.days * 86400
    files = sorted({p for pat in PATTERNS for p in CACHE.glob(pat) if p.is_file() and p.stat().st_mtime <= cutoff})
    total = sum(p.stat().st_size for p in files)

    for p in files:
        print(f"{'borrando' if args.apply else 'borraría'}: {p.name} ({p.stat().st_size / 1e6:.1f} MB)")
        if args.apply:
            try:
                p.unlink()
            except OSError as e:
                print(f"  no se pudo borrar: {e}")

    verb = "Liberados" if args.apply else "Se liberarían"
    print(f"\n{len(files)} archivos. {verb} {total / 1e6:.1f} MB." + ("" if args.apply else "  (usa --apply para borrar)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
