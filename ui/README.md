# Autopilot control room

This React dashboard is a read-only view of the job agent's local runtime state.

```bash
cd ui
npm install
npm run build
cd ..
./venv/bin/autopilot ui
```

Open http://127.0.0.1:4173. The server reads `state/last_scan.json`,
`state/job_history.json`, `state/seen_jobs.json`, and the recent portion of
`scan.log`. It refreshes automatically every 15 seconds. Use `--host` and
`--port` with `autopilot ui` when exposing it through a trusted reverse proxy.

For a persistent local service, install `deploy/systemd/autopilot-dashboard.service`
and enable it alongside the scanner service.
