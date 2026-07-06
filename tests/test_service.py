"""Service scheduler wiring."""

from job_hunt import service


def test_build_scheduler_uses_cron_tasks():
    cfg = {
        "service": {
            "timezone": "UTC",
            "schedules": [
                {"name": "morning_scan", "action": "scan", "cron": "30 2 * * *"},
                {"name": "midday_export", "action": "export", "cron": "0 12 * * *",
                 "args": {"min_score": 70, "days": 7}},
            ],
        }
    }

    scheduler = service.build_scheduler(cfg)
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {"morning_scan", "midday_export"}
    assert jobs["midday_export"].args[0].action == "export"
    assert jobs["midday_export"].args[0].args == {"min_score": 70, "days": 7}
