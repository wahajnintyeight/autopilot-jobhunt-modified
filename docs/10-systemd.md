# 10 - systemd service

Use this on a Linux VPS when you want autopilot to run on its own.

## 1. Copy the repo

Clone the repo onto the server and create the venv:

```bash
git clone https://github.com/wahajnintyeight/autopilot-jobhunt-modified.git /opt/autopilot-jobhunt
cd /opt/autopilot-jobhunt
python3.11 -m venv .venv
.venv/bin/pip install -e .
```

## 2. Configure the service

Edit `config.json` and `.env` in that directory. Set:

- `tinyfish_api_key`
- `openrouter_api_key` or another LLM backend
- `service.timezone`
- `service.schedules`

Example schedules:

```json
"service": {
  "timezone": "Asia/Karachi",
  "schedules": [
    { "name": "morning_scan", "action": "scan", "cron": "30 2 * * *" },
    { "name": "evening_scan", "action": "scan", "cron": "30 14 * * *" }
  ]
}
```

## 3. Register with systemd

Copy the unit file:

```bash
sudo cp deploy/systemd/autopilot-jobhunt.service /etc/systemd/system/autopilot-jobhunt.service
sudo systemctl daemon-reload
sudo systemctl enable --now autopilot-jobhunt
```

If your repo lives somewhere else, edit `WorkingDirectory`, `ExecStart`, and
`AUTOPILOT_LOG_FILE` in the unit file first.

## 4. Watch logs

Two options:

```bash
journalctl -fu autopilot-jobhunt
tail -f /opt/autopilot-jobhunt/scan.log
```

## 5. Check status

```bash
systemctl status autopilot-jobhunt
systemctl restart autopilot-jobhunt
```

## Notes

- `autopilot scan` still works for manual runs.
- The service uses one Python process with multiple cron jobs. That is enough for a
  single VPS.
- If you want a different install path, keep the repo and venv paths consistent in the
  unit file.
