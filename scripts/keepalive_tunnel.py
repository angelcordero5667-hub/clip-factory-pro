"""Keepalive daemon para evitar que Cloudflare cierre el tunel por inactividad."""
import time
import urllib.request
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("keepalive")

TUNNEL_URL = sys.argv[1] if len(sys.argv) > 1 else "https://config-leads-arrow-jpeg.trycloudflare.com"
TARGET = f"{TUNNEL_URL.rstrip('/')}/api/health"

logger.info(f"Iniciando keepalive hacia {TARGET} cada 15 segundos...")

while True:
    try:
        req = urllib.request.Request(TARGET, headers={"User-Agent": "ClipFactoryKeepAlive/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                logger.debug("Keepalive ping OK (200)")
    except Exception as e:
        logger.warning(f"Keepalive ping warning: {e}")
    time.sleep(15)
