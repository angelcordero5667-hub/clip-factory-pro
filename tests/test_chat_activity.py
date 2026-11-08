import json
import pytest
from pathlib import Path

from src.common.models import TranscriptResult, TranscriptSegment, WordTimestamp
from src.agents.agent2_viral_detector.chat_activity import (
    ChatMessage,
    ChatActivityProfile,
    parse_chat_messages,
    build_chat_profile,
    find_chat_hype_peaks,
    chat_bonus,
)
from src.agents.agent2_viral_detector.detector import ViralMomentDetector


def test_parse_chat_messages_dict_list():
    raw = [
        {"time": 10.5, "text": "Hola a todos"},
        {"t": 12.0, "message": "LUL que gracioso"},
        {"offset_seconds": 15.2, "body": "OMG ????"},
    ]
    msgs = parse_chat_messages(raw)
    assert len(msgs) == 3
    assert msgs[0].t == 10.5
    assert msgs[0].text == "Hola a todos"
    assert msgs[1].text == "LUL que gracioso"
    assert msgs[2].t == 15.2


def test_parse_chat_messages_twitch_format(tmp_path):
    twitch_data = {
        "comments": [
            {"content_offset_seconds": 5.0, "message": {"body": "iniciando stream"}},
            {"content_offset_seconds": 25.4, "message": {"body": "KEKW NO PUEDE SER"}},
            {"content_offset_seconds": 26.1, "message": {"body": "CLIP IT POGGG"}},
        ]
    }
    chat_file = tmp_path / "stream_chat.json"
    chat_file.write_text(json.dumps(twitch_data), encoding="utf-8")

    msgs = parse_chat_messages(chat_file)
    assert len(msgs) == 3
    assert msgs[1].t == 25.4
    assert "KEKW" in msgs[1].text
    assert msgs[2].t == 26.1


def test_parse_chat_messages_ytdlp_jsonl(tmp_path):
    line1 = json.dumps({
        "replayChatItemAction": {
            "videoOffsetTimeMsec": "14000",
            "actions": [{
                "addChatItemAction": {
                    "item": {
                        "liveChatTextMessageRenderer": {
                            "message": {"runs": [{"text": "jajajaja que jugada"}]}
                        }
                    }
                }
            }]
        }
    })
    line2 = json.dumps({
        "replayChatItemAction": {
            "videoOffsetTimeMsec": "15000",
            "actions": [{
                "addChatItemAction": {
                    "item": {
                        "liveChatTextMessageRenderer": {
                            "message": {"runs": [{"text": "WTFFF 🔥"}]}
                        }
                    }
                }
            }]
        }
    })
    chat_file = tmp_path / "yt.live_chat.json"
    chat_file.write_text(f"{line1}\n{line2}\n", encoding="utf-8")

    msgs = parse_chat_messages(chat_file)
    assert len(msgs) == 2
    assert msgs[0].t == 14.0
    assert "jajajaja" in msgs[0].text
    assert msgs[1].t == 15.0
    assert "WTFFF" in msgs[1].text


def test_build_chat_profile_detects_hype_burst():
    # 0s..20s: 1 mensaje cada 5s (tranquilo)
    # 25s..35s: ráfaga de 30 mensajes con "LUL", "OMG", "KEKW"
    # 40s..60s: 1 mensaje cada 10s
    messages = []
    for t in range(0, 20, 5):
        messages.append(ChatMessage(t=float(t), text="hola que tal"))
    for t in [25.0, 25.5, 26.0, 26.5, 27.0, 27.5, 28.0, 28.5, 29.0, 30.0, 31.0, 32.0, 33.0, 34.0, 35.0]:
        messages.append(ChatMessage(t=t, text="LUL KEKW NO WAY OMG ??? 😂🔥"))
    for t in range(40, 60, 10):
        messages.append(ChatMessage(t=float(t), text="gg"))

    profile = build_chat_profile(messages, duration=60.0, hop=2.0, window_sec=10.0)
    assert profile is not None
    assert len(profile.norm) > 0

    quiet_score = profile.window_score(0.0, 15.0)
    burst_score = profile.window_score(25.0, 35.0)

    assert burst_score > quiet_score
    assert burst_score >= 0.70

    peaks = find_chat_hype_peaks(profile, min_duration=10.0, max_duration=25.0, top_n=1)
    assert len(peaks) == 1
    p_start, p_end, p_score = peaks[0]
    assert 20.0 <= p_start <= 30.0
    assert p_score > 0.6


def test_chat_bonus_calculation():
    assert chat_bonus(0.5) == 0.0
    assert chat_bonus(1.0, max_points=10.0) == 10.0
    assert chat_bonus(0.0, max_points=10.0) == -10.0
    assert chat_bonus(0.75, max_points=8.0) == 4.0


def test_detector_integrates_chat_profile(monkeypatch):
    detector = ViralMomentDetector(min_duration=10.0, max_duration=30.0, max_candidates=5)

    segments = [
        TranscriptSegment(id=0, start=0.0, end=15.0, text="Introducción normal al directo.", words=[
            WordTimestamp(word="Introducción", start=0.0, end=5.0),
            WordTimestamp(word="normal.", start=5.0, end=15.0),
        ]),
        TranscriptSegment(id=1, start=15.0, end=35.0, text="Momento cumbre de risas y jugada épica increíble.", words=[
            WordTimestamp(word="Momento", start=15.0, end=20.0),
            WordTimestamp(word="cumbre", start=20.0, end=25.0),
            WordTimestamp(word="increíble.", start=25.0, end=35.0),
        ]),
        TranscriptSegment(id=2, start=35.0, end=50.0, text="Despedida y fin de la partida.", words=[
            WordTimestamp(word="Despedida", start=35.0, end=40.0),
            WordTimestamp(word="fin.", start=40.0, end=50.0),
        ]),
    ]
    transcript = TranscriptResult(video_path="test.mp4", segments=segments, language="es", duration=50.0)

    chat_msgs = [
        ChatMessage(t=20.0, text="OMG LUL 😂"),
        ChatMessage(t=21.0, text="KEKW NO WAY 🔥"),
        ChatMessage(t=22.0, text="POGGG CLIP IT"),
        ChatMessage(t=23.0, text="JAJAJAJA"),
        ChatMessage(t=24.0, text="WTFFF ???"),
    ]
    profile = build_chat_profile(chat_msgs, duration=50.0, hop=2.0, window_sec=10.0)

    candidates = detector.detect_moments(
        transcript, use_llm=False, chat_profile=profile
    )
    assert len(candidates) > 0
    # Al menos un candidato debe reflejar el chat o tener mención de chat en su razonamiento
    has_chat_mention = any("chat" in c.reasoning.lower() for c in candidates)
    assert has_chat_mention
