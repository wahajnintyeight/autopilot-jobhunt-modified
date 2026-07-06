"""Simple realtime log follower."""
from __future__ import annotations

import time
from pathlib import Path


def tail_file(path: str | Path, *, start_from_end: bool = True) -> None:
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)

    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        if start_from_end:
            fh.seek(0, 2)
        while True:
            line = fh.readline()
            if line:
                print(line, end="")
                continue
            time.sleep(0.5)
