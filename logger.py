"""
logger.py — Structured logging via loguru.
Import `log` from here everywhere.
"""
import sys
from loguru import logger as log

from src.config import LOG_LEVEL, DATA_DIR
import os

os.makedirs(DATA_DIR, exist_ok=True)

log.remove()

# Console — visible in Northflank dashboard
log.add(
    sys.stdout,
    level=LOG_LEVEL,
    colorize=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
           "<level>{level:<8}</level> | "
           "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
           "<level>{message}</level>",
)

# File — rotated, compressed
log.add(
    os.path.join(DATA_DIR, "ids_bot.log"),
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} — {message}",
)
