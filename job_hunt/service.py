"""Long-running scheduler service for autopilot-jobhunt."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from job_hunt.log import get_logger
from job_hunt.main import export_jobs, load_companies, load_config
from job_hunt.scanner import run_apify_scan, run_scan

logger = get_logger("autopilot.service")

_RUN_LOCK = threading.Lock()


@dataclass(frozen=True)
class ScheduledTask:
    name: str
    action: str
    cron: str
    args: dict[str, int] | None = None


def _default_tasks() -> list[ScheduledTask]:
    return [
        ScheduledTask(name="apify_scan_10h", action="apify_scan", cron="0 */10 * * *"),
        ScheduledTask(name="careers_scan_3h", action="scan", cron="0 */3 * * *"),
    ]


def _load_tasks(config: dict) -> list[ScheduledTask]:
    service_cfg = config.get("service", {})
    raw_tasks = service_cfg.get("schedules") or service_cfg.get("tasks") or []
    tasks: list[ScheduledTask] = []
    for idx, raw in enumerate(raw_tasks, 1):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or f"task_{idx}")
        action = str(raw.get("action") or "scan").lower()
        cron = str(raw.get("cron") or "").strip()
        if not cron:
            continue
        args = raw.get("args") if isinstance(raw.get("args"), dict) else None
        tasks.append(ScheduledTask(name=name, action=action, cron=cron, args=args))
    return tasks or _default_tasks()


def _run_with_lock(name: str, fn: Callable[[], None]) -> None:
    if not _RUN_LOCK.acquire(blocking=False):
        logger.warning("Skip %s: another job is still running", name)
        return
    try:
        logger.info("Starting %s", name)
        fn()
        logger.info("Finished %s", name)
    finally:
        _RUN_LOCK.release()


def _scan_task() -> None:
    config = load_config()
    companies = load_companies()
    run_scan(config, companies)


def _apify_scan_task() -> None:
    config = load_config()
    run_apify_scan(config)


def _export_task(min_score: int = 0, days: int = 0) -> None:
    export_jobs(min_score=min_score, days=days)


def _execute(task: ScheduledTask) -> None:
    if task.action == "scan":
        _run_with_lock(task.name, _scan_task)
        return
    if task.action == "apify_scan":
        _run_with_lock(task.name, _apify_scan_task)
        return
    if task.action == "export":
        args = task.args or {}
        min_score = int(args.get("min_score", 0))
        days = int(args.get("days", 0))
        _run_with_lock(task.name, lambda: _export_task(min_score=min_score, days=days))
        return
    logger.warning("Skip %s: unsupported action %r", task.name, task.action)


def _log_scheduler_event(event) -> None:
    if event.code == EVENT_JOB_EXECUTED:
        logger.info("Job %s completed", event.job_id)
    elif event.code == EVENT_JOB_ERROR:
        logger.error("Job %s failed", event.job_id)
    elif event.code == EVENT_JOB_MISSED:
        logger.warning("Job %s missed its schedule", event.job_id)


def build_scheduler(config: dict | None = None) -> BackgroundScheduler:
    config = config or load_config()
    service_cfg = config.get("service", {})
    timezone_name = service_cfg.get("timezone")
    tz = ZoneInfo(timezone_name) if timezone_name else None
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_listener(_log_scheduler_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)

    tasks = _load_tasks(config)
    for task in tasks:
        trigger = CronTrigger.from_crontab(task.cron, timezone=tz)
        scheduler.add_job(
            _execute,
            trigger=trigger,
            args=[task],
            id=task.name,
            name=task.name,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        logger.info("Scheduled %s -> %s at %s", task.name, task.action, task.cron)

    return scheduler


def run_service() -> None:
    config = load_config()
    scheduler = build_scheduler(config)
    scheduler.start()
    logger.info("Service started with %d job(s)", len(scheduler.get_jobs()))

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Service stopping")
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Service stopped")
