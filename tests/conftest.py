"""Aísla las pruebas: usan una base de datos temporal en vez de data/clip_factory.db."""
import os
import tempfile
from pathlib import Path

# Debe ejecutarse antes de importar src.* (la BD global se crea al importar).
_tmp = Path(tempfile.mkdtemp(prefix="clipfactory_tests_"))
os.environ["CLIP_DB_PATH"] = str(_tmp / "tests.sqlite")
os.environ["CLIP_NO_WORKER"] = "1"
# Que el token real de data/api_token.txt no active la autenticación durante las pruebas
os.environ["CLIP_TOKEN_FILE"] = str(_tmp / "sin_token.txt")
