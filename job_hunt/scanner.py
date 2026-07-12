import csv
import json
import random
import re
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from tinyfish import RateLimitError, TinyFish

from job_hunt.llm_utils import chat_with_llm
from job_hunt.log import get_logger
from job_hunt.notifier import send_discord, send_telegram

logger = get_logger()

STATE_FILE = Path("state/seen_jobs.json")
LAST_SCAN_FILE = Path("state/last_scan.json")
JOB_HISTORY_FILE = Path("state/job_history.json")

JOB_URL_RE = re.compile(
    r"/(job|jobs|opening|openings|position|positions|vacancy|vacancies|role|roles|apply)"
    r"/[a-zA-Z0-9_%@.-]{4,}",
    re.IGNORECASE,
)
ATS_JOB_RE = re.compile(
    r"(greenhouse\.io/.+/jobs/\d+"
    r"|lever\.co/[^/]+/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"
    r"|myworkdayjobs\.com/[^?#]+"
    r"|smartrecruiters\.com/[^/]+/[A-Z0-9]+"
    r"|ashbyhq\.com/[^/]+/[a-f0-9-]{32,})",
    re.IGNORECASE,
)
ATS_LISTING_RE = re.compile(
    r"^https?://(jobs\.lever\.co|boards\.greenhouse\.io|apply\.workable\.com"
    r"|jobs\.smartrecruiters\.com)/[^/?#]+/?(\?.*)?$",
    re.IGNORECASE,
)

SEARCH_QUERY = (
    'site:{domain} (senior OR staff OR principal OR lead) '
    '("data scientist" OR "ML engineer" OR "machine learning engineer" '
    'OR "AI engineer" OR MLOps OR "deep learning")'
)

SCORE_PROMPT = """You are evaluating job postings for a candidate. Output ONLY a JSON array, no other text.

CANDIDATE:
{candidate_profile}

RESUME SUMMARY:
{resume_summary}

JOBS TO SCORE:
{jobs_text}

For each job output:
{{
  "job_number": 1,
  "score": 0-100,
  "title": "extracted job title",
  "stack": "key tech from JD (comma-separated, max 6 items)",
  "location_remote": "location + remote policy",
  "reason": "one sentence why this fits or doesn't fit the candidate",
  "worth_applying": true/false
}}

Scoring: 80-100 near-perfect; 60-79 good fit; 40-59 partial; <40 poor.
If included titles are provided, only jobs whose title clearly matches one of them should be worth applying.
Otherwise set score low and worth_applying=false even if the description has some overlap.
Set worth_applying=true only if score >= {min_score}.
Include ALL jobs. Output ONLY the JSON array."""

EXPORT_FIELDS = [
    "Company", "Role", "Location", "Application URL",
    "Score (%)", "Stack", "Region", "Reason", "Worth Applying", "Scan Date",
]


def _build_candidate_profile(config: dict) -> str:
    cand = config.get("candidate", {})
    name = cand.get("name", "the candidate")
    profile = cand.get("profile", "")
    seeking = cand.get("seeking", "")
    not_suitable = cand.get("not_suitable", "")
    included_titles = cand.get("included_titles", [])

    lines = [f"- {name}"]
    if profile:
        lines.append(f"- {profile}")
    if seeking:
        lines.append(f"- Seeking: {seeking}")
    if not_suitable:
        lines.append(f"- NOT suitable: {not_suitable}")
    if included_titles:
        lines.append("- Included titles: " + ", ".join(included_titles))
    return "\n".join(lines)


def is_job_url(url: str) -> bool:
    return bool(JOB_URL_RE.search(url)) or bool(ATS_JOB_RE.search(url))


def is_ats_listing(url: str) -> bool:
    return bool(ATS_LISTING_RE.match(url))


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen_urls": [], "seen_apify_job_ids": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


_FETCH_URL_DELAY = 2.5


def _is_configured_secret(value: str | None) -> bool:
    if not value:
        return False
    return not (value.startswith("YOUR_") or value.startswith("your_") or value.endswith("_here"))


def _apify_run_input(config: dict, seen_job_ids: set[str] | None = None) -> dict:
    apify_cfg = config.get("apify_linkedin", {})
    run_input = {
        "title": apify_cfg.get(
            "title",
            "backend engineer OR full stack engineer OR nodejs engineer OR php developer",
        ),
        "location": apify_cfg.get("location", "European Union"),
        "limit": int(apify_cfg.get("limit", 100)),
        "skipEasyApply": bool(apify_cfg.get("skipEasyApply", True)),
        "experienceLevel": apify_cfg.get("experienceLevel", ["3", "4", "5"]),
        "contractType": apify_cfg.get("contractType", ["F", "C"]),
        "remote": apify_cfg.get("remote", ["2", "3"]),
    }
    for key in ("datePosted", "companyName", "companyId", "urlPath", "urlParam", "keywords", "excludeKeywords"):
        if key in apify_cfg:
            run_input[key] = apify_cfg[key]
    if "datePosted" not in run_input:
        run_input["datePosted"] = "r86400"
    skip_job_ids = set(str(job_id) for job_id in apify_cfg.get("skipJobId", []) if job_id)
    if seen_job_ids:
        skip_job_ids.update(str(job_id) for job_id in seen_job_ids if job_id)
    if skip_job_ids:
        run_input["skipJobId"] = sorted(skip_job_ids)
    return run_input


def _first_present(item: dict, keys: list[str], default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value:
            return str(value)
    return default


def _value_from_mapping_or_object(source, *names):
    for name in names:
        if isinstance(source, dict) and source.get(name):
            return source[name]
        value = getattr(source, name, None)
        if value:
            return value
    return None


def _telegram_configured(config: dict) -> bool:
    tg = config.get("telegram", {})
    return _is_configured_secret(tg.get("token")) and _is_configured_secret(tg.get("chat_id"))


def _term_in_text(term: str, text: str) -> bool:
    term = term.strip()
    if not term:
        return False
    if re.fullmatch(r"[A-Za-z0-9+#]+", term):
        pattern = rf"(?<![A-Za-z0-9+#]){re.escape(term)}(?![A-Za-z0-9+#])"
        return bool(re.search(pattern, text, re.IGNORECASE))
    return term.lower() in text.lower()


def _matches_apify_keyword_filters(job: dict, apify_cfg: dict) -> bool:
    text = "\n".join(
        str(job.get(key, ""))
        for key in ("title", "company", "location", "snippet", "content", "stack")
    )
    exclude_keywords = [str(k) for k in apify_cfg.get("excludeKeywords", []) if k]
    if any(_term_in_text(term, text) for term in exclude_keywords):
        return False

    keywords = [str(k) for k in apify_cfg.get("keywords", []) if k]
    if keywords and not any(_term_in_text(term, text) for term in keywords):
        return False
    return True


def _parse_application_count(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"(\d+)", str(value))
    return int(match.group(1)) if match else None


def _parse_posted_date(item: dict) -> datetime | None:
    raw = item.get("postedDate") or item.get("posted_date")
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    posted_time_ago = str(item.get("postedTimeAgo") or item.get("posted_time_ago") or "").strip().lower()
    if not posted_time_ago:
        return None
    match = re.search(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s+ago", posted_time_ago)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    delta_kwargs = {
        "minute": {"minutes": amount},
        "hour": {"hours": amount},
        "day": {"days": amount},
        "week": {"weeks": amount},
        "month": {"days": amount * 30},
        "year": {"days": amount * 365},
    }[unit]
    return datetime.now(UTC) - timedelta(**delta_kwargs)


def _matches_apify_freshness_and_applicant_limits(item: dict, apify_cfg: dict) -> bool:
    max_applicants = int(apify_cfg.get("maxApplicants", 20))
    applicant_count = _parse_application_count(item.get("applicationsCount"))
    if applicant_count is not None and applicant_count >= max_applicants:
        return False

    max_age_hours = int(apify_cfg.get("maxAgeHours", 24))
    posted_dt = _parse_posted_date(item)
    if posted_dt is not None:
        age_hours = (datetime.now(UTC) - posted_dt).total_seconds() / 3600
        if age_hours > max_age_hours:
            return False

    return True


def _normalize_apify_job(item: dict) -> dict | None:
    url = _first_present(item, ["url", "jobUrl", "job_url", "link", "applyUrl", "apply_url"])
    title = _first_present(item, ["title", "jobTitle", "job_title", "position"])
    company = _first_present(item, ["companyName", "company", "company_name"], "LinkedIn")
    location = _first_present(item, ["location", "jobLocation", "job_location"], "LinkedIn")
    description = _first_present(item, ["description", "jobDescription", "job_description", "text"])
    apply_url = _first_present(item, ["applyUrl", "apply_url"])

    if not url or not title:
        return None

    metadata = [
        f"Experience level: {item.get('experienceLevel')}" if item.get("experienceLevel") else "",
        f"Contract type: {item.get('contractType')}" if item.get("contractType") else "",
        f"Work type: {item.get('workType')}" if item.get("workType") else "",
        f"Sector: {item.get('sector')}" if item.get("sector") else "",
        f"Posted: {item.get('postedDate') or item.get('postedTimeAgo')}" if item.get("postedDate") or item.get("postedTimeAgo") else "",
        f"Applications: {item.get('applicationsCount')}" if item.get("applicationsCount") else "",
        f"Apply type: {item.get('applyType')}" if item.get("applyType") else "",
    ]
    content = "\n".join([line for line in metadata if line] + ([description] if description else []))

    return {
        "url": url,
        "title": title,
        "snippet": description[:500],
        "content": content[:3000],
        "company": company,
        "company_url": _first_present(item, ["companyUrl", "company_url"]),
        "location": location,
        "linkedin_id": _first_present(item, ["id"]),
        "posted_date": _first_present(item, ["postedDate", "posted_date"]),
        "apply_url": apply_url,
        "apply_type": _first_present(item, ["applyType", "apply_type"]),
        "contract_type": _first_present(item, ["contractType", "contract_type"]),
        "experience_level": _first_present(item, ["experienceLevel", "experience_level"]),
        "region": "LinkedIn",
        "source": "apify_linkedin",
    }


def fetch_apify_linkedin_jobs(config: dict, seen_urls: set, seen_job_ids: set | None = None) -> list[dict]:
    apify_cfg = config.get("apify_linkedin", {})
    if not apify_cfg.get("enabled", False):
        return []

    token = config.get("apify_api_token")
    if not _is_configured_secret(token):
        logger.warning("Apify LinkedIn source enabled but APIFY_API_TOKEN is not configured")
        return []

    try:
        from apify_client import ApifyClient
    except ImportError:
        logger.error("Apify LinkedIn source requires apify-client. Install dependencies from requirements.txt.")
        return []

    actor_id = apify_cfg.get("actor_id", "valig/linkedin-jobs-scraper")
    run_input = _apify_run_input(config, seen_job_ids)
    logger.info(
        "Apify LinkedIn: running %s for %r in %r (limit=%s, skipJobId=%s)",
        actor_id,
        run_input["title"],
        run_input["location"],
        run_input["limit"],
        len(run_input.get("skipJobId", [])),
    )

    try:
        client = ApifyClient(token)
        run = client.actor(actor_id).call(run_input=run_input)
        dataset_id = _value_from_mapping_or_object(run, "defaultDatasetId", "default_dataset_id")
        if not dataset_id:
            logger.warning("Apify LinkedIn run finished without a dataset id")
            return []
        dataset_items = client.dataset(dataset_id).list_items()
        items = _value_from_mapping_or_object(dataset_items, "items") or []
    except Exception as e:
        logger.error(f"Apify LinkedIn fetch failed: {e}")
        return []

    jobs: list[dict] = []
    seen_job_ids = seen_job_ids or set()
    for item in items:
        job = _normalize_apify_job(item)
        if (
            job
            and job["url"] not in seen_urls
            and job.get("linkedin_id") not in seen_job_ids
            and _matches_apify_keyword_filters(job, apify_cfg)
            and _matches_apify_freshness_and_applicant_limits(item, apify_cfg)
        ):
            jobs.append(job)
    logger.info("Apify LinkedIn: %d new job(s) from %d dataset item(s)", len(jobs), len(items))
    return jobs


def _score_and_publish_jobs(
    jobs: list[dict],
    resume: str,
    config: dict,
    *,
    source_label: str,
    state: dict | None = None,
    seen_urls: set[str] | None = None,
    seen_apify_job_ids: set[str] | None = None,
    all_scored_jobs: list[dict] | None = None,
    errors: list[str] | None = None,
    min_score: int = 55,
    top_n: int = 5,
    discord_configured: bool = False,
    discord_webhook: str | None = None,
) -> list[dict]:
    if not jobs:
        return []

    if seen_urls is not None:
        seen_urls.update(j["url"] for j in jobs if j.get("url"))
    if seen_apify_job_ids is not None:
        seen_apify_job_ids.update(j["linkedin_id"] for j in jobs if j.get("linkedin_id"))
    if state is not None and (seen_urls is not None or seen_apify_job_ids is not None):
        if seen_urls is not None:
            state["seen_urls"] = list(seen_urls)
        if seen_apify_job_ids is not None:
            state["seen_apify_job_ids"] = list(seen_apify_job_ids)
        save_state(state)

    logger.info("%s: scoring %d job(s)...", source_label, len(jobs))
    try:
        scored: list[dict] = []
        for i in range(0, len(jobs), 10):
            batch = jobs[i: i + 10]
            logger.debug("%s: scoring batch %d (%d jobs)...", source_label, i // 10 + 1, len(batch))
            scored.extend(score_jobs(batch, resume, config))
    except Exception as score_err:
        logger.error("%s scoring failed: %s", source_label, score_err)
        if errors is not None:
            errors.append(f"⚠️ Scoring failed for {source_label}: {score_err}")
        scored = jobs

    if scored:
        if all_scored_jobs is not None:
            all_scored_jobs.extend(scored)
        titles = [j.get("extracted_title") or j.get("title", "?") for j in scored[:3]]
        logger.info(
            "%s: %d job(s) saved: %s%s",
            source_label,
            len(scored),
            ", ".join(titles),
            " ..." if len(scored) > 3 else "",
        )
        discord_jobs = sorted(
            [j for j in scored if j.get("score", 0) >= min_score],
            key=lambda x: x.get("score", 0),
            reverse=True,
        )[:top_n]
        if discord_configured and discord_jobs and discord_webhook:
            date_str = datetime.now().strftime("%d %b %Y")
            sent = send_discord(discord_webhook, format_discord_message(discord_jobs, date_str))
            if sent:
                logger.info("%s: Discord notification sent for scored jobs.", source_label)
            else:
                logger.warning("%s: Discord send failed for scored jobs.", source_label)
    return scored


def run_apify_scan(config: dict) -> None:
    scan_start = time.time()
    logger.info("=== Apify LinkedIn scan started ===")
    logger.info("Candidate: %s", config.get("candidate", {}).get("name", "unknown"))
    logger.info("Min score: %s | Top N: %s", config.get("candidate", {}).get("min_score", 55), config.get("candidate", {}).get("top_n", 5))

    min_score = config.get("candidate", {}).get("min_score", 55)
    top_n = config.get("candidate", {}).get("top_n", 5)
    discord = config.get("discord", {})
    discord_webhook = discord.get("webhook_url")
    discord_configured = bool(discord_webhook)

    resume_path = Path(config.get("candidate", {}).get("resume_path", "resume/YOUR_RESUME.md"))
    resume = resume_path.read_text()
    logger.debug(f"Resume loaded: {resume_path} ({len(resume)} chars)")

    state = load_state()
    seen_urls: set = set(state.get("seen_urls", []))
    seen_apify_job_ids: set = set(state.get("seen_apify_job_ids", []))
    logger.info(
        "State loaded — %d previously seen URLs, %d Apify LinkedIn job IDs",
        len(seen_urls),
        len(seen_apify_job_ids),
    )

    all_scored_jobs: list[dict] = []
    errors: list[str] = []

    apify_jobs = fetch_apify_linkedin_jobs(config, seen_urls, seen_apify_job_ids)
    _score_and_publish_jobs(
        apify_jobs,
        resume,
        config,
        source_label="Apify LinkedIn",
        state=state,
        seen_urls=seen_urls,
        seen_apify_job_ids=seen_apify_job_ids,
        all_scored_jobs=all_scored_jobs,
        errors=errors,
        min_score=min_score,
        top_n=top_n,
        discord_configured=discord_configured,
        discord_webhook=discord_webhook,
    )

    state["seen_urls"] = list(seen_urls)
    state["seen_apify_job_ids"] = list(seen_apify_job_ids)
    state["last_scan"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    logger.debug("State saved")

    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for job in all_scored_jobs:
        job["scan_date"] = scan_date

    LAST_SCAN_FILE.parent.mkdir(exist_ok=True)
    LAST_SCAN_FILE.write_text(json.dumps(all_scored_jobs, indent=2))
    logger.debug(f"Last scan saved: {len(all_scored_jobs)} total jobs → {LAST_SCAN_FILE}")

    history: list[dict] = []
    if JOB_HISTORY_FILE.exists():
        try:
            history = json.loads(JOB_HISTORY_FILE.read_text())
        except Exception:
            history = []
    existing_urls = {j["url"] for j in history}
    new_entries = [j for j in all_scored_jobs if j["url"] not in existing_urls]
    history.extend(new_entries)
    JOB_HISTORY_FILE.write_text(json.dumps(history, indent=2))
    logger.debug(f"Job history updated: +{len(new_entries)} new entries ({len(history)} total)")

    elapsed = time.time() - scan_start
    top_jobs = sorted([j for j in all_scored_jobs if j.get("score", 0) >= min_score], key=lambda x: x.get("score", 0), reverse=True)[:top_n]
    logger.info(
        f"=== Apify LinkedIn scan complete — {len(all_scored_jobs)} jobs found, {len(top_jobs)} top matches "
        f"({elapsed / 60:.1f} min) ==="
    )
    if errors:
        logger.info("Apify LinkedIn scan recorded %d error(s).", len(errors))

    csv_path = _export_to_csv(all_scored_jobs, "apify scan results") if all_scored_jobs else None
    date_str = datetime.now().strftime("%d %b %Y")
    tg = config.get("telegram", {})
    telegram_configured = _telegram_configured(config)

    if errors and telegram_configured:
        error_msg = f"<b>Apify Job Hunt Errors — {date_str}</b>\n" + "\n".join(errors)
        send_telegram(tg["token"], tg["chat_id"], error_msg)

    if not top_jobs:
        logger.info("No matching Apify jobs found today.")
        if telegram_configured:
            msg = f"<b>Apify Job Hunt — {date_str}</b>\nNo new matches today."
            send_telegram(tg["token"], tg["chat_id"], msg)
        return
    logger.info("Apify CSV saved: %s", csv_path)

    msg = format_telegram_message(top_jobs, date_str)
    logger.info("\n" + msg)
    if telegram_configured:
        sent = send_telegram(tg["token"], tg["chat_id"], msg)
        if sent:
            logger.info(f"Apify Telegram notification sent. Results also saved to CSV: {csv_path}")
        else:
            logger.warning(f"Apify Telegram send failed — results saved to CSV: {csv_path}")
    else:
        logger.info(f"Apify Telegram not configured — results saved to CSV: {csv_path}")


def _fetch_with_ratelimit(tf: TinyFish, urls: list[str], **kwargs):
    for attempt in range(2):
        try:
            resp = tf.fetch.get_contents(urls, **kwargs)
            time.sleep(len(urls) * _FETCH_URL_DELAY)
            return resp
        except RateLimitError:
            logger.warning("Fetch rate-limited — waiting 65s before retry...")
            time.sleep(65)
        except Exception as e:
            logger.error(f"Fetch error for {urls[:1]}: {e}")
            time.sleep(len(urls) * _FETCH_URL_DELAY)
            return None
    return None


def _fetch_links(tf: TinyFish, urls: list[str]) -> dict[str, list[str]]:
    result = {}
    for i in range(0, len(urls), 10):
        batch = urls[i: i + 10]
        resp = _fetch_with_ratelimit(tf, batch, format="markdown", links=True)
        if resp:
            for r in resp.results:
                result[r.url] = r.links
    return result


def discover_job_urls(tf: TinyFish, company: dict, seen_urls: set) -> list[dict]:
    found_urls: set[str] = set()

    logger.debug(f"  [{company['name']}] Fetching careers page: {company['careers_url']}")
    resp = _fetch_with_ratelimit(tf, [company["careers_url"]], format="markdown", links=True)
    if resp and resp.results:
        links = resp.results[0].links
        direct = [link for link in links if is_job_url(link) and link not in seen_urls]
        ats_pages = list({link for link in links if is_ats_listing(link)})
        found_urls.update(direct)
        logger.debug(f"  [{company['name']}] Careers page: {len(direct)} direct job links, {len(ats_pages)} ATS listing pages")

        if ats_pages:
            logger.debug(f"  [{company['name']}] Expanding {len(ats_pages)} ATS listing page(s)...")
            ats_link_map = _fetch_links(tf, ats_pages[:5])
            ats_jobs = 0
            for page_links in ats_link_map.values():
                for link in page_links:
                    if is_job_url(link) and link not in seen_urls:
                        found_urls.add(link)
                        ats_jobs += 1
            logger.debug(f"  [{company['name']}] ATS expansion: {ats_jobs} additional job links")

    query = SEARCH_QUERY.format(domain=company["search_domain"])
    logger.debug(f"  [{company['name']}] Search query: {query}")
    for attempt in range(2):
        try:
            resp = tf.search.query(query, language="en")
            search_new = 0
            for r in resp.results:
                if is_job_url(r.url) and r.url not in seen_urls:
                    found_urls.add(r.url)
                    search_new += 1
            logger.debug(f"  [{company['name']}] Search: {len(resp.results)} results, {search_new} new job URLs")
            time.sleep(13)
            break
        except RateLimitError:
            logger.warning(f"  [{company['name']}] Search rate-limited — waiting 60s...")
            time.sleep(62)
        except Exception as e:
            logger.error(f"  [{company['name']}] Search error: {e}")
            time.sleep(13)
            break

    new = [
        {
            "url": u,
            "title": u.split("/")[-1].replace("-", " ").title(),
            "snippet": "",
            "company": company["name"],
            "location": company["location"],
            "region": company["region"],
        }
        for u in found_urls
    ]
    return new


def fetch_job_details(tf: TinyFish, jobs: list[dict]) -> list[dict]:
    enriched = []
    for i in range(0, len(jobs), 10):
        batch = jobs[i: i + 10]
        urls = [j["url"] for j in batch]
        logger.debug(f"  Fetching details for {len(batch)} job(s): {[j['title'][:40] for j in batch]}")
        resp = _fetch_with_ratelimit(tf, urls, format="markdown")
        if not resp:
            enriched.extend(batch)
            continue
        fetched = {r.url: r for r in resp.results}
        for job in batch:
            r = fetched.get(job["url"])
            if r and r.text:
                job["content"] = r.text[:3000]
                job["title"] = r.title or job["title"]
                logger.debug(f"    Fetched '{job['title']}' — {len(r.text)} chars")
            else:
                logger.debug(f"    No content for: {job['url']}")
            enriched.append(job)
    return enriched


def score_jobs(jobs: list[dict], resume: str, config: dict) -> list[dict]:
    if not jobs:
        return []

    jobs_text = "\n\n".join(
        f"JOB {i + 1}:\nCompany: {j['company']} | Location: {j['location']}\n"
        f"Title: {j['title']}\nURL: {j['url']}\n"
        f"Content:\n{j.get('content', j.get('snippet', ''))[:1500]}"
        for i, j in enumerate(jobs)
    )

    min_score = config.get("candidate", {}).get("min_score", 55)
    candidate_profile = _build_candidate_profile(config)

    prompt = SCORE_PROMPT.format(
        candidate_profile=candidate_profile,
        resume_summary=resume[:2500],
        jobs_text=jobs_text,
        min_score=min_score,
    )

    logger.debug(f"  Scoring {len(jobs)} job(s) via LLM (min_score={min_score})...")
    t0 = time.time()
    try:
        raw = chat_with_llm(
            config,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        elapsed = time.time() - t0
        start, end = raw.find("["), raw.rfind("]") + 1
        if start == -1:
            logger.error("  LLM returned no JSON array")
            return []
        scored = json.loads(raw[start:end])
        logger.debug(f"  LLM scoring complete in {elapsed:.1f}s — {len(scored)} results parsed")
    except Exception as e:
        logger.error(f"  Scoring error: {e}")
        return []

    results = []
    for item in scored:
        score = item.get("score", 0)
        title = item.get("title", "?")
        reason = item.get("reason", "")
        worth = item.get("worth_applying", False)
        logger.debug(f"    [{score:3d}] {title} — {reason[:80]}")
        if not worth:
            continue
        idx = item.get("job_number", 0) - 1
        if 0 <= idx < len(jobs):
            job = jobs[idx].copy()
            job.update(
                {
                    "score": score,
                    "extracted_title": title,
                    "stack": item.get("stack", ""),
                    "location_remote": item.get("location_remote", job["location"]),
                    "reason": reason,
                }
            )
            results.append(job)

    passing = len(results)
    logger.debug(f"  {passing}/{len(scored)} jobs passed min_score threshold")
    return sorted(results, key=lambda x: x["score"], reverse=True)


def format_telegram_message(top_jobs: list[dict], date_str: str) -> str:
    lines = [f"<b>Job Hunt — {date_str}</b>", f"<i>{len(top_jobs)} matches found</i>\n"]
    for i, job in enumerate(top_jobs, 1):
        lines.append(
            f"<b>#{i}</b> | {job['company']} | {job.get('extracted_title', job['title'])}\n"
            f"📍 {job.get('location_remote', job['location'])}\n"
            f"🔧 {job.get('stack', 'N/A')}\n"
            f"✅ {job.get('reason', '')}\n"
            f"<a href=\"{job['url']}\">Apply</a>\n"
        )
    lines.append('Reply "apply to #N" to draft application.')
    return "\n".join(lines)


def format_discord_message(jobs: list[dict], date_str: str) -> str:
    lines = [f"**Job Hunt - {date_str}**", f"*{len(jobs)} scored match(es)*", ""]
    for i, job in enumerate(jobs, 1):
        lines.extend(
            [
                f"**#{i}** | {job['company']} | {job.get('extracted_title', job['title'])}",
                f"Score: {job.get('score', '?')}/100",
                f"Location: {job.get('location_remote', job['location'])}",
                f"Stack: {job.get('stack', 'N/A')}",
                f"Reason: {job.get('reason', '')}",
                f"[Apply]({job['url']})",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _export_to_csv(jobs: list[dict], label: str) -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = Path("output") / f"jobs_{date_str}.csv"
    out_path.parent.mkdir(exist_ok=True)

    def _row(j: dict) -> dict:
        worth = j.get("worth_applying")
        return {
            "Company": j.get("company", ""),
            "Role": j.get("extracted_title") or j.get("title", ""),
            "Location": j.get("location_remote") or j.get("location", ""),
            "Application URL": j.get("url", ""),
            "Score (%)": j.get("score", ""),
            "Stack": j.get("stack", ""),
            "Region": j.get("region", ""),
            "Reason": j.get("reason", ""),
            "Worth Applying": "Yes" if worth else ("No" if worth is False else ""),
            "Scan Date": j.get("scan_date", ""),
        }

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        for j in jobs:
            writer.writerow(_row(j))

    logger.info(f"Results exported to CSV ({label}): {out_path}")
    return out_path


def run_scan(config: dict, companies: list[dict]) -> None:
    scan_start = time.time()
    total = len(companies)

    # Randomise scan order so no single company always goes first (and gets the
    # full wait if the run is interrupted early). A fixed `scan_seed` in config
    # makes the order reproducible for debugging; absent it, a fresh shuffle
    # every run. The seed is logged so a problematic run can be replayed.
    companies = list(companies)
    seed = config.get("scan_seed")
    rng = random.Random(seed) if seed is not None else random.Random()
    rng.shuffle(companies)
    logger.info(f"=== Scan started — {total} companies to check ===")
    if seed is not None:
        logger.info(f"Scan order seeded with scan_seed={seed} (reproducible)")
    else:
        logger.info("Scan order randomised (no scan_seed set — fresh shuffle)")
    logger.info(f"Candidate: {config.get('candidate', {}).get('name', 'unknown')}")
    logger.info(f"Min score: {config.get('candidate', {}).get('min_score', 55)} | Top N: {config.get('candidate', {}).get('top_n', 5)}")
    provider = (config.get("llm_provider") or "openrouter").lower()
    model_by_provider = {
        "openrouter": config.get("openrouter_model", "default"),
        "deepseek": config.get("deepseek_model", "default"),
        "huggingface": config.get("huggingface_model", "default"),
        "anthropic": config.get("anthropic_model", "default"),
        "claude_cli": config.get("claude_cli_model") or "claude default",
    }
    logger.info(f"LLM provider: {provider} | Model: {model_by_provider.get(provider, 'default')}")

    try:
        tf = TinyFish(api_key=config["tinyfish_api_key"])
        logger.debug("TinyFish client initialised")
    except Exception as e:
        logger.error(f"TinyFish init error: {e}")
        return

    resume_path = Path(config.get("candidate", {}).get("resume_path", "resume/YOUR_RESUME.md"))
    resume = resume_path.read_text()
    logger.debug(f"Resume loaded: {resume_path} ({len(resume)} chars)")

    min_score = config.get("candidate", {}).get("min_score", 55)
    top_n = config.get("candidate", {}).get("top_n", 5)
    discord = config.get("discord", {})
    discord_webhook = discord.get("webhook_url")
    discord_configured = bool(discord_webhook)

    state = load_state()
    seen_urls: set = set(state.get("seen_urls", []))
    seen_apify_job_ids: set = set(state.get("seen_apify_job_ids", []))
    logger.info(
        f"State loaded — {len(seen_urls)} previously seen URLs, "
        f"{len(seen_apify_job_ids)} Apify LinkedIn job IDs"
    )

    all_scored_jobs: list[dict] = []
    errors: list[str] = []
    companies_scanned = 0
    companies_with_jobs = 0

    for idx, company in enumerate(companies, 1):
        logger.info(f"[{idx}/{total}] Scanning {company['name']}...")
        try:
            new_jobs = discover_job_urls(tf, company, seen_urls)
            if not new_jobs:
                logger.info("  No new job URLs found")
                companies_scanned += 1
                continue

            logger.info(f"  {len(new_jobs)} new job URL(s) — fetching details...")
            new_jobs = fetch_job_details(tf, new_jobs)
            seen_urls.update(j["url"] for j in new_jobs)

            # Persist seen URLs after each company so an interrupted scan (Ctrl-C,
            # crash, network drop) doesn't re-process these URLs next time. The
            # final save at the end of run_scan also stamps last_scan time.
            state["seen_urls"] = list(seen_urls)
            save_state(state)

            logger.info(f"  Scoring {len(new_jobs)} job(s)...")
            scored: list[dict] = []
            try:
                for i in range(0, len(new_jobs), 10):
                    batch = new_jobs[i: i + 10]
                    logger.debug(f"  Scoring batch {i // 10 + 1} ({len(batch)} jobs)...")
                    batch_scored = score_jobs(batch, resume, config)
                    scored.extend(batch_scored)
            except Exception as score_err:
                logger.error(f"  Scoring failed: {score_err}")
                errors.append(f"⚠️ Scoring failed for {company['name']}: {score_err}")
                logger.warning(f"  Saving {len(new_jobs)} unscored job(s) as fallback")
                scored = new_jobs

            if scored:
                all_scored_jobs.extend(scored)
                companies_with_jobs += 1
                titles = [j.get("extracted_title") or j.get("title", "?") for j in scored[:3]]
                logger.info(f"  {len(scored)} job(s) saved: {', '.join(titles)}{' ...' if len(scored) > 3 else ''}")
                discord_jobs = sorted(
                    [j for j in scored if j.get("score", 0) >= min_score],
                    key=lambda x: x.get("score", 0),
                    reverse=True,
                )[:top_n]
                if discord_configured and discord_jobs:
                    date_str = datetime.now().strftime("%d %b %Y")
                    sent = send_discord(discord_webhook, format_discord_message(discord_jobs, date_str))
                    if sent:
                        logger.info("  Discord notification sent for scored jobs.")
                    else:
                        logger.warning("  Discord send failed for scored jobs.")

            companies_scanned += 1

        except Exception as company_err:
            msg = f"❌ {company['name']}: {company_err}"
            errors.append(msg)
            logger.error(f"  Company scan failed: {company_err}")
            continue

    state["seen_urls"] = list(seen_urls)
    state["seen_apify_job_ids"] = list(seen_apify_job_ids)
    state["last_scan"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    logger.debug("State saved")

    top_jobs = sorted(
        [j for j in all_scored_jobs if j.get("score", 0) >= min_score],
        key=lambda x: x.get("score", 0), reverse=True
    )[:top_n]

    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for job in all_scored_jobs:
        job["scan_date"] = scan_date

    LAST_SCAN_FILE.parent.mkdir(exist_ok=True)
    LAST_SCAN_FILE.write_text(json.dumps(all_scored_jobs, indent=2))
    logger.debug(f"Last scan saved: {len(all_scored_jobs)} total jobs → {LAST_SCAN_FILE}")

    history: list[dict] = []
    if JOB_HISTORY_FILE.exists():
        try:
            history = json.loads(JOB_HISTORY_FILE.read_text())
        except Exception:
            history = []
    existing_urls = {j["url"] for j in history}
    new_entries = [j for j in all_scored_jobs if j["url"] not in existing_urls]
    history.extend(new_entries)
    JOB_HISTORY_FILE.write_text(json.dumps(history, indent=2))
    logger.debug(f"Job history updated: +{len(new_entries)} new entries ({len(history)} total)")

    elapsed = time.time() - scan_start
    logger.info(
        f"=== Scan complete — {companies_scanned}/{total} companies, "
        f"{len(all_scored_jobs)} jobs found, {len(top_jobs)} top matches "
        f"({elapsed / 60:.1f} min) ==="
    )

    if top_jobs:
        logger.info("Top matches:")
        for j in top_jobs:
            logger.info(f"  [{j.get('score', '?'):3}] {j.get('extracted_title') or j.get('title')} @ {j['company']} — {j.get('reason', '')[:80]}")

    date_str = datetime.now().strftime("%d %b %Y")
    tg = config.get("telegram", {})
    telegram_configured = _telegram_configured(config)

    # Always persist results to CSV when there are scored jobs ? this is the
    # durable record regardless of whether Telegram or Discord is configured.
    csv_path = _export_to_csv(all_scored_jobs, "scan results") if all_scored_jobs else None

    if errors and telegram_configured:
        error_msg = f"<b>Job Hunt Errors ? {date_str}</b>\n" + "\n".join(errors)
        send_telegram(tg["token"], tg["chat_id"], error_msg)

    if not top_jobs:
        logger.info("No matching jobs found today.")
        if telegram_configured:
            msg = f"<b>Job Hunt ? {date_str}</b>\nNo new matches today."
            send_telegram(tg["token"], tg["chat_id"], msg)
        return

    msg = format_telegram_message(top_jobs, date_str)
    logger.info("\n" + msg)

    # Telegram is an optional notification on top of the CSV. When it's not
    # configured we simply skip it ? no error, the CSV already holds the results.
    if telegram_configured:
        sent = send_telegram(tg["token"], tg["chat_id"], msg)
        if sent:
            logger.info(f"Telegram notification sent. Results also saved to CSV: {csv_path}")
        else:
            logger.warning(f"Telegram send failed ? results saved to CSV: {csv_path}")
    else:
        logger.info(f"Telegram not configured ? results saved to CSV: {csv_path}")
        logger.info("Add telegram.token and telegram.chat_id to config.json to enable notifications.")
