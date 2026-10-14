import os

os.environ.update({
    "DATABASE_URL": "sqlite://", "LLM_PROVIDER": "none", "CRM_PROVIDER": "mock", "RUN_WORKER": "false",
    "ENRICH_FETCH_WEBSITE": "false", "API_KEY": "", "WEBHOOK_SECRET": "", "SEED_DEMO": "false",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import init_db  # noqa: E402
from app.graph import build_graph  # noqa: E402


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def session_factory():
    # CI runs the suite against a real Postgres via TEST_DATABASE_URL; locally SQLite in memory.
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        from app.db import Base
        engine = create_engine(url)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def graph(settings):
    return build_graph(settings, llm=None, http_client=None)


@pytest.fixture
def client(session_factory):
    from app.main import app

    app.state.session_factory = session_factory
    for attr in ("graph", "crm", "llm"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)
    with TestClient(app) as c:
        yield c
