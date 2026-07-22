import os, sys
from loguru import logger as log
import config

os.makedirs(config.DATA_DIR, exist_ok=True)
log.remove()
log.add(sys.stdout, level=config.LOG_LEVEL, colorize=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>")
log.add(os.path.join(config.DATA_DIR, "ids_bot.log"),
    level="DEBUG", rotation="10 MB", retention="7 days", compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} — {message}")
