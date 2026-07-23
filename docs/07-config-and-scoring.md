# 07 — Config & scoring

Two files hold your setup. Both are gitignored; copy them from the committed examples.

| File | Holds | Copy from |
|---|---|---|
| `config.json` | candidate profile, LLM provider, scoring thresholds, Telegram, Discord, Apify source settings | `config.example.json` |
| `.env` | API keys | `.env.example` |

`autopilot init` writes both for you. `.env` values override `config.json`, except that
a `your_..._here` placeholder never clobbers a real `config.json` value.

## Candidate profile

The scoring quality depends on this section — the LLM reads it plus your full resume.

```jsonc
{
  "tinyfish_api_key": "sk-tinyfish-...",
  "apify_api_token": "apify_api_...",
  "openrouter_api_key": "sk-or-v1-...",
  "llm_provider": "openrouter",
  "candidate": {
    "name": "Your Name",                        // appears in drafted cover letters
    "resume_path": "resume/YOUR_RESUME.md",     // your resume (Markdown)
    "profile": "Full-stack / backend engineer with strong API, platform, and product delivery experience.",
    "seeking": "Backend, full-stack, platform, and API-heavy roles",   // positive signal — scores higher
    "not_suitable": "Junior roles, senior/staff/principal/lead roles, ML/AI/data science roles, Java/Kotlin roles, Pakistan/South Asia roles", // negative filter — scores lower
    "excluded_titles": ["senior", "staff", "principal", "lead", "ml", "machine learning", "ai engineer", "data scientist", "java", "kotlin"],
    "excluded_locations": ["Pakistan", "South Asia", "Afghanistan", "Bangladesh", "Bhutan", "India", "Maldives", "Nepal", "Sri Lanka"],
    // ↑ hard filters — these titles and locations are removed before scoring or notification
    "min_score": 65,   // jobs below this are not saved or drafted
    "top_n": 5         // how many top matches go in the Telegram / Discord notification
  }
}
```

## Your resume

Replace `resume/YOUR_RESUME.md` with your real work history (plain Markdown — headings +
bullets). The LLM reads the **full text** when scoring each job, so specific detail
(exact tools, project scale, years per role) directly improves accuracy. A thin resume
yields low-confidence scores.

## Scoring model

Each job gets a 0–100 score with a one-line rationale. The bands (from the scoring
prompt):

| Score | Meaning |
|---|---|
| 80–100 | near-perfect fit |
| 60–79 | good fit |
| 40–59 | partial fit |
| < 40 | poor fit |

- **`min_score`** — the save/draft threshold. 60–70 is a good starting range. Jobs below
  it are discarded from results.
- **`top_n`** — how many of the passing matches are pushed to Telegram / Discord (all passing jobs
  still land in the CSV and `last_scan.json`).

Tune `min_score` up if you get too many marginal matches, down if you get too few.

## Apify LinkedIn source

If enabled in `config.json`, the Apify `linkedin-jobs-scraper` actor runs on its own
10-hour schedule and feeds into the same scoring and notification pipeline.

```jsonc
{
  "apify_linkedin": {
    "enabled": true,
    "actor_id": "valig/linkedin-jobs-scraper",
    "title": "backend engineer OR full stack engineer OR nodejs engineer OR php developer",
    "location": "European Union",
    "limit": 100,
    "datePosted": "r54000",
    "skipJobId": []
  }
}
```

- `seen_apify_job_ids` is stored in `state/seen_jobs.json` so repeat LinkedIn jobs are
  skipped on the next Apify run.
- `skipJobId` in config is merged with the stored IDs before the actor is called.
- Apify results are scored, saved, exported, and notified the same way as careers-page
  results.

## Provider selection

Set `llm_provider` to `openrouter` (default), `claude_cli`, or `anthropic` — see
[02 — LLM providers](02-providers.md) for each backend's keys and models. Override at
runtime without editing config: `LLM_PROVIDER=claude_cli autopilot scan`.

## Next

- [08 — Troubleshooting](08-troubleshooting.md)
- [09 — Testing checklist](09-testing-checklist.md)
