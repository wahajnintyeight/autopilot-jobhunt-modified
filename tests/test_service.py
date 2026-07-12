"""Service scheduler wiring."""

from job_hunt import service


def test_build_scheduler_defaults_include_apify_and_scan():
    scheduler = service.build_scheduler({"service": {}})
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {"apify_scan_hourly", "careers_scan_3h"}
    assert jobs["apify_scan_hourly"].args[0].action == "apify_scan"
    assert jobs["careers_scan_3h"].args[0].action == "scan"


def test_build_scheduler_uses_cron_tasks():
    cfg = {
        "service": {
            "timezone": "UTC",
            "schedules": [
                {"name": "apify_hourly", "action": "apify_scan", "cron": "0 * * * *"},
                {"name": "morning_scan", "action": "scan", "cron": "30 2 * * *"},
                {"name": "midday_export", "action": "export", "cron": "0 12 * * *",
                 "args": {"min_score": 70, "days": 7}},
            ],
        }
    }

    scheduler = service.build_scheduler(cfg)
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {"apify_hourly", "morning_scan", "midday_export"}
    assert jobs["apify_hourly"].args[0].action == "apify_scan"
    assert jobs["midday_export"].args[0].action == "export"
    assert jobs["midday_export"].args[0].args == {"min_score": 70, "days": 7}
