"""Local dashboard server for autopilot-jobhunt."""
from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path.cwd()
STATE_DIR = ROOT / "state"
LOG_FILE = ROOT / "scan.log"
STATIC_DIR = ROOT / "ui" / "dist"
CONFIG_FILE = ROOT / "config.json"
COMPANIES_FILE = ROOT / "companies.json"

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
_SCAN_PROGRESS_RE = re.compile(r"\[(?P<current>\d+)/(?P<total>\d+)\]\s+Scanning\s+(?P<company>.+?)(?:\.\.\.)?$")


def _read_json(filename: str, default):
    try:
        return json.loads((STATE_DIR / filename).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _read_project_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
    active_task: str | None = None
    for entry in entries:
        message = entry["message"]
        start = _START_RE.search(message)
        finish = _FINISH_RE.search(message)
        if start:
            task = start.group("task")
            state = states.setdefault(task, {"name": task})
            state.update({"running": True, "started_at": entry["timestamp"], "phase": "starting"})
            active_task = task

        progress = _SCAN_PROGRESS_RE.search(message)
        if progress and active_task:
            current = int(progress.group("current"))
            total = int(progress.group("total"))
            state = states.setdefault(active_task, {"name": active_task, "running": True})
            state.update(
                {
                    "phase": "scanning companies",
                    "progress": {
                        "current": current,
                        "total": total,
                        "company": progress.group("company"),
                        "percent": round((current / total) * 100) if total else 0,
                    },
                    "last_update": entry["timestamp"],
                }
            )
        elif active_task and "Fetching details" in message:
            states[active_task].update({"phase": "fetching job details", "last_update": entry["timestamp"]})
        elif active_task and "Scoring" in message:
            states[active_task].update({"phase": "scoring matches", "last_update": entry["timestamp"]})
        elif active_task and "State saved" in message:
            states[active_task].update({"phase": "saving results", "last_update": entry["timestamp"]})

        if finish:
            task = finish.group("finished") or finish.group("job")
            state = states.setdefault(task, {"name": task})
            state.update({"running": False, "phase": "complete", "finished_at": entry["timestamp"]})
            if active_task == task:
                active_task = None
    return states


def _scan_snapshot(entries: list[dict], task_states: dict[str, dict]) -> dict:
    running = [task for task in task_states.values() if task.get("running")]
    active = running[0] if running else None
    latest = entries[-1] if entries else {}
    return {
        "active": bool(active),
        "task": active.get("name", "") if active else "",
        "phase": active.get("phase", "") if active else "",
        "started_at": active.get("started_at", "") if active else "",
        "last_log_at": latest.get("timestamp", ""),
        "last_message": latest.get("message", ""),
        "progress": active.get("progress") if active else None,
    }


def _ui_profile(config: dict) -> dict:
    candidate = config.get("candidate", {}) if isinstance(config, dict) else {}
    resume_value = str(candidate.get("resume_path") or "")
    resume_path = Path(resume_value)
    if not resume_path.is_absolute():
        resume_path = ROOT / resume_path
    return {
        "name": candidate.get("name") or "Candidate profile",
        "profile": candidate.get("profile") or "",
        "seeking": candidate.get("seeking") or "",
        "not_suitable": candidate.get("not_suitable") or "",
        "min_score": candidate.get("min_score"),
        "top_n": candidate.get("top_n"),
        "included_titles": [str(value) for value in candidate.get("included_titles", []) if value],
        "excluded_titles": [str(value) for value in candidate.get("excluded_titles", []) if value],
        "excluded_locations": [str(value) for value in candidate.get("excluded_locations", []) if value],
        "relocation_note": candidate.get("relocation_note") or "",
        "resume_file": resume_path.name if resume_value else "",
        "resume_exists": resume_path.is_file(),
    }


def _ui_search_config(config: dict, companies: list) -> dict:
    apify = config.get("apify_linkedin", {}) if isinstance(config, dict) else {}
    service = config.get("service", {}) if isinstance(config, dict) else {}
    experience_labels = {
        "1": "Internship",
        "2": "Entry level",
        "3": "Associate",
        "4": "Mid-senior",
        "5": "Director",
        "6": "Executive",
    }
    contract_labels = {
        "F": "Full-time",
        "P": "Part-time",
        "C": "Contract",
        "T": "Temporary",
        "V": "Volunteer",
        "I": "Internship",
    }
    remote_labels = {"1": "On-site", "2": "Remote", "3": "Hybrid"}
    date_posted = str(apify.get("datePosted") or "")
    date_posted_label = date_posted
    if date_posted.startswith("r") and date_posted[1:].isdigit():
        hours = int(date_posted[1:]) // 3600
        date_posted_label = f"{hours // 24} days" if hours >= 24 else f"{hours} hours"

    def labels(values, mapping):
        return [mapping.get(str(value), str(value)) for value in values if value]

    def cadence(cron):
        match = re.fullmatch(r"0 \*/(?P<hours>\d+) \* \* \*", str(cron))
        return f"Every {match.group('hours')} hours" if match else str(cron)

    return {
        "linkedin": {
            "enabled": bool(apify.get("enabled")),
            "query": apify.get("title") or "",
            "location": apify.get("location") or "",
            "limit": apify.get("limit"),
            "date_posted": date_posted,
            "date_posted_label": date_posted_label,
            "max_age_hours": apify.get("maxAgeHours"),
            "experience_levels": labels(apify.get("experienceLevel", []), experience_labels),
            "contract_types": labels(apify.get("contractType", []), contract_labels),
            "remote_modes": labels(apify.get("remote", []), remote_labels),
            "keywords": [str(value) for value in apify.get("keywords", []) if value],
            "exclude_keywords": [str(value) for value in apify.get("excludeKeywords", []) if value],
        },
        "careers": {
            "company_count": len(companies) if isinstance(companies, list) else 0,
            "keywords": [str(value) for value in config.get("candidate", {}).get("included_titles", []) if value],
            "exclude_keywords": [str(value) for value in config.get("candidate", {}).get("excluded_titles", []) if value],
            "exclude_locations": [str(value) for value in config.get("candidate", {}).get("excluded_locations", []) if value],
        },
        "schedules": [
            {
                "name": schedule.get("name", ""),
                "action": schedule.get("action", ""),
                "cron": schedule.get("cron", ""),
                "cadence": cadence(schedule.get("cron", "")),
            }
            for schedule in service.get("schedules", [])
            if isinstance(schedule, dict)
        ],
        "timezone": service.get("timezone") or "",
    }


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


def _company_for_ui(company: dict, history: list) -> dict:
    name = str(company.get("name") or "Unnamed company")
    company_jobs = [
        job for job in history
        if isinstance(job, dict) and str(job.get("company") or "").casefold() == name.casefold()
    ]
    careers_urls = company.get("careers_urls") or []
    if not isinstance(careers_urls, list):
        careers_urls = []
    urls = [str(company.get("careers_url") or "")] + [str(url) for url in careers_urls if url]
    unique_urls = list(dict.fromkeys(url for url in urls if url))
    last_job = max((str(job.get("scan_date") or "") for job in company_jobs), default="")
    return {
        "name": name,
        "careers_url": unique_urls[0] if unique_urls else "",
        "careers_urls": unique_urls,
        "search_domain": str(company.get("search_domain") or ""),
        "location": str(company.get("location") or "Location not specified"),
        "region": str(company.get("region") or "Unclassified"),
        "jobs_found": len(company_jobs),
        "last_job_at": last_job,
        "source_status": "configured",
    }


def _add_company(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be an object")

    name = str(payload.get("name") or "").strip()
    careers_url = str(payload.get("careers_url") or "").strip()
    parsed_url = urlparse(careers_url)
    if not 2 <= len(name) <= 120:
        raise ValueError("Company name must be between 2 and 120 characters")
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or parsed_url.username:
        raise ValueError("Careers URL must be a valid http or https URL")

    hostname = parsed_url.hostname.casefold().strip(".")
    try:
        host_address = ipaddress.ip_address(hostname)
    except ValueError:
        host_address = None
    if host_address and not host_address.is_global:
        raise ValueError("Careers URL must use a public domain")
    if "." not in hostname or not re.fullmatch(r"[a-z0-9.-]+", hostname):
        raise ValueError("Careers URL must use a public domain")
    search_domain = str(payload.get("search_domain") or hostname.removeprefix("www.")).strip().casefold().strip(".")
    if len(search_domain) > 255 or not re.fullmatch(r"[a-z0-9.-]+", search_domain) or "." not in search_domain:
        raise ValueError("Search domain must be a valid domain name")

    location = str(payload.get("location") or "Location not specified").strip()[:160]
    region = str(payload.get("region") or "Unclassified").strip()[:40]
    company = {
        "name": name,
        "careers_url": careers_url,
        "search_domain": search_domain,
        "location": location or "Location not specified",
        "region": region or "Unclassified",
    }

    companies = _read_project_json(COMPANIES_FILE, [])
    if not isinstance(companies, list):
        raise ValueError("companies.json is not a list")
    normalized_url = careers_url.rstrip("/").casefold()
    for existing in companies:
        if not isinstance(existing, dict):
            continue
        existing_url = str(existing.get("careers_url") or "").rstrip("/").casefold()
        if str(existing.get("name") or "").strip().casefold() == name.casefold() or existing_url == normalized_url:
            raise FileExistsError("That company or careers URL is already configured")

    companies.append(company)
    serialized = json.dumps(companies, ensure_ascii=False, indent=2) + "\n"
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=COMPANIES_FILE.parent, prefix=".companies.", delete=False
        ) as temporary:
            temporary.write(serialized)
            temporary_path = temporary.name
        os.replace(temporary_path, COMPANIES_FILE)
    except OSError:
        if "temporary_path" in locals():
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise
    return _company_for_ui(company, [])


def _history_analytics(history: list) -> dict:
    jobs = [job for job in history if isinstance(job, dict)]
    scores = [job.get("score") for job in jobs if isinstance(job.get("score"), (int, float))]
    source_counts = {"linkedin": 0, "careers": 0}
    company_counts: dict[str, int] = {}
    location_counts: dict[str, int] = {}
    for job in jobs:
        source = "linkedin" if job.get("source") in {"linkedin", "apify_linkedin"} else "careers"
        source_counts[source] += 1
        company = str(job.get("company") or "Unknown company")
        location = str(job.get("location") or "Location not listed")
        company_counts[company] = company_counts.get(company, 0) + 1
        location_counts[location] = location_counts.get(location, 0) + 1

    def ranked(values: dict[str, int], limit: int = 6) -> list[dict]:
        return [
            {"label": label, "count": count}
            for label, count in sorted(values.items(), key=lambda item: (-item[1], item[0].lower()))[:limit]
        ]

    return {
        "total": len(jobs),
        "scored": len(scores),
        "average_score": round(sum(scores) / len(scores)) if scores else None,
        "high_score": sum(score >= 80 for score in scores),
        "target_score": sum(score >= 60 for score in scores),
        "sources": source_counts,
        "score_buckets": [
            {"label": "80+", "count": sum(score >= 80 for score in scores)},
            {"label": "60–79", "count": sum(60 <= score < 80 for score in scores)},
            {"label": "Below 60", "count": sum(score < 60 for score in scores)},
        ],
        "top_companies": ranked(company_counts),
        "top_locations": ranked(location_counts),
    }


def _scan_runs(entries: list[dict]) -> list[dict]:
    runs: list[dict] = []
    for entry in entries:
        message = entry["message"]
        apify_match = _APIFY_COMPLETE_RE.search(message)
        if apify_match:
            runs.append(
                {
                    "source": "linkedin",
                    "label": "LinkedIn discovery",
                    "timestamp": entry["timestamp"],
                    "jobs": int(apify_match.group("jobs")),
                    "top_matches": int(apify_match.group("top")),
                    "companies": None,
                    "total_companies": None,
                }
            )
        careers_match = _CAREERS_COMPLETE_RE.search(message)
        if careers_match:
            runs.append(
                {
                    "source": "careers",
                    "label": "Company careers",
                    "timestamp": entry["timestamp"],
                    "jobs": int(careers_match.group("jobs")),
                    "top_matches": int(careers_match.group("top")),
                    "companies": int(careers_match.group("companies")),
                    "total_companies": int(careers_match.group("total")),
                }
            )
    return list(reversed(runs[-16:]))


def build_dashboard() -> dict:
    last_scan = _read_json("last_scan.json", [])
    history = _read_json("job_history.json", [])
    seen = _read_json("seen_jobs.json", {})
    config = _read_project_json(CONFIG_FILE, {})
    companies = _read_project_json(COMPANIES_FILE, [])
    entries = _log_entries()
    task_states = _task_states(entries)
    scan = _scan_snapshot(entries, task_states)

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
        "scan": scan,
        "profile": _ui_profile(config),
        "search": _ui_search_config(config, companies),
        "summary": {
            "new_jobs": len(last_scan) if isinstance(last_scan, list) else 0,
            "history_jobs": len(history) if isinstance(history, list) else 0,
            "seen_urls": len(seen.get("seen_urls", [])) if isinstance(seen, dict) else 0,
            "seen_linkedin_ids": len(seen.get("seen_apify_job_ids", [])) if isinstance(seen, dict) else 0,
        },
        "latest": {"apify": latest_apify, "careers": latest_careers},
        "analytics": _history_analytics(history) if isinstance(history, list) else _history_analytics([]),
        "runs": _scan_runs(entries),
        "companies": [_company_for_ui(company, history if isinstance(history, list) else []) for company in companies if isinstance(company, dict)],
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

    def _send_json(self, payload: dict, status: int = 200) -> None:
        self._send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

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

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path != "/api/companies":
            self._send_json({"error": "Not found"}, 404)
            return

        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname != self.headers.get("Host", "").split(":", 1)[0]:
            self._send_json({"error": "Cross-origin writes are not allowed"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                raise ValueError("Request body is missing or too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            company = _add_company(payload)
        except json.JSONDecodeError:
            self._send_json({"error": "Request body must be valid JSON"}, 400)
            return
        except FileExistsError as error:
            self._send_json({"error": str(error)}, 409)
            return
        except ValueError as error:
            self._send_json({"error": str(error)}, 400)
            return
        except OSError:
            self._send_json({"error": "Could not update companies.json"}, 500)
            return
        self._send_json({"company": company}, 201)

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
