import os
import shutil
import uuid
from pathlib import Path

import pytest


TEST_DATABASE = Path(__file__).resolve().parents[1] / "storage" / f"pytest-{uuid.uuid4().hex}.db"
os.environ["DATABASE_BACKEND"] = "sqlite"
os.environ["SQLITE_DATABASE"] = str(TEST_DATABASE)
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["GEMINI_API_KEY"] = "test-gemini-key"

from app.ai.ppt_mapping import PPTMapping
from app.ai.template_analysis import analyze_template
from app.db.schema import ensure_schema_upgrades
from app.db.seed import seed
from app.db.session import Base, engine


@pytest.fixture
def tmp_path():
    """Workspace-local temporary path that is reliable in restricted Windows CI."""
    path = TEST_DATABASE.parent / "pytest-files" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def isolated_test_database():
    Base.metadata.create_all(bind=engine)
    ensure_schema_upgrades()
    seed()
    yield
    engine.dispose()
    TEST_DATABASE.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def mocked_report_gemini_mapping(monkeypatch):
    def fake_generate_text(_provider, prompt, *_args, **_kwargs):
        lowered = prompt.lower()
        if "business flow" in lowered or '"nodes"' in lowered:
            return ('{"nodes":[{"id":"start","label":"Start","description":"Process begins","actor":"Business User","type":"input","inputs":[],"outputs":["request"]},{"id":"validate","label":"Validate","description":"Validate the request","actor":"System","type":"decision","inputs":["request"],"outputs":["validated request"]},{"id":"end","label":"Complete","description":"Process completes","actor":"System","type":"output","inputs":["validated request"],"outputs":["result"]}],"edges":[{"source":"start","target":"validate","label":"submitted","kind":"normal"},{"source":"validate","target":"end","label":"valid","kind":"normal"}]}', "test-gemini-model")
        if "architecture" in lowered:
            return ('{"layers":[{"name":"Experience","purpose":"User workflows","components":["Web application"],"securityBoundary":"Browser"},{"name":"Services","purpose":"Business processing","components":["API"],"securityBoundary":"Private network"},{"name":"Data","purpose":"Persistence","components":["Database"],"securityBoundary":"Data subnet"}],"connections":[],"deployment":["Container platform"],"security":["OIDC","RBAC"],"decisions":["Layered architecture"]}', "test-gemini-model")
        return ('{"executive_summary":"Database-grounded delivery summary."}', "test-gemini-model")

    def fake_map_template(path, _db, projects, _statuses, report_metadata=None):
        structure = analyze_template(path)
        slides = []
        for slide in structure.slides:
            mapped_content = {}
            for element in slide.elements:
                if element.type not in {"shape", "placeholder", "table_cell"}:
                    continue
                # Tokenized shapes are intentionally left to the production
                # token replacement path. These are common free-text template
                # labels that require a Gemini-style final text assignment.
                if "{{" not in element.text and "[" not in element.text:
                    if "REPORT TITLE" in element.text.upper():
                        mapped_content[element.id] = (report_metadata or {}).get("title", "Delivery Status Report")
                    elif "EXECUTIVE SUMMARY" in element.text.upper():
                        project_name = projects[0].name if projects else "the selected project"
                        mapped_content[element.id] = f"Current delivery status for {project_name}."
            if mapped_content:
                slides.append({"slide_index": slide.slide_index, "mapped_content": mapped_content})
        if not slides:
            first = next(
                (element for slide in structure.slides for element in slide.elements if element.type in {"shape", "placeholder", "table_cell"}),
                None,
            )
            if first is not None:
                slide_index = int(first.id.split("_")[1])
                slides.append({"slide_index": slide_index, "mapped_content": {}})
        return structure, PPTMapping(slides=slides)

    monkeypatch.setattr("app.reports.generator.map_template", fake_map_template)
    monkeypatch.setattr("app.services.llm.generate_text", fake_generate_text)
    monkeypatch.setattr("app.api.v1.brd.generate_text", fake_generate_text)
