import json
import logging
import math
import os
import re
from typing import List, Optional
import requests

from src.common.config import settings
from src.common.models import TranscriptResult, TranscriptSegment, ViralMomentCandidate, ViralityBreakdown
from src.agents.agent2_viral_detector.audio_energy import energy_bonus, find_hype_moments
from src.agents.agent2_viral_detector.chat_activity import (
    ChatActivityProfile,
    chat_bonus,
    find_chat_hype_peaks,
)
from src.agents.agent2_viral_detector.analysis import (
    build_windows,
    compile_keyword_patterns,
    count_keyword_hits,
    flatten_words,
    normalize_text,
    sliding_windows,
    snap_to_pauses,
    trim_filler_words,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("Agent2_ViralDetector")

OPUS_PROMPT_TEMPLATE = """
Eres el motor de Inteligencia Artificial de OpusClip (el creador de clips virales #1 del mundo para TikTok, Shorts y Reels).
Analiza la siguiente transcripción con marcas de tiempo (en segundos).

Extrae entre 3 y {max_clips} momentos VIRALES de ALTO IMPACTO (humor, debates intensos, giros inesperados, lecciones poderosas, reacciones).

REGLAS OBLIGATORIAS:
1. Cada clip debe durar entre {min_duration} y {max_duration} segundos.
2. Cada clip debe tener un GANCHO magnético en los primeros 3 segundos.
3. El clip DEBE ser una idea autocontenida y completa (inicio claro y remate natural).
4. Genera un TÍTULO viral irresistible (con 1 emoji).
5. Calcula el 'virality_score' general (de 50 a 99), y su desglose: 'hook_score', 'flow_score' y 'trend_score' (todos 0-100).
6. Redacta un copy persuasivo ('social_description') y 4-6 hashtags estratégicos ('hashtags').
7. Usa SOLO tiempos que existan en la transcripción y frases que realmente se digan en ella. No copies los textos del formato.
8. Devuelve ÚNICAMENTE un objeto JSON válido con la clave "clips" (lista de momentos), sin texto adicional.

Formato (reemplaza cada <...> con contenido real de la transcripción):
{{"clips": [
  {{
    "start_time": <segundo de inicio, número>,
    "end_time": <segundo de fin, número>,
    "title": "<título viral basado en el contenido, con 1 emoji>",
    "hook_text": "<frase textual con la que abre el clip>",
    "context_text": "<resumen de lo que se explica en el clip>",
    "virality_score": <50 a 99>,
    "hook_score": <0 a 100>,
    "flow_score": <0 a 100>,
    "trend_score": <0 a 100>,
    "category": "<humor | discusion | reaccion | sorpresa | ensenanza>",
    "reasoning": "<por qué este momento retiene a la audiencia>",
    "social_description": "<copy persuasivo para redes>",
    "hashtags": ["<4 a 6 hashtags>"]
  }}
]}}

Transcripción:
{transcript_text}
"""

# Textos de ejemplo (versiones anteriores del prompt y placeholders) que delatan una respuesta copiada
TEMPLATE_MARKERS = (
    "El Secreto Que Nadie Te Dice",
    "Si estás cometiendo este error, estás perdiendo todo tu dinero",
    "<título viral",
    "<frase textual",
)

VIRAL_KEYWORDS = {
    "humor": ["jaja", "risa", "broma", "gracioso", "chiste", "ridículo", "meme", "locura"],
    "discusion": ["error", "mentira", "pero", "falso", "problema", "culpa", "crítica", "pelea", "discutir"],
    "reaccion": ["increíble", "no puede ser", "dios mío", "wow", "brutal", "impactante", "imposible"],
    "sorpresa": ["secreto", "nadie sabe", "la verdad", "revelar", "descubrí", "atención", "jamás"],
    "ensenanza": ["estrategia", "aprende", "regla", "método", "consejo", "paso 1", "fórmula"],
}
# Se normalizan (sin acentos) al compilar: "increíble" y "increible" coinciden con el mismo patrón.
_KEYWORD_PATTERNS = {cat: compile_keyword_patterns(kws) for cat, kws in VIRAL_KEYWORDS.items()}

CATEGORY_TITLES = {
    "humor": "La Risa Que No Esperabas 😂",
    "discusion": "El Gran Debate Que Divide Opiniones 💥",
    "reaccion": "Reacción Brutal Que Te Dejará en Shock 🤯",
    "sorpresa": "Lo Que Nadie Se Atreve a Decir 🤫",
    "ensenanza": "La Regla De Oro Que Debes Saber 💡",
}
CATEGORY_EMOJIS = {"humor": "😂", "discusion": "💥", "reaccion": "🤯", "sorpresa": "🤫", "ensenanza": "💡"}


class ViralMomentDetector:
    """
    Agente 2: Detección semántica con puntuación 0-100, desglose (Hook, Flow, Trend),
    títulos virales y copies para redes. Motor LLM por ventanas + heurístico de respaldo.
    """

    def __init__(
        self,
        ollama_url: Optional[str] = None,
        model_name: Optional[str] = None,
        min_duration: float = 20.0,
        max_duration: float = 65.0,
        max_candidates: int = 20,
        window_sec: float = 240.0,       # 3 a 4 minutos por ventana para el LLM
        window_overlap_sec: float = 30.0,
        heuristic_step_sec: float = 10.0,
        pause_tolerance_sec: float = 3.0,
        ai_provider: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
    ):
        try:
            from src.common.database import db
            self.ai_provider = ai_provider or db.get_setting("ai_provider", "ollama")
            saved_model = db.get_setting("ollama_model")
            self.model_name = model_name or saved_model or settings.ollama.model
            self.gemini_api_key = gemini_api_key or db.get_setting("gemini_api_key") or os.environ.get("GEMINI_API_KEY")
            self.gemini_model = gemini_model or db.get_setting("gemini_model", "gemini-2.5-flash")
        except Exception:
            self.ai_provider = ai_provider or "ollama"
            self.model_name = model_name or settings.ollama.model
            self.gemini_api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY")
            self.gemini_model = gemini_model or "gemini-2.5-flash"

        self.ollama_url = ollama_url or settings.ollama.base_url
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.max_candidates = max_candidates
        self.window_sec = min(480.0, max(180.0, window_sec))
        self.window_overlap_sec = window_overlap_sec
        self.heuristic_step_sec = heuristic_step_sec
        self.pause_tolerance_sec = pause_tolerance_sec

    def format_transcript_for_llm(self, transcript) -> str:
        """Acepta un TranscriptResult o una lista de segmentos (una ventana)."""
        segments = transcript.segments if hasattr(transcript, "segments") else transcript
        return "\n".join(f"[{seg.start:.1f}s -> {seg.end:.1f}s] {seg.text}" for seg in segments)

    @staticmethod
    def _apply_energy(
        candidates: List[ViralMomentCandidate],
        energy,
        transcript: Optional[TranscriptResult] = None
    ) -> List[ViralMomentCandidate]:
        """Sube o baja hasta ±8 puntos según la energía del audio del tramo (risas, énfasis, ritmo).
        
        Penalización por ruido: Si la energía acústica es alta (e > 0.75) pero la densidad verbal
        es muy baja (< 0.6 pal/s, ej. gritos prolongados o ruido de fondo sin diálogo),
        se penaliza en lugar de bonificar para priorizar contenido con sustancia semántica.
        """
        if energy is None:
            return candidates
        all_segments = transcript.segments if transcript and hasattr(transcript, "segments") else []
        for c in candidates:
            e = energy.window_score(c.start_time, c.end_time)
            bonus = energy_bonus(e)
            penalized = False
            if all_segments and c.duration > 5.0:
                words_in_clip = sum(
                    len(s.text.split()) for s in all_segments
                    if s.end >= c.start_time and s.start <= c.end_time
                )
                wps = words_in_clip / c.duration
                if e > 0.75 and wps < 0.6:
                    bonus = -4.0
                    penalized = True
                    c.reasoning = f"{c.reasoning} Penalización por ruido/gritos sin densidad verbal ({wps:.1f} pal/s).".strip()
            c.virality_score = round(min(100.0, max(0.0, c.virality_score + bonus)), 1)
            sign = "+" if bonus >= 0 else ""
            if not penalized:
                c.reasoning = f"{c.reasoning} Energía de audio {int(e * 100)}/100 ({sign}{bonus} pts).".strip()
        return candidates

    def detect_moments(
        self,
        transcript: TranscriptResult,
        use_llm: bool = True,
        energy=None,
        include_hype: Optional[bool] = None,
        layout: Optional[str] = None,
        focus_prompt: Optional[str] = None,
        chat_profile: Optional[ChatActivityProfile] = None,
    ) -> List[ViralMomentCandidate]:
        if transcript.duration < self.min_duration:
            logger.warning(f"Duración ({transcript.duration}s) menor al mínimo requerido.")
            return []

        candidates: List[ViralMomentCandidate] = []
        if use_llm:
            if self.ai_provider == "gemini":
                try:
                    candidates = self._detect_with_gemini(transcript, focus_prompt=focus_prompt)
                except Exception as e:
                    logger.warning(f"Gemini API no respondió: {e}. Probando Ollama / Heurístico.")
                    try:
                        candidates = self._detect_with_ollama(transcript, focus_prompt=focus_prompt)
                    except Exception:
                        pass
            elif self.ai_provider == "ollama":
                try:
                    candidates = self._detect_with_ollama(transcript, focus_prompt=focus_prompt)
                except Exception as e:
                    logger.warning(f"Ollama no respondió: {e}. Activando motor heurístico.")
            elif self.ai_provider == "heuristic":
                logger.info("Proveedor configurado como heurístico. Saltando LLM.")

        if not candidates:
            candidates = self._detect_heuristic(transcript, focus_prompt=focus_prompt)

        # Hype peaks: solo activado en streams/gaming o con flag explícito
        should_include_hype = include_hype if include_hype is not None else (layout in ("gaming", "streamer"))
        if energy is not None and should_include_hype:
            try:
                hype_peaks = find_hype_moments(
                    energy,
                    min_duration=self.min_duration,
                    max_duration=self.max_duration,
                    top_n=max(2, self.max_candidates // 2)
                )
                for idx, (p_start, p_end, p_score) in enumerate(hype_peaks, 1):
                    # Evitar solapes: reforzar a los candidatos que cubren el pico y no duplicar
                    overlapping_any = False
                    peak_dur = max(1.0, (p_end - p_start))
                    for existing in candidates:
                        inter_start = max(p_start, existing.start_time)
                        inter_end = min(p_end, existing.end_time)
                        inter_len = max(0.0, inter_end - inter_start)
                        if inter_len >= 10.0 or (inter_len / peak_dur) >= 0.4:
                            overlapping_any = True
                            if p_score > 0.5:
                                existing.virality_score = min(99.0, existing.virality_score + 3.0)
                                if "pico de energía" not in existing.reasoning.lower():
                                    existing.reasoning += f" Coincide con pico de energía acústica ({int(p_score*100)}/100)."

                    if overlapping_any:
                        continue

                    # Extraer transcripción contextual para titular y redactar copy real
                    matching_segs = [s for s in transcript.segments if s.end >= p_start and s.start <= p_end]
                    text_snippet = " ".join(s.text for s in matching_segs).strip()
                    first_text = matching_segs[0].text.strip() if matching_segs else ""
                    
                    p_score_pct = int(p_score * 100)
                    vir_score = round(min(98.0, max(75.0, 78.0 + p_score * 18.0)), 1)

                    clean_words = re.findall(r"\b[\wáéíóúüñÁÉÍÓÚÜÑ]+\b", first_text) if first_text else []
                    if len(clean_words) >= 3:
                        title_text = f"{' '.join(clean_words[:5]).title()} 💥"
                    elif text_snippet:
                        snippet_words = re.findall(r"\b[\wáéíóúüñÁÉÍÓÚÜÑ]+\b", text_snippet) if text_snippet else []
                        title_text = f"{' '.join(snippet_words[:5]).title()} 🔥" if len(snippet_words) >= 3 else f"Reacción en Directo ({p_score_pct}%) 🔥"
                    else:
                        title_text = f"Pico de Intensidad ({p_score_pct}%) 💥"

                    if text_snippet:
                        social_desc = f"¡Momento intenso en el directo! '{text_snippet[:90]}...' ¿Qué opinas? Comenta 👇"
                        ctx = text_snippet[:250] + ("..." if len(text_snippet) > 250 else "")
                    else:
                        social_desc = "¡Reacción brutal y máxima tensión en el directo! 🔥🎮 ¿Te lo esperabas?"
                        ctx = f"Pico de energía acústica ({p_score_pct}/100) y alta intensidad en streaming."

                    hook_txt = first_text[:120] if first_text else "¡Momento cumbre de la partida!"

                    candidates.append(ViralMomentCandidate(
                        id=f"clip_hype_{idx}",
                        start_time=round(p_start, 2),
                        end_time=round(min(transcript.duration, p_end), 2),
                        duration=round(p_end - p_start, 2),
                        title=title_text,
                        hook_text=hook_txt,
                        context_text=ctx,
                        virality_score=vir_score,
                        breakdown=ViralityBreakdown(
                            hook_score=min(100.0, vir_score + 2.0),
                            flow_score=min(100.0, vir_score),
                            trend_score=min(100.0, vir_score + 1.0),
                        ),
                        category="reaccion",
                        reasoning=f"Pico de volumen y energía acústica ({p_score_pct}/100) característico de momentos virales en streaming.",
                        social_description=social_desc,
                        hashtags=["#streamer", "#twitch", "#gaming", "#momentoepico", "#viral"],
                        status="pending",
                        engine="audio_energy",
                    ))
            except Exception as e:
                logger.debug(f"Hype moments scan fallback: {e}")

        # Chat Activity Hype: refuerzo de momentos y extracción de picos de chat
        if chat_profile is not None:
            try:
                for cand in candidates:
                    c_score = chat_profile.window_score(cand.start_time, cand.end_time)
                    if c_score > 0.5:
                        c_bonus = chat_bonus(c_score, max_points=6.0)
                        cand.virality_score = min(99.0, max(50.0, cand.virality_score + c_bonus))
                        if "chat" not in cand.reasoning.lower():
                            cand.reasoning += f" Alta actividad en el chat de directo ({int(c_score * 100)}%)."
                chat_peaks = find_chat_hype_peaks(
                    chat_profile,
                    min_duration=self.min_duration,
                    max_duration=self.max_duration,
                    top_n=max(2, self.max_candidates // 2),
                )
                for idx, (cp_start, cp_end, cp_score) in enumerate(chat_peaks, 1):
                    overlapping_any = False
                    peak_dur = max(1.0, (cp_end - cp_start))
                    for existing in candidates:
                        inter_start = max(cp_start, existing.start_time)
                        inter_end = min(cp_end, existing.end_time)
                        inter_len = max(0.0, inter_end - inter_start)
                        if inter_len >= 10.0 or (inter_len / peak_dur) >= 0.4:
                            overlapping_any = True
                            break
                    if overlapping_any:
                        continue

                    matching_segs = [s for s in transcript.segments if s.end >= cp_start and s.start <= cp_end]
                    text_snippet = " ".join(s.text for s in matching_segs).strip()
                    first_text = matching_segs[0].text.strip() if matching_segs else ""

                    vir_score = round(min(98.0, max(76.0, 78.0 + cp_score * 18.0)), 1)
                    title_text = f"Reacción del Chat ({int(cp_score * 100)}%) 💬🔥"
                    hook_txt = first_text[:120] if first_text else "¡El chat enloqueció en este momento!"
                    social_desc = "¡El chat reaccionó con todo a esta escena! 💬🔥 ¿Qué opinas tú?"
                    ctx = f"Pico de ráfaga y reacciones en el chat ({int(cp_score * 100)}/100)."

                    candidates.append(ViralMomentCandidate(
                        id=f"clip_chat_{idx}",
                        start_time=round(cp_start, 2),
                        end_time=round(min(transcript.duration, cp_end), 2),
                        duration=round(cp_end - cp_start, 2),
                        title=title_text,
                        hook_text=hook_txt,
                        context_text=ctx,
                        virality_score=vir_score,
                        reasoning=f"Momento impulsado por ráfagas de mensajes y emotes del chat ({int(cp_score * 100)}%).",
                        social_description=social_desc,
                        hashtags=["#streamer", "#twitch", "#chat", "#clip", "#viral"],
                        status="pending",
                        engine="chat_activity",
                        pause_aligned=False,
                        category="humor" if cp_score > 0.65 else "epico",
                    ))
            except Exception as e:
                logger.debug(f"Chat activity scan fallback: {e}")

        validated = self._validate_and_adjust_boundaries(candidates, transcript)
        if not validated and candidates and candidates[0].engine == "llm":
            logger.warning("Ningún candidato del LLM cumplió las duraciones; se usa el motor heurístico.")
            validated = self._validate_and_adjust_boundaries(self._detect_heuristic(transcript, focus_prompt=focus_prompt), transcript)
        aligned = self._align_to_pauses(validated, transcript)
        aligned = self._apply_energy(aligned, energy, transcript=transcript)
        deduped = self.deduplicate_candidates(aligned)
        deduped.sort(key=lambda c: c.virality_score, reverse=True)
        deduped = self.normalize_virality_scores(deduped)
        return deduped[: self.max_candidates]

    @staticmethod
    def normalize_virality_scores(
        candidates: List[ViralMomentCandidate],
        target_min: float = 66.0,
        target_max: float = 97.0,
    ) -> List[ViralMomentCandidate]:
        """Normaliza los puntajes de viralidad dentro del video para evitar saturación en 99-100.

        Preserva estrictamente el orden relativo, mapeando los candidatos a un rango
        perceptible (por defecto 66 a 97) combinando su valor relativo continuo (65%)
        con su posición percentil (35%). Ajusta proporcionalmente los subpuntajes del desglose.
        """
        n = len(candidates)
        if n == 0:
            return candidates
        if n == 1:
            c = candidates[0]
            raw = c.virality_score
            c.virality_score = round(min(target_max, max(75.0, raw)), 1)
            return candidates

        candidates.sort(key=lambda x: x.virality_score, reverse=True)
        scores = [c.virality_score for c in candidates]
        s_min, s_max = min(scores), max(scores)

        for i, c in enumerate(candidates):
            raw = c.virality_score
            v = (raw - s_min) / (s_max - s_min) if s_max > s_min else 0.5
            p = ((n - 1) - i) / (n - 1)
            t = 0.65 * v + 0.35 * p
            norm_score = round(target_min + t * (target_max - target_min), 1)

            if c.breakdown and raw > 0:
                ratio = norm_score / raw
                c.breakdown.hook_score = round(min(100.0, max(0.0, c.breakdown.hook_score * ratio)), 1)
                c.breakdown.flow_score = round(min(100.0, max(0.0, c.breakdown.flow_score * ratio)), 1)
                c.breakdown.trend_score = round(min(100.0, max(0.0, c.breakdown.trend_score * ratio)), 1)

            c.virality_score = norm_score

        return candidates

    # ------------------------------------------------------------------
    # Motor LLM por ventanas
    # ------------------------------------------------------------------
    def _detect_with_ollama(self, transcript: TranscriptResult, focus_prompt: Optional[str] = None) -> List[ViralMomentCandidate]:
        windows = build_windows(transcript.segments, self.window_sec, self.window_overlap_sec)
        if not windows:
            return []
        per_window = max(3, math.ceil(self.max_candidates / len(windows)) + 1)

        candidates: List[ViralMomentCandidate] = []
        failures = 0
        last_error: Optional[Exception] = None
        for n, window in enumerate(windows, 1):
            try:
                if focus_prompt:
                    found = self._query_window(window, per_window, id_offset=len(candidates), focus_prompt=focus_prompt)
                else:
                    found = self._query_window(window, per_window, id_offset=len(candidates))
                logger.info(f"Ventana {n}/{len(windows)} "
                            f"({window[0].start:.0f}s-{window[-1].end:.0f}s): {len(found)} candidatos")
                candidates.extend(found)
            except Exception as e:
                failures += 1
                last_error = e
                logger.warning(f"Ventana {n}/{len(windows)} falló: {e}")
        if failures == len(windows) and last_error is not None:
            raise last_error  # nada funcionó: que detect_moments active el heurístico
        # Une resultados y elimina duplicados por solape temporal entre ventanas
        return self.deduplicate_candidates(candidates)

    def _query_window(
        self,
        segments: List[TranscriptSegment],
        max_clips: int,
        id_offset: int = 0,
        focus_prompt: Optional[str] = None,
    ) -> List[ViralMomentCandidate]:
        prompt = OPUS_PROMPT_TEMPLATE.format(
            min_duration=int(self.min_duration),
            max_duration=int(self.max_duration),
            max_clips=max_clips,
            transcript_text=self.format_transcript_for_llm(segments),
        )
        if focus_prompt and focus_prompt.strip():
            focus_instruction = (
                f"\nREGLA PRIORITARIA DE ENFOQUE TEMÁTICO (INSTRUCCIÓN DEL USUARIO):\n"
                f"Prioriza y extrae momentos enfocados en: \"{focus_prompt.strip()}\".\n"
            )
            prompt = prompt.replace("REGLAS OBLIGATORIAS:\n", "REGLAS OBLIGATORIAS:\n" + focus_instruction)
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.3, "num_ctx": 4096},
        }
        response = requests.post(f"{self.ollama_url}/api/generate", json=payload, timeout=settings.ollama.timeout_seconds)
        response.raise_for_status()
        raw_output = response.json().get("response", "[]").strip()

        data = self._extract_json_array(raw_output)
        candidates = []
        for idx, item in enumerate(data):
            try:
                if any(m in str(item.get("hook_text", "")) + str(item.get("title", "")) for m in TEMPLATE_MARKERS):
                    continue  # el modelo copió el ejemplo del prompt en vez de analizar la transcripción
                start = float(item["start_time"])
                end = float(item["end_time"])
                raw_score = float(item.get("virality_score", 85.0))
                score = raw_score * 10.0 if (0.0 < raw_score <= 10.0) else raw_score
                score = round(min(100.0, max(0.0, score)), 1)
                hook_s = float(item.get("hook_score", min(100.0, score + 2.0)))
                flow_s = float(item.get("flow_score", max(0.0, score - 1.0)))
                trend_s = float(item.get("trend_score", score))

                candidates.append(ViralMomentCandidate(
                    id=f"clip_{id_offset + idx + 1}",
                    start_time=round(start, 2),
                    end_time=round(end, 2),
                    duration=round(end - start, 2),
                    title=item.get("title", f"Momento Viral #{id_offset + idx + 1} 🔥"),
                    hook_text=item.get("hook_text", "").strip(),
                    context_text=item.get("context_text", "").strip(),
                    virality_score=score,
                    breakdown=ViralityBreakdown(hook_score=hook_s, flow_score=flow_s, trend_score=trend_s),
                    category=item.get("category", "sorpresa").strip().lower(),
                    reasoning=item.get("reasoning", "Alto potencial de retención y debate.").strip(),
                    social_description=item.get("social_description", "").strip(),
                    hashtags=item.get("hashtags", ["#viral", "#shorts", "#reels"]),
                    status="pending",
                    engine="llm",
                ))
            except Exception as err:
                logger.debug(f"Error parseando clip: {err}")
        return candidates

    def _detect_with_gemini(self, transcript: TranscriptResult, focus_prompt: Optional[str] = None) -> List[ViralMomentCandidate]:
        windows = build_windows(transcript.segments, self.window_sec, self.window_overlap_sec)
        if not windows:
            return []
        per_window = max(3, math.ceil(self.max_candidates / len(windows)) + 1)

        candidates: List[ViralMomentCandidate] = []
        failures = 0
        last_error: Optional[Exception] = None
        for n, window in enumerate(windows, 1):
            try:
                found = self._query_gemini_window(window, per_window, id_offset=len(candidates), focus_prompt=focus_prompt)
                logger.info(f"[Gemini] Ventana {n}/{len(windows)} "
                            f"({window[0].start:.0f}s-{window[-1].end:.0f}s): {len(found)} candidatos")
                candidates.extend(found)
            except Exception as e:
                failures += 1
                last_error = e
                logger.warning(f"[Gemini] Ventana {n}/{len(windows)} falló: {e}")
        if failures == len(windows) and last_error is not None:
            raise last_error
        return self.deduplicate_candidates(candidates)

    def _query_gemini_window(
        self,
        segments: List[TranscriptSegment],
        max_clips: int,
        id_offset: int = 0,
        focus_prompt: Optional[str] = None,
    ) -> List[ViralMomentCandidate]:
        api_key = self.gemini_api_key
        if not api_key:
            raise ValueError("Clave GEMINI_API_KEY no configurada")

        prompt = OPUS_PROMPT_TEMPLATE.format(
            min_duration=int(self.min_duration),
            max_duration=int(self.max_duration),
            max_clips=max_clips,
            transcript_text=self.format_transcript_for_llm(segments),
        )
        if focus_prompt and focus_prompt.strip():
            focus_instruction = (
                f"\nREGLA PRIORITARIA DE ENFOQUE TEMÁTICO (INSTRUCCIÓN DEL USUARIO):\n"
                f"Prioriza y extrae momentos enfocados en: \"{focus_prompt.strip()}\".\n"
            )
            prompt = prompt.replace("REGLAS OBLIGATORIAS:\n", "REGLAS OBLIGATORIAS:\n" + focus_instruction)

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "response_mime_type": "application/json"
            }
        }
        res = requests.post(url, json=payload, timeout=30)
        res.raise_for_status()
        raw_json = res.json()
        parts = raw_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])
        text_content = parts[0].get("text", "[]") if parts else "[]"
        data = self._extract_json_array(text_content)
        candidates = []
        for idx, item in enumerate(data):
            try:
                if any(m in str(item.get("hook_text", "")) + str(item.get("title", "")) for m in TEMPLATE_MARKERS):
                    continue
                start = float(item["start_time"])
                end = float(item["end_time"])
                raw_score = float(item.get("virality_score", 85.0))
                score = raw_score * 10.0 if (0.0 < raw_score <= 10.0) else raw_score
                score = round(min(100.0, max(0.0, score)), 1)
                hook_s = float(item.get("hook_score", min(100.0, score + 2.0)))
                flow_s = float(item.get("flow_score", max(0.0, score - 1.0)))
                trend_s = float(item.get("trend_score", score))

                candidates.append(ViralMomentCandidate(
                    id=f"clip_{id_offset + idx + 1}",
                    start_time=round(start, 2),
                    end_time=round(end, 2),
                    duration=round(end - start, 2),
                    title=item.get("title", f"Momento Viral #{id_offset + idx + 1} 🔥"),
                    hook_text=item.get("hook_text", "").strip(),
                    context_text=item.get("context_text", "").strip(),
                    virality_score=score,
                    breakdown=ViralityBreakdown(hook_score=hook_s, flow_score=flow_s, trend_score=trend_s),
                    category=item.get("category", "sorpresa").strip().lower(),
                    reasoning=item.get("reasoning", "Detectado con Gemini Cloud").strip(),
                    social_description=item.get("social_description", "").strip(),
                    hashtags=item.get("hashtags", ["#viral", "#shorts", "#reels"]),
                    status="pending",
                    engine="gemini",
                ))
            except Exception as err:
                logger.debug(f"Error parseando clip de Gemini: {err}")
        return candidates

    @staticmethod
    def _clips_from_json(parsed) -> list:
        """Acepta una lista de clips, un objeto {"clips": [...]} (o candidates/moments/...),
        o un único clip suelto (los modelos pequeños con format=json suelen devolver uno solo)."""
        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]
        if isinstance(parsed, dict):
            if "start_time" in parsed and "end_time" in parsed:
                return [parsed]
            for key in ("clips", "candidates", "moments", "momentos", "results"):
                if isinstance(parsed.get(key), list):
                    return [x for x in parsed[key] if isinstance(x, dict)]
            for value in parsed.values():  # cualquier lista de objetos con tiempos
                if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                    return value
        return []

    def _extract_json_array(self, text: str) -> list:
        try:
            clips = self._clips_from_json(json.loads(text))
            if clips:
                return clips
        except Exception:
            pass

        # Texto con basura alrededor: busca el primer objeto o arreglo JSON completo
        for pattern in (r"\{.*\}", r"\[.*\]"):
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    clips = self._clips_from_json(json.loads(match.group(0)))
                    if clips:
                        return clips
                except Exception:
                    continue
        return []

    # ------------------------------------------------------------------
    # Motor heurístico: ventana deslizante con paso fijo + texto sin acentos
    # ------------------------------------------------------------------
    def _detect_heuristic(self, transcript: TranscriptResult, focus_prompt: Optional[str] = None) -> List[ViralMomentCandidate]:
        segments = transcript.segments
        normalized = [normalize_text(s.text) for s in segments]
        spans = sliding_windows(segments, self.min_duration, self.max_duration, step_sec=self.heuristic_step_sec)

        focus_patterns = None
        if focus_prompt and focus_prompt.strip():
            norm_focus = normalize_text(focus_prompt)
            stopwords = {"para", "como", "sobre", "este", "esta", "estos", "estas", "unos", "unas", "todo", "toda", "pero", "porque", "cuando", "donde", "quien"}
            focus_words = [w for w in re.findall(r"\b[a-z0-9áéíóúüñ]{3,}\b", norm_focus) if w not in stopwords]
            if focus_words:
                focus_patterns = compile_keyword_patterns(focus_words)

        candidates: List[ViralMomentCandidate] = []
        for i, j in spans:
            start_seg, end_seg = segments[i], segments[j]
            duration = end_seg.end - start_seg.start
            block_text = " ".join(normalized[i : j + 1])

            score = 75
            matched_category = "sorpresa"
            best_hits = 0
            for cat, patterns in _KEYWORD_PATTERNS.items():
                matches = count_keyword_hits(block_text, patterns)
                if matches > 0:
                    score += min(matches * 6, 20)
                    if matches >= best_hits:  # la categoría con más coincidencias da nombre al clip
                        matched_category, best_hits = cat, matches

            focus_hits = 0
            if focus_patterns:
                focus_hits = count_keyword_hits(block_text, focus_patterns)
                if focus_hits > 0:
                    score += min(focus_hits * 8, 20)

            first_sentence = start_seg.text
            if "?" in first_sentence or "¿" in first_sentence:
                score += 5
            if "!" in first_sentence or "¡" in first_sentence:
                score += 4
            score = min(99, score)

            clean_hook = re.sub(r"[¿?¡!\"'.,;:()]", "", first_sentence).strip()
            words_hook = clean_hook.split()
            emoji = CATEGORY_EMOJIS.get(matched_category, "🔥")
            if len(words_hook) >= 4:
                cand_title = f"{' '.join(words_hook[:6]).title()} {emoji}"
            else:
                cand_title = CATEGORY_TITLES.get(matched_category, f"Momento Viral {emoji}")  # ya incluye su emoji

            reasoning = f"Detectado gancho de alto impacto y patrones semánticos de {matched_category}."
            if focus_hits > 0 and focus_prompt:
                reasoning = f"Alineado con el tema solicitado ('{focus_prompt.strip()}'). {reasoning}"

            candidates.append(ViralMomentCandidate(
                id=f"clip_h_{len(candidates)+1}",
                start_time=round(start_seg.start, 2),
                end_time=round(end_seg.end, 2),
                duration=round(duration, 2),
                title=cand_title,
                hook_text=first_sentence[:120],
                context_text=" ".join(s.text for s in segments[i : j + 1])[:250] + "...",
                virality_score=score,
                breakdown=ViralityBreakdown(
                    hook_score=min(100, score + 3),
                    flow_score=min(100, score - 2),
                    trend_score=min(100, score + 1),
                ),
                category=matched_category,
                reasoning=reasoning,
                social_description=f"Mira este momento increíble sobre {matched_category}. ¿Estás de acuerdo? Comenta abajo 👇",
                hashtags=[f"#{matched_category}", "#viral", "#fyp", "#shorts", "#podcast"],
                status="pending",
                engine="heuristic",
            ))
        return candidates

    # ------------------------------------------------------------------
    # Límites, pausas y deduplicación
    # ------------------------------------------------------------------
    def _validate_and_adjust_boundaries(
        self, candidates: List[ViralMomentCandidate], transcript: TranscriptResult
    ) -> List[ViralMomentCandidate]:
        adjusted = []
        for c in candidates:
            s = max(0.0, c.start_time)
            e = min(transcript.duration, c.end_time)
            if s >= transcript.duration - 1.0:
                continue  # el inicio cae fuera del video
            if c.engine == "llm":
                # Los modelos pequeños eligen bien el momento pero ignoran la duración pedida:
                # se amplía (o recorta) alrededor de su inicio para cumplir mínimo y máximo.
                target = self.min_duration + 5.0
                if e - s < self.min_duration:
                    e = min(transcript.duration, s + target)
                    if e - s < self.min_duration:
                        s = max(0.0, e - target)
                elif e - s > self.max_duration + 5.0:
                    e = s + self.max_duration
            dur = e - s
            if self.min_duration <= dur <= self.max_duration + 5.0:
                c.start_time = round(s, 2)
                c.end_time = round(e, 2)
                c.duration = round(dur, 2)
                adjusted.append(c)
        return adjusted

    def _align_to_pauses(self, candidates: List[ViralMomentCandidate], transcript: TranscriptResult) -> List[ViralMomentCandidate]:
        """Ajusta inicio y fin a la pausa más cercana (timestamps por palabra) y poda muletillas muertas iniciales."""
        words = flatten_words(transcript.segments)
        if not words:
            return candidates
        for c in candidates:
            s, e, changed = snap_to_pauses(
                c.start_time, c.end_time, words,
                tolerance=self.pause_tolerance_sec,
                min_duration=self.min_duration,
                max_duration=self.max_duration + 5.0,
            )
            # Poda de muletillas iniciales (Filler-Word Trimmer) para arrancar directo con el gancho
            s_trim, new_hook, trimmed = trim_filler_words(s, e, words, min_duration=self.min_duration)
            if trimmed:
                s = s_trim
                changed = True
                if new_hook and len(new_hook) > 5:
                    c.hook_text = new_hook
            if changed:
                c.start_time = s
                c.end_time = min(e, transcript.duration)
                c.duration = round(c.end_time - c.start_time, 2)
                c.pause_aligned = True
        return candidates

    def deduplicate_candidates(
        self, candidates: List[ViralMomentCandidate], overlap_threshold: float = 0.5
    ) -> List[ViralMomentCandidate]:
        if not candidates:
            return []

        sorted_candidates = sorted(candidates, key=lambda x: x.virality_score, reverse=True)
        unique_candidates: List[ViralMomentCandidate] = []

        for cand in sorted_candidates:
            overlaps = False
            for kept in unique_candidates:
                inter_start = max(cand.start_time, kept.start_time)
                inter_end = min(cand.end_time, kept.end_time)
                inter_len = max(0.0, inter_end - inter_start)

                min_len = min(cand.duration, kept.duration)
                if min_len > 0 and (inter_len / min_len) >= overlap_threshold:
                    overlaps = True
                    break

            if not overlaps:
                unique_candidates.append(cand)

        return unique_candidates
