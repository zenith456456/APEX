"""logger_setup.py ─ Coloured structured logging for APEX-QUANT"""
import logging
import sys
import colorlog
from config import cfg


def get_logger(name: str) -> logging.Logger:
    handler = colorlog.StreamHandler(sys.stdout)
    handler.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)-8s] %(name)s%(reset)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG":    "cyan",
            "INFO":     "green",
            "WARNING":  "yellow",
            "ERROR":    "red",
            "CRITICAL": "bold_red",
        },
    ))
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO))
    if not logger.handlers:
        logger.addHandler(handler)
    logger.propagate = False
    return logger
