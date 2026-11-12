"""
Módulo de Normalización y Reconocimiento de Jerga Urbana Dominicana para Whisper & Subtítulos.

Estructura modular por categorías:
1. Expresiones dominicanas y jerga urbana.
2. Nombres de artistas, celebridades y apodos urbanos.
3. Correcciones fonéticas contextuales (aspiración de S, elisiones, fusiones léxicas).
4. Detección de palabras y segmentos con baja confianza.
5. Extensibilidad mediante archivo de vocabulario JSON configurable sin tocar código.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from src.common.models import TranscriptSegment, WordTimestamp

logger = logging.getLogger("DominicanSlang")

# Prompt inicial para Faster-Whisper
DOMINICAN_INITIAL_PROMPT = (
    "Transcripción en español de República Dominicana con jerga urbana, dembow y entrevistas. "
    "Términos: klk, ta' tó, pámpara, wawawa, popi, teteo, cualto, chelitos, demagogo, pariguayo, "
    "coro, vaina, lío, freco, en olla, chucky, de lo mío, tíguere, dizque, bacano, singar, chapiadora, "
    "manito, pana, canchanchán, piquete, bochinchero, quillarse, de lo lindo, Papá Dios, salvos, iglesia. "
    "Nombres propios y medios: Alofoke, Santiago Matías, Rochy RD, Kreizy K, Yailin La Más Viral, Anuel AA, "
    "El Alfa, Tokischa, Bulin 47, Onguito Wa, Toxic Crow, Luinny Corporán, Capricornio TV, Dotol Nastra, Dilon Baby, Masha."
)

# ==============================================================================
# DICCIONARIO CATEGORIZADO DE JERGA, FONÉTICA Y NOMBRES URBANOS
# ==============================================================================

CATEGORIZED_DICTIONARY: Dict[str, List[Tuple[str, str]]] = {
    # 1. Expresiones dominicanas y jerga urbana
    "expresiones_urbanas": [
        (r"\bta\s+to\b", "ta' tó"),
        (r"\btató\b", "ta' tó"),
        (r"\btano\b", "ta' tó"),
        (r"\bta\s*tano\b", "ta' tó"),
        (r"\bde\s+lo\s+mio\b", "de lo mío"),
        (r"\bdelomio\b", "de lo mío"),
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
        (r"\bchuki\b", "chucky"),
        (r"\bprender\s+la\s+l[aá]mpara\b", "prender la pámpara"),
        (r"\bla\s+l[aá]mpara\b", "la pámpara"),
        (r"\bpampara\b", "pámpara"),
        (r"\bdesacata\s*o\b", "desacata'o"),
        (r"\bdesbarata\s*o\b", "desbarata'o"),
        (r"\bquilla\s*o\b", "quilla'o"),
        (r"\bquillo\b", "quilló"),
        (r"\bde\s+lo\s+lindo\b", "de lo lindo"),
    ],

    # 2. Nombres de artistas, personalidades y shows
    "artistas_y_apodos": [
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
        (r"\bdillon\s+baby\b", "Dilon Baby"),
        (r"\bdillon\b", "Dilon"),
        (r"\bdilon\b", "Dilon"),
    ],

    # 3. Fonética contextual: Aspiración de 's', elisiones y fusiones
    "fonetica_contextual": [
        # Aspiración de 's' final en Papá Dios
        (r"\bpap[aá]\s+dio\b", "Papá Dios"),
        (r"\bpapa\s+dios\b", "Papá Dios"),
        # Elisión de 'es' y plural en están salvos
        (r"\btan\s+salvo\b", "están salvos"),
        (r"\btan\s+salvos\b", "están salvos"),
        (r"\btan\s+salva\b", "están salvas"),
        (r"\btan\s+salvas\b", "están salvas"),
        # Fusión léxica / error acústico en cantan canciones
        (r"\bunos\s+cantaciones\b", "unos cantan canciones"),
        (r"\bcantaciones\b", "cantan canciones"),
    ]
}

# Cargar vocabulario externo configurable si existe (e.g. data/dominican_custom_vocab.json)
CUSTOM_VOCAB_PATH = Path("data/dominican_custom_vocab.json")
if CUSTOM_VOCAB_PATH.exists():
    try:
        custom_data = json.loads(CUSTOM_VOCAB_PATH.read_text(encoding="utf-8"))
        for category, pairs in custom_data.items():
            if category not in CATEGORIZED_DICTIONARY:
                CATEGORIZED_DICTIONARY[category] = []
            for pattern, repl in pairs:
                CATEGORIZED_DICTIONARY[category].append((pattern, repl))
        logger.info(f"Cargado vocabulario personalizado desde {CUSTOM_VOCAB_PATH}")
    except Exception as e:
        logger.warning(f"Error al cargar {CUSTOM_VOCAB_PATH}: {e}")

# Lista aplanada de reemplazos para retrocompatibilidad total
DOMINICAN_REPLACEMENTS: List[Tuple[str, str]] = []
for _cat, _rules in CATEGORIZED_DICTIONARY.items():
    DOMINICAN_REPLACEMENTS.extend(_rules)

# Compilación de expresiones regulares con IGNORECASE
COMPILED_RULES = [(re.compile(pattern, re.IGNORECASE), replacement) for pattern, replacement in DOMINICAN_REPLACEMENTS]


def correct_dominican_text(text: str) -> str:
    """Aplica las reglas fonéticas del dialecto dominicano a un texto arbitrario de forma contextual."""
    if not text:
        return ""
    result = text
    for regex, replacement in COMPILED_RULES:
        result = regex.sub(replacement, result)
    return result


def get_low_confidence_segments(
    segments: List[TranscriptSegment],
    threshold: float = 0.70
) -> List[Dict[str, Any]]:
    """
    Detecta palabras y segmentos con confianza menor al umbral especificado.
    No inventa palabras: identifica incertidumbre acústica real para revisión o re-análisis.
    """
    dubious = []
    for s_idx, seg in enumerate(segments):
        for w_idx, w in enumerate(seg.words):
            if w.probability is not None and w.probability < threshold:
                dubious.append({
                    "segment_id": seg.id,
                    "segment_index": s_idx,
                    "word_index": w_idx,
                    "word": w.word,
                    "probability": round(w.probability, 4),
                    "start": w.start,
                    "end": w.end,
                    "segment_text": seg.text
                })
    return dubious


def normalize_dominican_segments(
    segments: List[TranscriptSegment],
    use_llm: bool = False
) -> List[TranscriptSegment]:
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

    # Opcional: Refinamiento asistido por LLM local (Ollama llama3.2)
    if use_llm:
        try:
            normalized_segments = refine_segments_with_ollama(normalized_segments)
        except Exception as e:
            logger.warning(f"No se pudo refinar con Ollama (se mantiene corrección por diccionario): {e}")

    return normalized_segments


def refine_segments_with_ollama(
    segments: List[TranscriptSegment],
    model: str = "llama3.2:3b",
    endpoint: str = "http://127.0.0.1:11434"
) -> List[TranscriptSegment]:
    """
    Utiliza Llama 3.2 vía Ollama local para pulir giros idiomáticos complejos del habla dominicana
    sin desfasar los timestamps.
    """
    if not segments:
        return segments

    full_sample = " | ".join(s.text for s in segments[:10])
    prompt = (
        f"Eres un experto en transcripción del dialecto dominicano urbano (Alofoke, Dembow, calle de Santo Domingo).\n"
        f"A continuación hay fragmentos de audio transcritos separados por '|'. Corrige palabras mal escritas "
        f"manteniendo la jerga dominicana exacta (klk, ta tó, pámpara, wawawa, cualto, popi, teteo, nombres propios como Alofoke, Rochy RD, Kreizy K, Yailin, Dilon Baby, Masha).\n"
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
        import urllib.request
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
