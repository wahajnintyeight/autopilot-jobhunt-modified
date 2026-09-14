"""Local read-only dashboard server for autopilot-jobhunt."""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path.cwd()
STATE_DIR = ROOT / "state"
LOG_FILE = ROOT / "scan.log"
STATIC_DIR = ROOT / "ui" / "dist"

_LOG_RE = re.compile(r"^\[(?P<timestamp>[^]]+)\]\s+(?P<level>\w+)\s+(?P<message>.*)$")
_START_RE = re.compile(r"Starting (?P<task>[\w-]+)")
_FINISH_RE = re.compile(r"(?:Finished (?P<finished>[\w-]+)|Job (?P<job>[\w-]+) completed)")
_APIFY_COMPLETE_RE = re.compile(
    r"=== Apify LinkedIn scan complete — (?P<jobs>\d+) jobs found, (?P<top>\d+) top matches"
)
_CAREERS_COMPLETE_RE = re.compile(
    r"=== Scan complete — (?P<companies>\d+)/(?P<total>\d+) companies, "
    r"(?P<jobs>\d+) jobs found, (?P<top>\d+) top matches"
)


def _read_json(filename: str, default):
    try:
        return json.loads((STATE_DIR / filename).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _parse_timestamp(value: str) -> str:
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value.replace(" ", "T")
    except ValueError:
        return value


def _log_entries() -> list[dict]:
    try:
        with LOG_FILE.open("rb") as log:
            log.seek(0, 2)
            log.seek(max(0, log.tell() - 1_000_000))
            lines = log.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []

    entries = []
    for line in lines[-5000:]:
        match = _LOG_RE.match(line)
        if not match:
            continue
        entries.append(
            {
                "timestamp": _parse_timestamp(match.group("timestamp")),
                "level": match.group("level"),
                "message": match.group("message"),
            }
        )
    return entries


def _task_states(entries: list[dict]) -> dict[str, dict]:
    states: dict[str, dict] = {}
    for entry in entries:
        message = entry["message"]
        start = _START_RE.search(message)
        finish = _FINISH_RE.search(message)
        if start:
            task = start.group("task")
            states[task] = {"name": task, "running": True, "started_at": entry["timestamp"]}
        elif finish:
            task = finish.group("finished") or finish.group("job")
            state = states.setdefault(task, {"name": task})
            state.update({"running": False, "finished_at": entry["timestamp"]})
    return states


def _service_state() -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "autopilot-jobhunt"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.stdout.strip() or "unknown"
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return "unknown"


def _job_for_ui(job: dict) -> dict:
    content = str(job.get("content") or job.get("snippet") or "")
    return {
        "url": job.get("url", ""),
        "title": job.get("extracted_title") or job.get("title") or "Untitled role",
        "company": job.get("company") or "Unknown company",
        "location": job.get("location") or "Location not listed",
        "region": job.get("region") or "",
        "score": job.get("score"),
        "source": job.get("source") or ("linkedin" if "linkedin.com" in str(job.get("url")) else "careers"),
        "scan_date": job.get("scan_date") or "",
        "reason": job.get("reason") or "",
        "stack": job.get("stack") or "",
        "worth_applying": job.get("worth_applying"),
        "content": content[:1200],
    }


def build_dashboard() -> dict:
    last_scan = _read_json("last_scan.json", [])
    history = _read_json("job_history.json", [])
    seen = _read_json("seen_jobs.json", {})
    entries = _log_entries()
    task_states = _task_states(entries)

    recent_events = []
    seen_event_keys: set[tuple[str, str]] = set()
    for entry in reversed(entries):
        key = (entry["timestamp"], entry["message"])
        if key in seen_event_keys:
            continue
        seen_event_keys.add(key)
        recent_events.append(entry)
        if len(recent_events) == 12:
            break

    latest_apify = None
    latest_careers = None
    for entry in entries:
        apify_match = _APIFY_COMPLETE_RE.search(entry["message"])
        if apify_match:
            latest_apify = {
                "timestamp": entry["timestamp"],
                "jobs": int(apify_match.group("jobs")),
                "top_matches": int(apify_match.group("top")),
            }
        careers_match = _CAREERS_COMPLETE_RE.search(entry["message"])
        if careers_match:
            latest_careers = {
                "timestamp": entry["timestamp"],
                "companies": int(careers_match.group("companies")),
                "total_companies": int(careers_match.group("total")),
                "jobs": int(careers_match.group("jobs")),
                "top_matches": int(careers_match.group("top")),
            }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "service": {"state": _service_state(), "tasks": list(task_states.values())},
        "summary": {
            "new_jobs": len(last_scan) if isinstance(last_scan, list) else 0,
            "history_jobs": len(history) if isinstance(history, list) else 0,
            "seen_urls": len(seen.get("seen_urls", [])) if isinstance(seen, dict) else 0,
            "seen_linkedin_ids": len(seen.get("seen_apify_job_ids", [])) if isinstance(seen, dict) else 0,
        },
        "latest": {"apify": latest_apify, "careers": latest_careers},
        "events": recent_events,
        "new_jobs": [_job_for_ui(job) for job in last_scan] if isinstance(last_scan, list) else [],
        "history": [_job_for_ui(job) for job in reversed(history)] if isinstance(history, list) else [],
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AutopilotDashboard/1.0"

    def _send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path == "/api/dashboard":
            body = json.dumps(build_dashboard(), ensure_ascii=False).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8")
            return

        if not STATIC_DIR.exists():
            self._send_bytes(b"Build the UI first with: cd ui && npm run build\n", "text/plain; charset=utf-8", 503)
            return

        relative = path.lstrip("/") or "index.html"
        candidate = (STATIC_DIR / relative).resolve()
        if STATIC_DIR not in candidate.parents and candidate != STATIC_DIR:
            self._send_bytes(b"Not found", "text/plain; charset=utf-8", 404)
            return
        if not candidate.is_file():
            candidate = STATIC_DIR / "index.html"
        try:
            self._send_bytes(candidate.read_bytes(), mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        except OSError:
            self._send_bytes(b"Not found", "text/plain; charset=utf-8", 404)

    def log_message(self, format: str, *args) -> None:
        return


def run_ui_server(host: str = "127.0.0.1", port: int = 4173) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"Autopilot dashboard: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve the local autopilot dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args(argv)
    run_ui_server(args.host, args.port)


if __name__ == "__main__":
    main()
