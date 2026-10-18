import hashlib
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import db
from app.config import get_settings
from app.crm import CrmError, get_crm
from app.graph import build_graph
from app.llm import get_chat_model
from app.models import Lead, LeadStatus, Report
from app.report import generate_report
from app.schemas import ApproveIn, LeadDetailOut, LeadIn, LeadOut, RejectIn, ReportOut
from app.services import (
    InvalidState,
    approve_lead,
    log_event,
    process_lead,
    process_pending,
    reject_lead,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("leadpilot")
STATIC = Path(__file__).parent / "static"


def _worker_loop(app: FastAPI, stop: threading.Event) -> None:
    st = app.state
    while not stop.wait(st.settings.worker_interval_s):
        try:
            process_pending(st.session_factory, st.graph, st.settings)
        except Exception:
            log.exception("worker iteration failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    st = app.state
    st.settings = settings
    st.session_factory = getattr(st, "session_factory", None) or db.SessionLocal
    db.init_db(st.session_factory.kw["bind"])
    st.llm = getattr(st, "llm", None) or get_chat_model()
    st.http = httpx.Client(timeout=settings.enrich_timeout_s)
    st.graph = getattr(st, "graph", None) or build_graph(settings, st.llm, st.http)
    st.crm = getattr(st, "crm", None) or get_crm(settings, st.session_factory)
    log.info("LeadPilot up | llm=%s crm=%s", settings.llm_provider if st.llm else "heuristic", st.crm.name)

    if (settings.seed_demo or settings.demo_mode) and st.crm.name == "mock":
        from app.demo import seed_demo

        if seed_demo(st.session_factory, st.graph, settings, st.crm):
            generate_report(st.session_factory, st.llm)

    stop = threading.Event()
    scheduler = None
    if settings.run_worker:
        threading.Thread(target=_worker_loop, args=(app, stop), daemon=True, name="lead-worker").start()
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            lambda: generate_report(st.session_factory, st.llm, slack_webhook_url=settings.slack_webhook_url),
            CronTrigger(day_of_week=settings.report_cron_day, hour=settings.report_cron_hour),
            id="weekly_report", max_instances=1, coalesce=True,
        )
        scheduler.start()
    yield
    stop.set()
    if scheduler:
        scheduler.shutdown(wait=False)
    st.http.close()


app = FastAPI(title="LeadPilot", version="1.0.0", lifespan=lifespan,
              description="Multi-agent lead qualification, enrichment and CRM sync with human approval.")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def session(request: Request):
    s = request.app.state.session_factory()
    try:
        yield s
    finally:
        s.close()


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)):
    expected = request.app.state.settings.api_key
    if expected and x_api_key != expected:
        raise HTTPException(401, "invalid or missing X-API-Key")


auth = [Depends(require_api_key)]


def _get_lead(s: Session, lead_id: int) -> Lead:
    lead = s.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "lead not found")
    return lead


def _client_ip_hash(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "")
    return hashlib.sha256(f"leadpilot:{ip}".encode()).hexdigest()


def _enqueue(request: Request, bg: BackgroundTasks, s: Session, data: LeadIn, raw: dict, idem: str | None) -> Lead:
    st = request.app.state
    if idem:
        existing = s.scalar(select(Lead).where(Lead.idempotency_key == idem))
        if existing:
            return existing
    ip_hash = _client_ip_hash(request)
    if st.settings.demo_mode:
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        recent = s.scalar(select(func.count(Lead.id)).where(Lead.client_ip_hash == ip_hash, Lead.created_at >= since))
        if recent >= st.settings.demo_submissions_per_hour:
            raise HTTPException(429, "Demo limit reached: a few test leads per hour. Try again later.")
    lead = Lead(**data.model_dump(), raw=raw, idempotency_key=idem, client_ip_hash=ip_hash)
    s.add(lead)
    try:
        s.commit()
    except IntegrityError:  # concurrent duplicate with the same key
        s.rollback()
        return s.scalar(select(Lead).where(Lead.idempotency_key == idem))
    log_event(s, lead.id, "received", {"source": lead.source})
    s.commit()
    if st.settings.inline_processing:
        # Serverless: no process outlives the request, so run the (bounded) pipeline now.
        process_lead(lead.id, st.session_factory, st.graph, st.settings)
        s.expire_all()
        return s.get(Lead, lead.id)
    # Long-running host: answer immediately; the polling worker is the safety net if this process dies.
    bg.add_task(process_lead, lead.id, st.session_factory, st.graph, st.settings)
    return lead


def _page(name: str) -> HTMLResponse:
    html = (STATIC / name).read_text(encoding="utf-8")
    st = get_settings()
    if st.public_url:  # link previews (LinkedIn, Upwork, WhatsApp) need absolute image URLs
        html = html.replace('content="/static/', f'content="{st.public_url.rstrip("/")}/static/')
    return HTMLResponse(html.replace("{{CONTACT_URL}}", st.contact_url))


@app.get("/", include_in_schema=False)
def landing():
    return _page("landing.html")


@app.get("/app", include_in_schema=False)
def web_app():
    return _page("app.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "logo.svg", media_type="image/svg+xml")


@app.get("/api/meta")
def meta(request: Request):
    st = request.app.state
    return {"workspace": st.settings.workspace_name, "demo": st.settings.demo_mode,
            "contact_url": st.settings.contact_url, "crm": st.crm.name,
            "llm": (st.settings.llm_model if st.llm else "rules"), "hot_threshold": st.settings.hot_threshold,
            "warm_threshold": st.settings.warm_threshold}


@app.get("/api/cron/daily", include_in_schema=False)
def cron_daily(request: Request, authorization: str | None = Header(default=None)):
    """Vercel Cron (Hobby: once a day). Drains the queue, resets the public demo, writes the weekly report."""
    st = request.app.state
    if not st.settings.cron_secret or authorization != f"Bearer {st.settings.cron_secret}":
        raise HTTPException(401, "invalid cron secret")
    done = {"processed": process_pending(st.session_factory, st.graph, st.settings)}
    if st.settings.demo_mode and st.crm.name == "mock":
        from app.demo import reset_demo

        done["demo_reseeded"] = reset_demo(st.session_factory, st.graph, st.settings, st.crm)
        generate_report(st.session_factory, st.llm)
        done["report"] = True
    elif datetime.now(timezone.utc).strftime("%a").lower() == st.settings.report_cron_day:
        generate_report(st.session_factory, st.llm, slack_webhook_url=st.settings.slack_webhook_url)
        done["report"] = True
    return done


@app.get("/health")
def health(s: Session = Depends(session)):
    s.execute(select(1))
    return {"status": "ok"}


@app.post("/api/leads", response_model=LeadOut, status_code=201, dependencies=auth)
def create_lead(data: LeadIn, request: Request, bg: BackgroundTasks, s: Session = Depends(session),
                idempotency_key: str | None = Header(default=None)):
    return _enqueue(request, bg, s, data, data.model_dump(), idempotency_key)


FIELD_ALIASES = {
    "email": ["email", "Email", "email_address", "your-email"],
    "first_name": ["first_name", "firstname", "firstName", "First Name"],
    "last_name": ["last_name", "lastname", "lastName", "Last Name"],
    "company": ["company", "company_name", "organization", "Company"],
    "website": ["website", "url", "company_website"],
    "phone": ["phone", "phone_number", "tel"],
    "job_title": ["job_title", "title", "role", "jobtitle"],
    "message": ["message", "description", "details", "project", "your-message", "Message"],
}


@app.post("/api/webhooks/lead", status_code=202)
async def webhook_lead(request: Request, bg: BackgroundTasks, s: Session = Depends(session),
                       source: str = Query("webhook"), x_webhook_secret: str | None = Header(default=None)):
    """Accepts JSON or form posts from Typeform, Webflow, Tally, WordPress, Zapier, n8n..."""
    secret = request.app.state.settings.webhook_secret
    if secret and x_webhook_secret != secret and request.query_params.get("secret") != secret:
        raise HTTPException(401, "invalid webhook secret")
    ctype = request.headers.get("content-type", "")
    raw = dict(await request.form()) if "form" in ctype else await request.json()
    mapped = {field: next((raw[k] for k in keys if raw.get(k)), None) for field, keys in FIELD_ALIASES.items()}
    if not mapped["first_name"] and raw.get("name"):
        parts = str(raw["name"]).split(" ", 1)
        mapped["first_name"], mapped["last_name"] = parts[0], (parts[1] if len(parts) > 1 else None)
    try:
        data = LeadIn(**{k: v for k, v in mapped.items() if v is not None}, source=source)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
    lead = _enqueue(request, bg, s, data, raw, request.headers.get("idempotency-key"))
    return {"id": lead.id, "status": lead.status}


@app.get("/api/leads", response_model=list[LeadOut], dependencies=auth)
def list_leads(s: Session = Depends(session), status: str | None = None, tier: str | None = None,
               limit: int = Query(100, le=500)):
    q = select(Lead).order_by(Lead.created_at.desc()).limit(limit)
    if status:
        q = q.where(Lead.status == status)
    if tier:
        q = q.where(Lead.tier == tier)
    return s.scalars(q).all()


@app.get("/api/leads/{lead_id}", response_model=LeadDetailOut, dependencies=auth)
def get_lead(lead_id: int, s: Session = Depends(session)):
    return _get_lead(s, lead_id)


@app.post("/api/leads/{lead_id}/approve", response_model=LeadOut, dependencies=auth)
def approve(lead_id: int, data: ApproveIn, request: Request, s: Session = Depends(session)):
    lead = _get_lead(s, lead_id)
    try:
        return approve_lead(s, lead, data, request.app.state.crm)
    except InvalidState as exc:
        raise HTTPException(409, str(exc)) from exc
    except CrmError as exc:
        raise HTTPException(502, f"CRM write failed, lead kept in queue: {exc}") from exc


@app.post("/api/leads/{lead_id}/reject", response_model=LeadOut, dependencies=auth)
def reject(lead_id: int, data: RejectIn, s: Session = Depends(session)):
    try:
        return reject_lead(s, _get_lead(s, lead_id), data)
    except InvalidState as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/leads/{lead_id}/reprocess", response_model=LeadOut, dependencies=auth)
def reprocess(lead_id: int, request: Request, bg: BackgroundTasks, s: Session = Depends(session)):
    lead = _get_lead(s, lead_id)
    if lead.status in (LeadStatus.SYNCED, LeadStatus.PROCESSING):
        raise HTTPException(409, f"cannot reprocess a {lead.status} lead")
    lead.status, lead.attempts = LeadStatus.RECEIVED, 0
    log_event(s, lead.id, "reprocess_requested")
    s.commit()
    st = request.app.state
    if st.settings.inline_processing:
        process_lead(lead.id, st.session_factory, st.graph, st.settings)
        s.expire_all()
        return s.get(Lead, lead.id)
    bg.add_task(process_lead, lead.id, st.session_factory, st.graph, st.settings)
    return lead


@app.get("/api/stats", dependencies=auth)
def stats(s: Session = Depends(session)):
    by_status = dict(s.execute(select(Lead.status, func.count()).group_by(Lead.status)).all())
    by_tier = dict(s.execute(select(Lead.tier, func.count()).where(Lead.tier.is_not(None)).group_by(Lead.tier)).all())
    st = get_settings()
    return {"by_status": by_status, "by_tier": by_tier, "crm": app.state.crm.name,
            "llm": st.llm_provider if app.state.llm else "heuristic"}


@app.get("/api/reports", response_model=list[ReportOut], dependencies=auth)
def list_reports(s: Session = Depends(session), limit: int = Query(10, le=100)):
    return s.scalars(select(Report).order_by(Report.id.desc()).limit(limit)).all()


@app.get("/api/reports/latest", response_model=ReportOut, dependencies=auth)
def latest_report(s: Session = Depends(session)):
    report = s.scalar(select(Report).order_by(Report.id.desc()).limit(1))
    if not report:
        raise HTTPException(404, "no report yet")
    return report


@app.post("/api/reports/generate", response_model=ReportOut, dependencies=auth)
def make_report(request: Request, days: int = Query(7, ge=1, le=90)):
    st = request.app.state
    return generate_report(st.session_factory, st.llm, days=days, slack_webhook_url=st.settings.slack_webhook_url)
