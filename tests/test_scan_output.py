"""run_scan output behavior — CSV is always written; Telegram is optional.

- No Telegram configured  -> CSV saved, send_telegram NOT called, no error.
- Telegram configured      -> CSV saved AND send_telegram called.
"""
import csv

import pytest

from job_hunt import scanner


@pytest.fixture
def scan_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resume = tmp_path / "resume.md"
    resume.write_text("Senior ML/AI engineer, 10 YOE.")

    # Stub the whole discovery/fetch/score pipeline so the test is deterministic
    # and makes no network or LLM calls.
    monkeypatch.setattr(scanner, "TinyFish", lambda **_: object())
    monkeypatch.setattr(scanner, "discover_job_urls", lambda tf, co, seen: [
        {"url": "https://x.co/jobs/1", "title": "ML Engineer",
         "company": co["name"], "location": co["location"], "region": co["region"]},
    ])
    monkeypatch.setattr(scanner, "fetch_job_details", lambda tf, jobs: jobs)
    monkeypatch.setattr(scanner, "score_jobs", lambda jobs, resume, config: [
        {**jobs[0], "score": 90, "extracted_title": "ML Engineer",
         "stack": "Python, LLMs", "location_remote": "Remote", "reason": "Strong fit"},
    ])

    calls = []
    monkeypatch.setattr(scanner, "send_telegram",
                        lambda token, chat, msg: calls.append((token, chat, msg)) or True)
    monkeypatch.setattr(scanner, "send_discord",
                        lambda webhook, msg: calls.append((webhook, msg)) or True)

    base_config = {
        "tinyfish_api_key": "sk-x",
        "candidate": {"name": "Tarun", "resume_path": str(resume), "min_score": 40, "top_n": 5},
    }
    companies = [{"name": "Acme", "careers_url": "https://x.co", "search_domain": "x.co",
                  "location": "Berlin", "region": "EU"}]
    return tmp_path, base_config, companies, calls


def _read_csv(tmp_path):
    files = list((tmp_path / "output").glob("*.csv"))
    assert files, "expected a CSV file in output/"
    with files[0].open() as fh:
        return list(csv.DictReader(fh))


def test_no_telegram_saves_csv_and_does_not_notify(scan_env):
    tmp_path, config, companies, calls = scan_env  # no 'telegram' key

    scanner.run_scan(config, companies)

    rows = _read_csv(tmp_path)
    assert len(rows) == 1
    assert rows[0]["Company"] == "Acme"
    assert calls == []  # Telegram never invoked, no error raised


def test_telegram_configured_saves_csv_and_notifies(scan_env):
    tmp_path, config, companies, calls = scan_env
    config = {**config, "telegram": {"token": "bot-token", "chat_id": "123"}}

    scanner.run_scan(config, companies)

    rows = _read_csv(tmp_path)
    assert len(rows) == 1                  # CSV still written
    assert len(calls) == 1                 # AND Telegram sent
    assert calls[0][0] == "bot-token"


def test_discord_configured_saves_csv_and_notifies(scan_env):
    tmp_path, config, companies, calls = scan_env
    config = {**config, "discord": {"webhook_url": "https://discord.com/api/webhooks/x/y"}}

    scanner.run_scan(config, companies)

    rows = _read_csv(tmp_path)
    assert len(rows) == 1
    assert len(calls) == 1
    assert calls[0][0] == "https://discord.com/api/webhooks/x/y"


def test_discord_notifies_after_each_company_scores(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resume = tmp_path / "resume.md"
    resume.write_text("Senior backend engineer.")
    events = []

    monkeypatch.setattr(scanner, "TinyFish", lambda **_: object())

    def discover(tf, company, seen):
        events.append(f"discover:{company['name']}")
        return [
            {"url": f"https://x.co/{company['name']}", "title": "Engineer",
             "company": company["name"], "location": "Remote", "region": "Remote"},
        ]

    def score(jobs, resume_text, config):
        company = jobs[0]["company"]
        events.append(f"score:{company}")
        return [{**jobs[0], "score": 90, "extracted_title": "Engineer", "reason": "fit"}]

    monkeypatch.setattr(scanner, "discover_job_urls", discover)
    monkeypatch.setattr(scanner, "fetch_job_details", lambda tf, jobs: jobs)
    monkeypatch.setattr(scanner, "score_jobs", score)
    monkeypatch.setattr(scanner, "send_discord",
                        lambda webhook, msg: events.append(f"discord:{msg}") or True)

    config = {
        "tinyfish_api_key": "sk-x",
        "scan_seed": 1,
        "candidate": {"name": "Ada", "resume_path": str(resume), "min_score": 60, "top_n": 5},
        "discord": {"webhook_url": "https://discord.com/api/webhooks/x/y"},
    }
    companies = [
        {"name": "Acme", "careers_url": "https://a.co", "search_domain": "a.co",
         "location": "Remote", "region": "Remote"},
        {"name": "Beta", "careers_url": "https://b.co", "search_domain": "b.co",
         "location": "Remote", "region": "Remote"},
    ]

    scanner.run_scan(config, companies)

    assert events.index("score:Beta") < next(i for i, e in enumerate(events) if e.startswith("discord:"))
    assert next(i for i, e in enumerate(events) if e.startswith("discord:")) < events.index("discover:Acme")
