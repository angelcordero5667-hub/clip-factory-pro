"""
Módulo de Normalización y Reconocimiento de Jerga Urbana Dominicana para Whisper & Subtítulos.
Incluye:
1. DOMINICAN_INITIAL_PROMPT: Prompt contextual previo para Faster-Whisper.
2. Diccionario fonético de reemplazo de errores comunes en transcripción de audio dominicano.
3. Normalizador de segmentos y marcas de tiempo por palabra.
4. Opcional: Refinamiento asistido por LLM local (Ollama llama3.2).
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional
import urllib.request
import urllib.error

from src.common.models import TranscriptSegment, WordTimestamp

logger = logging.getLogger("DominicanSlang")

# Prompt inicial que condiciona a Whisper para reconocer dialecto dominicano y música urbana
DOMINICAN_INITIAL_PROMPT = (
    "Transcripción en español de República Dominicana con jerga urbana, dembow y música callejera. "
    "Términos habituales: klk, keloke, ta' tó, ta to, tató, pámpara, pampara, wawawa, wa wa wa, popi, "
    "teteo, cualto, cuarto, chelitos, demagogo, pariguayo, coro, chiste, pila, vaina, lío, freco, "
    "en olla, chucky, chuki, de lo mío, de lo mio, bregador, tíguere, tigre, dique, dizque, montar pila, "
    "bacano, singar, chapiadora, palomo, manito, pana, canchanchán, piquete, desacatao. "
    "Nombres propios y medios: Alofoke, Santiago Matías, Rochy RD, Kreizy K, Yailin La Más Viral, Anuel AA, "
    "El Alfa, Tokischa, Bulin 47, Onguito Wa, Toxic Crow, Luinny Corporán, Capricornio TV, Dotol Nastra."
)

# Diccionario de corrección fonética automática para transcripciones urbanas dominicanas
# Mapea patrones de error frecuentes de Whisper -> Término dominicano correcto
DOMINICAN_REPLACEMENTS = [
    # Expresiones de acuerdo y estado
    (r"\bta\s+to\b", "ta' tó"),
    (r"\btató\b", "ta' tó"),
    (r"\btano\b", "ta' tó"),  # Confusión clásica de Whisper en República Dominicana
    (r"\bta\s*tano\b", "ta' tó"),
    (r"\bde\s+lo\s+mio\b", "de lo mío"),
    (r"\bdelomio\b", "de lo mío"),
    
    # Saludos y jerga callejera
    (r"\bke\s*lo\s*ke\b", "klk"),
    (r"\bkeloke\b", "klk"),
    (r"\bque\s+lo\s+que\b", "klk"),
    (r"\bgua\s*gua\s*gua\b", "wawawa"),
    (r"\bguaguagua\b", "wawawa"),
    (r"\bwa\s*wa\s*wa\b", "wawawa"),
    (r"\bte\s*te\s*o\b", "teteo"),
    (r"\bpari\s*guayo\b", "pariguayo"),
    (r"\bpariguallo\b", "pariguayo"),
    (r"\btiguere\b", "tíguere"),
    (r"\btiguerazo\b", "tiguerazo"),
    (r"\bchapi\s*adora\b", "chapiadora"),
    (r"\bdesacata\s*o\b", "desacata'o"),
    (r"\bdesbarata\s*o\b", "desbarata'o"),
    (r"\bchuki\b", "chucky"),
    (r"\bprender\s+la\s+l[aá]mpara\b", "prender la pámpara"),
    (r"\bla\s+l[aá]mpara\b", "la pámpara"),
    (r"\bpampara\b", "pámpara"),
    
    # Nombres propios de artistas y programas urbanos de RD
    (r"\balofo\s*que\b", "Alofoke"),
    (r"\balofoque\b", "Alofoke"),
    (r"\balofoke\b", "Alofoke"),
    (r"\bsantiago\s+matias\b", "Santiago Matías"),
    (r"\brochi\s+rd\b", "Rochy RD"),
    (r"\brochy\s+rd\b", "Rochy RD"),
    (r"\broshi\s+rd\b", "Rochy RD"),
    (r"\brochi\b", "Rochy"),
    (r"\bcreysi\s*k\b", "Kreizy K"),
    (r"\bcreisy\s*k\b", "Kreizy K"),
    (r"\bcrazy\s*k\b", "Kreizy K"),
    (r"\bkreisi\s*k\b", "Kreizy K"),
    (r"\bkreizy\b", "Kreizy"),
    (r"\byail[ií]n\s+la\s+m[aá]s\s+viral\b", "Yailin La Más Viral"),
    (r"\byailin\b", "Yailin"),
    (r"\bjailin\b", "Yailin"),
    (r"\banuel\s*aa\b", "Anuel AA"),
    (r"\bel\s+alfa\b", "El Alfa"),
    (r"\btokischa\b", "Tokischa"),
    (r"\btoquicha\b", "Tokischa"),
    (r"\bbulin\s*47\b", "Bulin 47"),
    (r"\bonguito\s*wa\b", "Onguito Wa"),
    (r"\bluinny\s+corporan\b", "Luinny Corporán"),
    (r"\bdotol\s+nastra\b", "Dotol Nastra"),
    (r"\bcapricornio\s+tv\b", "Capricornio TV"),
]

# Compilar expresiones regulares con flag IGNORECASE
COMPILED_RULES = [(re.compile(pattern, re.IGNORECASE), replacement) for pattern, replacement in DOMINICAN_REPLACEMENTS]


def correct_dominican_text(text: str) -> str:
    """Aplica las reglas fonéticas del dialecto dominicano a un texto arbitrario."""
    if not text:
        return ""
    result = text
    for regex, replacement in COMPILED_RULES:
        result = regex.sub(replacement, result)
    return result


def normalize_dominican_segments(segments: List[TranscriptSegment], use_llm: bool = False) -> List[TranscriptSegment]:
    """
    Normaliza una lista de segmentos de transcripción para reflejar fielmente la jerga dominicana.
    Ajusta tanto el texto completo del segmento como las palabras individuales con timestamps.
    """
    if not segments:
        return []

    normalized_segments = []

    for seg in segments:
        original_text = seg.text
        corrected_text = correct_dominican_text(original_text)

        # Si el texto cambió, actualizamos también las palabras internas
        updated_words = []
        if seg.words:
            for w in seg.words:
                w_corr = correct_dominican_text(w.word)
                updated_words.append(
                    WordTimestamp(
                        word=w_corr,
                        start=w.start,
                        end=w.end,
                        probability=w.probability
                    )
                )
        else:
            updated_words = []

        normalized_segments.append(
            TranscriptSegment(
                id=seg.id,
                start=seg.start,
                end=seg.end,
                text=corrected_text,
                words=updated_words
            )
        )

    # Opcional: Si se solicita LLM y Ollama está disponible, refinar el texto preservando timestamps
    if use_llm:
        try:
            normalized_segments = refine_segments_with_ollama(normalized_segments)
        except Exception as e:
            logger.warning(f"No se pudo refinar con Ollama (se mantiene corrección por diccionario): {e}")

    return normalized_segments


def refine_segments_with_ollama(segments: List[TranscriptSegment], model: str = "llama3.2:3b", endpoint: str = "http://127.0.0.1:11434") -> List[TranscriptSegment]:
    """
    Utiliza Llama 3.2 vía Ollama local para pulir giros idiomáticos complejos del habla dominicana.
    Si Ollama responde rápidamente, actualiza el texto de los segmentos sin romper los timestamps.
    """
    if not segments:
        return segments

    # Tomar textos de los segmentos
    full_sample = " | ".join(s.text for s in segments[:10])
    prompt = (
        f"Eres un experto en transcripción del dialecto dominicano urbano (Alofoke, Dembow, calle de Santo Domingo).\n"
        f"A continuación hay fragmentos de audio transcritos separados por '|'. Corrige palabras mal escritas "
        f"manteniendo la jerga dominicana exacta (klk, ta tó, pámpara, wawawa, cualto, popi, teteo, nombres propios como Alofoke, Rochy RD, Kreizy K, Yailin).\n"
        f"Devuelve ÚNICAMENTE los fragmentos corregidos separados exactamente por '|', sin introducciones ni explicaciones.\n\n"
        f"Texto original:\n{full_sample}\n\nTexto corregido:"
    )

    req_data = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 300
        }
    }

    try:
        req = urllib.request.Request(
            f"{endpoint}/api/generate",
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            response_text = data.get("response", "").strip()
            chunks = [c.strip() for c in response_text.split("|")]
            if len(chunks) == min(len(segments), 10):
                for idx, c in enumerate(chunks):
                    if c:
                        segments[idx].text = c
                logger.info(f"Ollama refinó exitosamente {len(chunks)} segmentos con jerga dominicana.")
    except Exception as e:
        logger.debug(f"Ollama refine omitido por timeout o servicio inactivo: {e}")

    return segments
