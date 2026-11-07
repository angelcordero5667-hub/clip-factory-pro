from src.agents.agent2_viral_detector.detector import ViralMomentDetector
from src.common.models import TranscriptResult, TranscriptSegment

def test_live():
    detector = ViralMomentDetector(min_duration=10.0, max_duration=35.0)
    sample = TranscriptResult(
        video_path="sample.mp4",
        language="es",
        duration=45.0,
        segments=[
            TranscriptSegment(id=0, start=0.0, end=7.0, text="¡No cometas este error brutal al invertir en bienes raices!"),
            TranscriptSegment(id=1, start=7.0, end=18.0, text="El 90% de la gente compra propiedades sin calcular el flujo de caja neto."),
            TranscriptSegment(id=2, start=18.0, end=30.0, text="La formula real es descontar impuestos, seguros y vacancia."),
            TranscriptSegment(id=3, start=30.0, end=45.0, text="Sigue estos tres pasos y nunca perderas dinero en una propiedad.")
        ],
        full_text="¡No cometas este error brutal al invertir en bienes raices! El 90% de la gente compra propiedades sin calcular el flujo de caja neto. La formula real es descontar impuestos, seguros y vacancia. Sigue estos tres pasos y nunca perderas dinero en una propiedad."
    )
    results = detector.detect_moments(sample)
    print(f"Total candidates found: {len(results)}")
    for r in results:
        print(f"[{r.category.upper()}] Score: {r.virality_score} | Dur: {r.duration}s | Hook: {r.hook_text}")

if __name__ == "__main__":
    test_live()
