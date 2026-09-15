import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "../../tokens.css";
import "./styles.css";

const views = [
  { id: "overview", label: "Overview", key: "01" },
  { id: "new", label: "New jobs", key: "02" },
  { id: "history", label: "History", key: "03" },
  { id: "companies", label: "Companies", key: "04" },
];

function Icon({ name, size = 18 }) {
  const paths = {
    activity: <><path d="M3 12h4l2-7 4 14 2-7h6" /></>,
    archive: <><path d="M4 7h16v13H4z" /><path d="M3 4h18v3H3zM9 12h6" /></>,
    arrow: <><path d="M5 12h13M13 7l5 5-5 5" /></>,
    check: <><path d="m5 12 4 4L19 6" /></>,
    external: <><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 13v6H4V5h6" /></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    refresh: <><path d="M20 11a8 8 0 0 0-14.7-3L3 11" /><path d="M3 5v6h6M4 13a8 8 0 0 0 14.7 3L21 13" /><path d="M21 19v-6h-6" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6" /><path d="m16 16 5 5" /></>,
    server: <><rect x="4" y="4" width="16" height="6" rx="1" /><rect x="4" y="14" width="16" height="6" rx="1" /><path d="M8 7h.01M8 17h.01" /></>,
    x: <><path d="m6 6 12 12M18 6 6 18" /></>,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.replace("T", " ").slice(0, 16);
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function relativeTime(value) {
  if (!value) return "not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "recently";
  const minutes = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function scoreClass(score) {
  if (score >= 80) return "score score--high";
  if (score >= 60) return "score score--good";
  if (score !== null && score !== undefined) return "score score--low";
  return "score score--empty";
}

function sourceLabel(source) {
  return source === "linkedin" || source === "apify_linkedin" ? "LinkedIn" : "Careers";
}

function JobRow({ job, onOpen }) {
  const isLinkedIn = job.source === "linkedin" || job.source === "apify_linkedin";
  return (
    <button className="job-row" onClick={() => onOpen(job)} type="button">
      <span className="job-row__score"><span className={scoreClass(job.score)}>{job.score ?? "—"}</span></span>
      <span className="job-row__main">
        <span className="job-row__title">{job.title}</span>
        <span className="job-row__meta">{job.company} <span className="dot-separator">·</span> {job.location}</span>
      </span>
      <span className="job-row__source"><span className={`source-dot source-dot--${isLinkedIn ? "linkedin" : "careers"}`} />{sourceLabel(job.source)}</span>
      <Icon name="arrow" size={17} />
    </button>
  );
}

function Metric({ label, value, detail, accent = false }) {
  return <div className={`metric ${accent ? "metric--accent" : ""}`}><span className="metric__label">{label}</span><strong>{value}</strong><span className="metric__detail">{detail}</span></div>;
}

function prettyLabel(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function TagList({ items, tone = "default" }) {
  if (!items?.length) return <span className="tag-empty">Not configured</span>;
  return <div className={`tag-list tag-list--${tone}`}>{items.map((item) => <span className="tag" key={item}>{item}</span>)}</div>;
}

function ScanPanel({ scan, latest }) {
  const active = Boolean(scan?.active);
  const progress = scan?.progress;
  const percent = Math.min(100, Math.max(0, Number(progress?.percent) || 0));
  return (
    <article className="operator-card scan-card">
      <div className="operator-card__head"><div><span className="card-kicker">RUN MONITOR</span><h3>{active ? prettyLabel(scan.task) : "No scan in progress"}</h3></div><span className={`state-badge ${active ? "state-badge--live" : ""}`}><span className="pulse-dot" />{active ? "live" : "idle"}</span></div>
      <p className="operator-card__lede">{active ? `The worker is ${scan.phase || "working"}. This view refreshes every 3 seconds while it runs.` : "The worker is waiting for its next scheduled pass. The latest completed result stays visible here."}</p>
      {active && progress ? <div className="scan-progress"><div className="progress-meta"><span>{progress.company || "Current company"}</span><strong>{progress.current} / {progress.total}</strong></div><div className="progress-track" aria-label={`${percent}% of companies scanned`}><span style={{ "--progress": percent / 100 }} /></div><div className="progress-foot"><span>{percent}% complete</span><span>{scan.phase || "working"}</span></div></div> : <div className="scan-idle"><span className="scan-idle__icon"><Icon name="check" size={17} /></span><div><strong>{latest ? `${latest.jobs} jobs found in the last pass` : "Waiting for the first completed pass"}</strong><span>{latest ? `${latest.top_matches} top matches · completed ${relativeTime(latest.timestamp)}` : "No completed scan recorded yet"}</span></div></div>}
      <div className="operator-card__foot"><span>Last log {relativeTime(scan?.last_log_at)}</span><span>{active ? "Polling / 3 sec" : "Polling / 15 sec"}</span></div>
    </article>
  );
}

function ProfilePanel({ profile }) {
  return (
    <article className="operator-card profile-card">
      <div className="operator-card__head"><div><span className="card-kicker">YOUR BRIEF</span><h3>{profile?.name || "Candidate profile"}</h3></div><span className={`resume-badge ${profile?.resume_exists ? "resume-badge--ready" : ""}`}><span className="pulse-dot" />{profile?.resume_exists ? "resume loaded" : "resume missing"}</span></div>
      <p className="profile-summary">{profile?.profile || "Add a candidate profile to give the scorer more context."}</p>
      <div className="profile-facts"><div><span>Target roles</span><strong>{profile?.seeking || "Not set"}</strong></div><div><span>Minimum match</span><strong>{profile?.min_score ?? "—"} / 100</strong></div><div><span>Top matches sent</span><strong>{profile?.top_n ?? "—"}</strong></div></div>
      <div className="tag-group"><span>Include in role search</span><TagList items={profile?.included_titles} /></div>
      <div className="tag-group"><span>Exclude from role search</span><TagList items={[...(profile?.excluded_titles || []), ...(profile?.excluded_locations || [])]} tone="muted" /></div>
      {profile?.not_suitable && <div className="profile-boundary"><span>Scoring guardrails</span><p>{profile.not_suitable}</p></div>}
    </article>
  );
}

function SearchConfigPanel({ search }) {
  const linkedin = search?.linkedin || {};
  const careers = search?.careers || {};
  return (
    <article className="operator-card search-config-card">
      <div className="operator-card__head"><div><span className="card-kicker">SEARCH COVERAGE</span><h3>What the agent is watching</h3></div><span className="coverage-count">{careers.company_count || 0} career sites</span></div>
      <div className="search-config-grid">
        <div className="config-block"><div className="config-block__title"><span className="source-avatar source-avatar--linkedin">in</span><div><strong>LinkedIn</strong><span className={`config-status ${linkedin.enabled ? "config-status--on" : ""}`}>{linkedin.enabled ? "enabled" : "disabled"}</span></div></div><p className="config-query">{linkedin.query || "No LinkedIn query configured"}</p><div className="config-facts"><span>Location <strong>{linkedin.location || "—"}</strong></span><span>Posted within <strong>{linkedin.date_posted_label || "—"}</strong></span><span>Result cap <strong>{linkedin.limit ?? "—"}</strong></span><span>Level <strong>{linkedin.experience_levels?.join(" · ") || "—"}</strong></span><span>Work mode <strong>{linkedin.remote_modes?.join(" · ") || "—"}</strong></span><span>Type <strong>{linkedin.contract_types?.join(" · ") || "—"}</strong></span></div><span className="tag-label">Keywords</span><TagList items={linkedin.keywords} /><span className="tag-label tag-label--muted">Excluded</span><TagList items={linkedin.exclude_keywords} tone="muted" /></div>
        <div className="config-block"><div className="config-block__title"><span className="source-avatar source-avatar--careers">◎</span><div><strong>Company careers</strong><span className="config-status config-status--on">{careers.company_count || 0} sources</span></div></div><p className="config-query">Role titles are matched against each company’s careers page.</p><div className="config-facts"><span>Timezone <strong>{search?.timezone || "—"}</strong></span><span>Schedules <strong>{search?.schedules?.length || 0}</strong></span><span>Source <strong>Careers</strong></span></div><span className="tag-label">Role keywords</span><TagList items={careers.keywords} /><span className="tag-label tag-label--muted">Location exclusions</span><TagList items={careers.exclude_locations} tone="muted" /></div>
      </div>
      <div className="schedule-list">{(search?.schedules || []).map((schedule) => <div className="schedule-row" key={schedule.name}><span className="pulse-dot" /><strong>{prettyLabel(schedule.name)}</strong><span>{schedule.cadence || prettyLabel(schedule.action)}</span><code>{schedule.cron}</code></div>)}{!(search?.schedules || []).length && <span className="tag-empty">No schedules configured</span>}</div>
    </article>
  );
}

function WorkspaceHeader({ view, summary, analytics, latestRun }) {
  if (view === "new") {
    const latestDetail = latestRun
      ? `${latestRun.label} completed ${relativeTime(latestRun.timestamp)} · ${latestRun.jobs} jobs found`
      : "Waiting for a completed scan result";
    return <div className="workspace-header"><div><p className="eyebrow">INBOX / FRESH SIGNAL</p><h2>New jobs, ready for a decision.</h2><p>Roles from the latest completed pass are kept here until the next scan replaces the inbox.</p></div><div className="workspace-header__facts"><span><strong>{summary.new_jobs ?? 0}</strong>fresh roles</span><span>{latestDetail}</span></div></div>;
  }
  return <div className="workspace-header"><div><p className="eyebrow">ARCHIVE / SEARCH MEMORY</p><h2>History with the signal intact.</h2><p>Search every saved role, compare sources, and use the score trail to decide where your attention goes next.</p></div><div className="workspace-header__facts"><span><strong>{analytics?.total ?? summary.history_jobs ?? 0}</strong>saved roles</span><span><strong>{analytics?.high_score ?? 0}</strong> high-confidence matches</span></div></div>;
}

function HistoryInsights({ analytics }) {
  const total = analytics?.total || 0;
  const sources = analytics?.sources || {};
  return <div className="history-insights">
    <article className="insight-card insight-card--score"><span className="card-kicker">MATCH QUALITY</span><div className="insight-card__value">{analytics?.average_score ?? "—"}<small>/100 avg</small></div><div className="insight-card__footer"><span>{analytics?.target_score ?? 0} at 60+</span><span>{analytics?.scored ?? 0} scored</span></div></article>
    <article className="insight-card"><div className="insight-card__head"><span className="card-kicker">SOURCE MIX</span><span>{total.toLocaleString()} total</span></div><div className="source-meter" aria-label="History source mix"><span className="source-meter__linkedin" style={{ width: `${total ? ((sources.linkedin || 0) / total) * 100 : 0}%` }} /><span className="source-meter__careers" style={{ width: `${total ? ((sources.careers || 0) / total) * 100 : 0}%` }} /></div><div className="insight-card__legend"><span><i className="legend-dot legend-dot--linkedin" />LinkedIn <strong>{sources.linkedin || 0}</strong></span><span><i className="legend-dot legend-dot--careers" />Careers <strong>{sources.careers || 0}</strong></span></div></article>
    <article className="insight-card"><span className="card-kicker">SCORE BANDS</span><div className="score-bars">{(analytics?.score_buckets || []).map((bucket) => <div className="score-bar" key={bucket.label}><div><span>{bucket.label}</span><strong>{bucket.count}</strong></div><span className="score-bar__track"><i style={{ width: `${total ? (bucket.count / total) * 100 : 0}%` }} /></span></div>)}</div></article>
    <article className="insight-card insight-card--ranked"><span className="card-kicker">MOST REPRESENTED COMPANIES</span><div className="ranked-list">{(analytics?.top_companies || []).slice(0, 5).map((item, index) => <div className="ranked-row" key={item.label}><span>0{index + 1}</span><strong>{item.label}</strong><em>{item.count}</em></div>)}{!(analytics?.top_companies || []).length && <span className="tag-empty">No company history yet</span>}</div></article>
  </div>;
}

function RunTimeline({ runs }) {
  return <article className="run-timeline"><div className="insight-section-head"><div><span className="card-kicker">RUN HISTORY</span><h3>What the worker has completed</h3></div><span className="insight-section-head__meta">Last {Math.min(runs?.length || 0, 16)} runs</span></div><div className="run-list">{(runs || []).map((run, index) => <div className="run-row" key={`${run.timestamp}-${run.source}-${index}`}><span className={`run-marker run-marker--${run.source}`} /><div className="run-row__main"><strong>{run.label}</strong><span>{formatDate(run.timestamp)} · {relativeTime(run.timestamp)}</span></div><div className="run-row__result"><strong>{run.jobs} jobs</strong><span>{run.top_matches} top matches{run.companies !== null ? ` · ${run.companies}/${run.total_companies} sites` : ""}</span></div></div>)}{!(runs || []).length && <p className="muted-copy">No completed runs have been recorded yet.</p>}</div></article>;
}

function CompanyCard({ company }) {
  const initials = company.name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  return <article className="company-card"><div className="company-card__head"><span className="company-avatar">{initials}</span><div className="company-card__identity"><h3>{company.name}</h3><span>{company.search_domain || "Domain not set"}</span></div><span className="company-status"><i />{company.source_status}</span></div><div className="company-card__facts"><div><span>Coverage</span><strong>{company.location}</strong></div><div><span>Region</span><strong>{company.region}</strong></div></div><div className="company-card__foot"><span>{company.jobs_found} saved role{company.jobs_found === 1 ? "" : "s"}{company.last_job_at ? ` · last ${relativeTime(company.last_job_at)}` : " · no saved roles yet"}</span><a href={company.careers_url} target="_blank" rel="noreferrer" aria-label={`Open ${company.name} careers page`}><Icon name="external" size={15} />{company.careers_urls?.length > 1 ? `${company.careers_urls.length} sources` : "Open source"}</a></div></article>;
}

function CompaniesWorkspace({ companies, scan, onSaved }) {
  const [query, setQuery] = useState("");
  const [region, setRegion] = useState("all");
  const [form, setForm] = useState({ name: "", careers_url: "", search_domain: "", location: "", region: "EU" });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");
  const regions = useMemo(() => ["all", ...new Set(companies.map((company) => company.region).filter(Boolean))], [companies]);
  const filteredCompanies = useMemo(() => companies.filter((company) => {
    const haystack = `${company.name} ${company.search_domain} ${company.location} ${company.region}`.toLowerCase();
    return (!query.trim() || haystack.includes(query.trim().toLowerCase())) && (region === "all" || company.region === region);
  }), [companies, query, region]);

  function updateField(event) {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
    setFormError("");
    setFormSuccess("");
  }

  async function submitCompany(event) {
    event.preventDefault();
    setSaving(true);
    setFormError("");
    setFormSuccess("");
    try {
      const response = await fetch("/api/companies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Could not add company");
      setForm({ name: "", careers_url: "", search_domain: "", location: "", region: "EU" });
      setFormSuccess(`${payload.company.name} is ready for the next careers pass.`);
      onSaved();
    } catch (error) {
      setFormError(error.message || "Could not add company");
    } finally {
      setSaving(false);
    }
  }

  return <div className="companies-workspace"><div className="workspace-header"><div><p className="eyebrow">DIRECTORY / CAREERS SOURCES</p><h2>Control the companies in the hunt.</h2><p>Every source below is part of the careers scraper’s configured watchlist. Add a company once and the next scheduled pass will include it.</p></div><div className="workspace-header__facts"><span><strong>{companies.length}</strong>configured sources</span><span>{scan?.active ? `Current pass: ${prettyLabel(scan.task)}` : "Ready for the next pass"}</span></div></div><div className="company-layout"><form className="add-company-card" onSubmit={submitCompany}><div className="operator-card__head"><div><span className="card-kicker">ADD A SOURCE</span><h3>Bring another company into range.</h3></div><span className="source-avatar source-avatar--careers">+</span></div><p className="operator-card__lede">Use the company’s public careers page. The scraper will use the domain to discover matching roles.</p><div className="company-form-grid"><label><span>Company name</span><input name="name" value={form.name} onChange={updateField} placeholder="Example Labs" required /></label><label><span>Careers URL</span><input name="careers_url" type="url" value={form.careers_url} onChange={updateField} placeholder="https://example.com/careers" required /></label><label><span>Search domain <em>optional</em></span><input name="search_domain" value={form.search_domain} onChange={updateField} placeholder="example.com" /></label><label><span>Location <em>optional</em></span><input name="location" value={form.location} onChange={updateField} placeholder="Remote / Berlin" /></label><label><span>Region <em>optional</em></span><select name="region" value={form.region} onChange={updateField}><option>EU</option><option>US</option><option>NZ</option><option>Remote</option><option>Global</option></select></label></div>{formError && <p className="form-feedback form-feedback--error" role="alert">{formError}</p>}{formSuccess && <p className="form-feedback form-feedback--success" role="status">{formSuccess}</p>}<button className="action-button action-button--accent" disabled={saving} type="submit">{saving ? "Adding source…" : "Add to watchlist"}<Icon name="arrow" size={16} /></button></form><div className="company-directory"><div className="directory-toolbar"><div><span className="card-kicker">WATCHLIST</span><h3>{filteredCompanies.length} companies in view</h3></div><div className="directory-controls"><label className="search-field"><Icon name="search" size={16} /><span className="sr-only">Search companies</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search companies or domains" /></label><select value={region} onChange={(event) => setRegion(event.target.value)} aria-label="Filter companies by region">{regions.map((item) => <option value={item} key={item}>{item === "all" ? "All regions" : item}</option>)}</select></div></div><div className="company-list">{filteredCompanies.map((company) => <CompanyCard company={company} key={`${company.name}-${company.careers_url}`} />)}{!filteredCompanies.length && <EmptyState label="No companies match" detail="Try another name, domain, or region filter." action="Clear filters" onAction={() => { setQuery(""); setRegion("all"); }} />}</div></div></div></div>;
}

function App() {
  const [dashboard, setDashboard] = useState(null);
  const [view, setView] = useState("overview");
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("all");
  const [sortBy, setSortBy] = useState("score");
  const [visibleCount, setVisibleCount] = useState(18);
  const [menuOpen, setMenuOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [selectedJob, setSelectedJob] = useState(null);
  const dialogRef = useRef(null);
  const searchRef = useRef(null);

  async function loadDashboard(isRefresh = false) {
    if (isRefresh) setRefreshing(true);
    try {
      const response = await fetch("/api/dashboard", { cache: "no-store" });
      if (!response.ok) throw new Error(`Dashboard returned ${response.status}`);
      setDashboard(await response.json());
      setError("");
    } catch (fetchError) {
      setError(fetchError.message || "Could not reach the dashboard server");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    loadDashboard();
    const timer = window.setInterval(() => loadDashboard(), dashboard?.scan?.active ? 3000 : 15000);
    const keyboard = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setView("history");
        setMenuOpen(false);
        window.setTimeout(() => searchRef.current?.focus(), 0);
      }
      if (event.key.toLowerCase() === "r" && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) loadDashboard(true);
      if (event.key === "Escape") {
        dialogRef.current?.close();
        setMenuOpen(false);
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => { window.clearInterval(timer); window.removeEventListener("keydown", keyboard); };
  }, [dashboard?.scan?.active]);

  useEffect(() => {
    if (selectedJob && dialogRef.current && !dialogRef.current.open) dialogRef.current.showModal();
  }, [selectedJob]);

  useEffect(() => {
    setVisibleCount(18);
  }, [view, query, source, sortBy]);

  const summary = dashboard?.summary || {};
  const jobs = view === "new" ? (dashboard?.new_jobs || []) : (dashboard?.history || []);
  const filteredJobs = useMemo(() => jobs.filter((job) => {
    const haystack = `${job.title} ${job.company} ${job.location} ${job.stack} ${job.reason} ${job.content}`.toLowerCase();
    const matchesQuery = !query.trim() || haystack.includes(query.trim().toLowerCase());
    const isLinkedIn = job.source === "linkedin" || job.source === "apify_linkedin";
    return matchesQuery && (source === "all" || (source === "linkedin" ? isLinkedIn : !isLinkedIn));
  }), [jobs, query, source]);

  const sortedJobs = useMemo(() => [...filteredJobs].sort((left, right) => {
    if (sortBy === "company") return left.company.localeCompare(right.company);
    if (sortBy === "recent") return String(right.scan_date).localeCompare(String(left.scan_date));
    return (right.score ?? -1) - (left.score ?? -1);
  }), [filteredJobs, sortBy]);
  const visibleJobs = sortedJobs.slice(0, visibleCount);

  const latestApify = dashboard?.latest?.apify;
  const latestCareers = dashboard?.latest?.careers;
  const scan = dashboard?.scan || {};
  const profile = dashboard?.profile || {};
  const search = dashboard?.search || {};
  const analytics = dashboard?.analytics || {};
  const runs = dashboard?.runs || [];
  const latestRun = runs[0];
  const serviceActive = dashboard?.service?.state === "active";
  const statusLabel = serviceActive ? (scan.active ? "Processing a scan" : "Standing by") : "Unavailable";

  if (loading && !dashboard) return <div className="boot-screen"><span className="boot-mark">A</span><p>Loading your job workspace…</p></div>;

  return (
    <div className="app-shell">
      <header className="site-header">
        <div className="site-header__inner">
          <button className="brand-lockup" onClick={() => { setView("overview"); setMenuOpen(false); }} type="button" aria-label="Autopilot overview">
            <span className="brand-mark">A</span>
            <span className="brand-type">AUTOPILOT<br /><b>JOB HUNT</b></span>
          </button>
          <nav className={`site-nav ${menuOpen ? "site-nav--open" : ""}`} aria-label="Primary navigation">
            {views.map((item) => <button key={item.id} className={`site-nav__link ${view === item.id ? "site-nav__link--active" : ""}`} onClick={() => { setView(item.id); setMenuOpen(false); }} type="button"><span>{item.key}</span>{item.label}</button>)}
          </nav>
          <div className="site-header__tools">
            <button className="header-search" onClick={() => { setView("history"); setMenuOpen(false); window.setTimeout(() => searchRef.current?.focus(), 0); }} type="button"><Icon name="search" size={15} /><span>Search roles</span><kbd>⌘K</kbd></button>
            <span className={`header-health ${serviceActive ? "header-health--live" : ""}`}><span className="pulse-dot" />{serviceActive ? "live" : "offline"}</span>
            <button className={`icon-button ${refreshing ? "is-loading" : ""}`} onClick={() => loadDashboard(true)} type="button" aria-label="Refresh dashboard"><Icon name="refresh" size={17} /></button>
            <button className="menu-toggle" onClick={() => setMenuOpen((open) => !open)} type="button" aria-label="Toggle navigation" aria-expanded={menuOpen}><Icon name={menuOpen ? "x" : "menu"} size={19} /></button>
          </div>
        </div>
      </header>

      <main className="main-canvas">
        {error && <div className="error-banner" role="alert"><Icon name="activity" size={18} /><span>{error}. Check that <code>autopilot ui</code> is running.</span><button onClick={() => loadDashboard(true)} type="button">Retry</button></div>}

        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-grid" aria-hidden="true" />
          <div className="hero-content">
            <p className="eyebrow">AUTOPILOT / JOB OPERATIONS</p>
            <h1 id="hero-title">Every role.<br /><span>One clear next move.</span></h1>
            <p className="hero-lede">Monitor the service, review fresh matches, and move from discovery to application without losing the thread.</p>
            <div className="hero-actions"><button className="action-button action-button--accent" onClick={() => loadDashboard(true)} type="button">Refresh signal <Icon name="arrow" size={16} /></button><span className="hero-note">AUTO-REFRESH / 15 SEC</span></div>
          </div>
          <div className="hero-readout" aria-label="Current service readout">
            <div className="readout-head"><span>RUN STATE</span><span className={serviceActive ? "readout-live" : ""}><span className="pulse-dot" />{serviceActive ? "LIVE" : "OFFLINE"}</span></div>
            <div className="readout-row"><span>daemon</span><strong>{statusLabel}</strong></div>
            <div className="readout-row"><span>last update</span><strong>{relativeTime(dashboard?.generated_at)}</strong></div>
            <div className="readout-row"><span>scan progress</span><strong>{scan.active && scan.progress ? `${scan.progress.current}/${scan.progress.total}` : "Idle"}</strong></div>
          </div>
        </section>

        <section className="signal-strip" aria-label="Scan status" aria-live="polite">
          <div className="signal-strip__lead"><span className={`status-orb ${scan.active ? "status-orb--running" : ""}`}><Icon name={scan.active ? "activity" : "check"} size={20} /></span><div><span className="signal-kicker">BACKGROUND SERVICE</span><strong>{serviceActive ? (scan.active ? "Processing a scan" : "All systems operational") : "Service unavailable"}</strong><span className="signal-detail">{scan.active ? `${prettyLabel(scan.task)} · ${scan.phase || "working"}` : "Watching configured schedules"}</span></div></div>
          <div className="signal-stat"><span>LINKEDIN PASS</span><strong>{latestApify ? formatDate(latestApify.timestamp) : "No run recorded"}</strong><small>{latestApify ? `${latestApify.jobs} jobs · ${latestApify.top_matches} top matches` : "Waiting for first result"}</small></div>
          <div className="signal-stat"><span>CAREERS PASS</span><strong>{latestCareers ? formatDate(latestCareers.timestamp) : "No run recorded"}</strong><small>{latestCareers ? `${latestCareers.jobs} jobs · ${latestCareers.top_matches} top matches` : "Waiting for first result"}</small></div>
        </section>

        <section className="metrics-grid" aria-label="Job totals"><Metric label="New jobs" value={summary.new_jobs ?? 0} detail="last completed scan" accent /><Metric label="History" value={summary.history_jobs ?? 0} detail="saved job records" /><Metric label="Seen URLs" value={(summary.seen_urls ?? 0).toLocaleString()} detail="deduplicated" /><Metric label="LinkedIn IDs" value={(summary.seen_linkedin_ids ?? 0).toLocaleString()} detail="Apify memory" /></section>

        <section className="operator-grid" aria-label="Live scan and candidate profile"><ScanPanel scan={scan} latest={latestApify || latestCareers} /><ProfilePanel profile={profile} /></section>
        <section className="search-config-section" aria-label="Search configuration"><SearchConfigPanel search={search} /></section>

        <section className="content-section">
          {view === "companies" ? <CompaniesWorkspace companies={dashboard?.companies || []} scan={scan} onSaved={() => loadDashboard(true)} /> : <>
            {view === "overview" ? <div className="section-head"><div><p className="eyebrow">RECENT SIGNAL</p><h2>What needs attention</h2></div><div className="section-head__meta">{(dashboard?.history || []).length ? "Latest saved roles" : "No saved roles yet"}</div></div> : <WorkspaceHeader view={view} summary={summary} analytics={analytics} latestRun={latestRun} />}
            {view === "history" && <><HistoryInsights analytics={analytics} /><RunTimeline runs={runs} /></>}
            {view !== "overview" && <div className="list-tools"><label className="search-field"><Icon name="search" size={17} /><span className="sr-only">Search jobs</span><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title, company, location, keywords" /></label><div className="list-tools__controls"><div className="filter-tabs" role="group" aria-label="Filter by source">{["all", "linkedin", "careers"].map((item) => <button className={source === item ? "is-selected" : ""} onClick={() => setSource(item)} key={item} type="button">{item === "all" ? "All" : item === "linkedin" ? "LinkedIn" : "Careers"}</button>)}</div><label className="sort-control"><span>Sort</span><select value={sortBy} onChange={(event) => setSortBy(event.target.value)} aria-label="Sort jobs"><option value="score">Best score</option><option value="recent">Most recent</option><option value="company">Company A–Z</option></select></label></div></div>}
            {view === "overview" ? <div className="overview-grid"><div className="job-list">{(dashboard?.history || []).slice(0, 6).map((job) => <JobRow key={`${job.url}-${job.scan_date}`} job={job} onOpen={setSelectedJob} />)}{!(dashboard?.history || []).length && <EmptyState label="History is empty" detail="Completed scans will appear here once roles are saved." action="Refresh data" onAction={() => loadDashboard(true)} />}</div><aside className="activity-card"><div className="activity-card__head"><span className="eyebrow">EVENT STREAM</span><span className="live-label"><span className="pulse-dot pulse-dot--live" />live</span></div><div className="event-list">{(dashboard?.events || []).slice(0, 7).map((event, index) => <div className="event" key={`${event.timestamp}-${index}`}><span className={`event-marker event-marker--${event.level.toLowerCase()}`} /><div><strong>{event.message}</strong><span>{formatDate(event.timestamp)}</span></div></div>)}{!(dashboard?.events || []).length && <p className="muted-copy">No log events available yet.</p>}</div></aside></div> : <div className="job-list"><div className="results-caption"><span>{filteredJobs.length} matches across {jobs.length} records</span><span>Showing {Math.min(visibleJobs.length, filteredJobs.length)} now</span></div>{visibleJobs.map((job) => <JobRow key={`${job.url}-${job.scan_date}-${job.title}`} job={job} onOpen={setSelectedJob} />)}{visibleJobs.length < sortedJobs.length && <button className="load-more" type="button" onClick={() => setVisibleCount((count) => count + 18)}>Load more roles <span>{sortedJobs.length - visibleJobs.length} remaining</span><Icon name="arrow" size={15} /></button>}{!filteredJobs.length && <EmptyState label={view === "new" ? "No new jobs in this inbox" : "No matching records"} detail={view === "new" ? (latestRun ? `${latestRun.label} checked ${latestRun.companies ? `${latestRun.companies} of ${latestRun.total_companies} company sites` : "LinkedIn"} and finished ${relativeTime(latestRun.timestamp)} with no new roles.` : "The latest completed scan has no jobs to review yet.") : "Try a different search or source filter."} action={view === "new" ? "Refresh data" : "Clear filters"} onAction={view === "new" ? () => loadDashboard(true) : () => { setQuery(""); setSource("all"); }} />}</div>}
          </>}
        </section>

        <footer className="site-footer"><div className="footer-statement">Find the right work.<br /><span>Keep moving.</span></div><div className="footer-meta"><span>AUTOPILOT JOB HUNT / LOCAL CONSOLE</span><span>Updated {relativeTime(dashboard?.generated_at)} · {new Date().getFullYear()}</span></div></footer>
      </main>

      <nav className="mobile-nav" aria-label="Mobile navigation">
        {views.map((item) => <button key={item.id} className={view === item.id ? "is-selected" : ""} onClick={() => { setView(item.id); setMenuOpen(false); }} type="button"><Icon name={item.id === "overview" ? "activity" : item.id === "new" ? "check" : item.id === "history" ? "archive" : "server"} size={18} /><span>{item.label}</span></button>)}
      </nav>

      <dialog ref={dialogRef} className="job-dialog" onClose={() => setSelectedJob(null)}>
        {selectedJob && <div className="dialog-content"><div className="dialog-top"><span className={`source-tag source-tag--${selectedJob.source === "linkedin" || selectedJob.source === "apify_linkedin" ? "linkedin" : "careers"}`}>{sourceLabel(selectedJob.source)}</span><button className="icon-button" onClick={() => dialogRef.current?.close()} type="button" aria-label="Close job details"><Icon name="x" size={18} /></button></div><div className="dialog-heading"><span className={scoreClass(selectedJob.score)}>{selectedJob.score ?? "—"}</span><div><p className="eyebrow">{selectedJob.company}</p><h2>{selectedJob.title}</h2><p>{selectedJob.location}</p></div></div><div className="dialog-grid"><div><span className="detail-label">Why it surfaced</span><p>{selectedJob.reason || "No scoring explanation recorded."}</p></div><div><span className="detail-label">Stack / signal</span><p>{selectedJob.stack || "No stack data recorded."}</p></div><div><span className="detail-label">Scanned</span><p>{formatDate(selectedJob.scan_date)}</p></div><div><span className="detail-label">Application signal</span><p>{selectedJob.worth_applying == null ? "Not recorded" : selectedJob.worth_applying ? "Worth applying" : "Below application threshold"}</p></div></div>{selectedJob.region && <div className="dialog-excerpt"><span className="detail-label">Region</span><p>{selectedJob.region}</p></div>}{selectedJob.content && <div className="dialog-excerpt"><span className="detail-label">Description excerpt</span><p>{selectedJob.content}</p></div>}<a className="primary-link" href={selectedJob.url} target="_blank" rel="noreferrer">Open original listing <Icon name="external" size={16} /></a></div>}
      </dialog>
    </div>
  );
}

function EmptyState({ label, detail, action, onAction }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name="archive" size={19} /></span><strong>{label}</strong><p>{detail}</p><button type="button" onClick={onAction}>{action} <Icon name="arrow" size={15} /></button></div>;
}

createRoot(document.getElementById("root")).render(<App />);
