import logging
import os
import sys
from pathlib import Path


def get_logger(name: str = "autopilot") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console level is INFO by default; set LOG_LEVEL=DEBUG for full per-URL/per-job
    # detail on stdout (the scan.log file always captures DEBUG regardless).
    if os.getenv("AUTOPILOT_CONSOLE_LOG", "1") != "0":
        console_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(console_level)
        console.setFormatter(fmt)
        logger.addHandler(console)

    try:
        log_path = Path(os.getenv("AUTOPILOT_LOG_FILE", "scan.log"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        pass

    return logger
