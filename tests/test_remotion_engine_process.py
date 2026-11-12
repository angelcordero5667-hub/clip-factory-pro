"""Gestión de procesos del motor Remotion: cancelación, tiempo máximo y limpieza (sin necesitar Node ni Chromium)."""
import subprocess
import sys
import threading
import time

import psutil
import pytest

from src.common import remotion_engine as re_mod
from src.common.remotion_engine import RemotionEngine, kill_process_tree

# Un "render" simulado: un proceso padre que a su vez lanza un hijo (como npx → node → Chromium)
PARENT_WITH_CHILD = (
    "import subprocess, sys, time;"
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
    "print('Rendered 1/10', flush=True); time.sleep(120)"
)


def _tree_alive(root_pid):
    try:
        root = psutil.Process(root_pid)
    except psutil.Error:
        return []
    return [p for p in root.children(recursive=True) + [root] if p.is_running()]


def test_kill_process_tree_kills_children_too():
    proc = subprocess.Popen([sys.executable, "-c", PARENT_WITH_CHILD], stdout=subprocess.PIPE, text=True)
    proc.stdout.readline()          # esperar a que el padre haya lanzado a su hijo
    time.sleep(0.5)
    kids = psutil.Process(proc.pid).children(recursive=True)
    assert kids, "el hijo debería existir antes de matar"
    assert kill_process_tree(proc.pid) >= 2
    proc.wait(timeout=5)
    assert not any(k.is_running() for k in kids)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = RemotionEngine()
    monkeypatch.setattr(eng, "is_available", lambda: True)
    monkeypatch.setattr(eng, "cache_dir", tmp_path / "rcache")
    eng.cache_dir.mkdir()
    real_popen = subprocess.Popen
    started = []

    def fake_popen(cmd, **kw):   # ignora el comando real de npx y lanza el árbol simulado
        p = real_popen([sys.executable, "-c", PARENT_WITH_CHILD], **{k: v for k, v in kw.items() if k != "cwd"})
        started.append(p.pid)
        return p

    monkeypatch.setattr(re_mod.subprocess, "Popen", fake_popen)
    eng._started = started
    eng._real_popen = real_popen   # el parche cambia subprocess.Popen globalmente: guardar el original
    return eng


def test_cancel_kills_whole_tree_and_cleans_up(engine, tmp_path):
    out = tmp_path / "out.mp4"
    ev = threading.Event()
    threading.Timer(1.5, ev.set).start()
    t0 = time.time()
    with pytest.raises(RuntimeError, match="cancelado"):
        engine.render_clip({"videoSrc": "https://x/y.mp4", "durationInFrames": 10}, out, cancel_event=ev, timeout_s=60)
    assert time.time() - t0 < 15
    assert not _tree_alive(engine._started[0])               # ni el padre ni el hijo siguen vivos
    assert not out.exists()
    assert list(engine.cache_dir.glob("props_*.json")) == []  # props temporales borrados


def test_timeout_kills_tree_and_reports(engine, tmp_path):
    with pytest.raises(RuntimeError, match="tiempo máximo"):
        engine.render_clip({"videoSrc": "https://x/y.mp4", "durationInFrames": 10}, tmp_path / "o.mp4", timeout_s=2)
    assert not _tree_alive(engine._started[0])
    assert list(engine.cache_dir.glob("props_*.json")) == []


def test_props_file_names_are_unique_per_render(engine, tmp_path, monkeypatch):
    seen = []
    orig_dump = re_mod.json.dump

    def spy(obj, f, **kw):
        seen.append(f.name)
        return orig_dump(obj, f, **kw)

    monkeypatch.setattr(re_mod.json, "dump", spy)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            engine.render_clip({"videoSrc": "https://x/y.mp4", "durationInFrames": 10}, tmp_path / "o.mp4", timeout_s=1)
    assert len(set(seen)) == 2


def test_failed_render_reports_real_error_and_no_orphans(engine, tmp_path, monkeypatch):
    real_popen = engine._real_popen

    def failing(cmd, **kw):
        return real_popen([sys.executable, "-c", "import sys; print('Error: boom', flush=True); sys.exit(3)"],
                          **{k: v for k, v in kw.items() if k != "cwd"})

    monkeypatch.setattr(re_mod.subprocess, "Popen", failing)
    with pytest.raises(RuntimeError, match="boom"):
        engine.render_clip({"videoSrc": "https://x/y.mp4", "durationInFrames": 10}, tmp_path / "o.mp4", timeout_s=30)
