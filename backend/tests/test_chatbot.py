from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from types import SimpleNamespace

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.main import app
from app.models.people import Employee
from app.services import chat as chat_service
from app.services import llm as llm_service


def _headers_for(email: str) -> dict[str, str]:
    with SessionLocal() as db:
        employee = db.query(Employee).filter(Employee.email == email).one()
        return {"Authorization": f"Bearer {create_access_token(employee.id, {'role': employee.role.value})}"}


def test_chat_route_requires_authentication() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/chat", json={"message": "Hi"})
    assert response.status_code == 401


def test_chat_route_is_registered_in_openapi() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "/api/v1/chat" in response.json()["paths"]
    assert "post" in response.json()["paths"]["/api/v1/chat"]
    assert "/api/v1/ai/chat" not in response.json()["paths"]


def test_chat_route_rejects_invalid_request() -> None:
    response = TestClient(app).post(
        "/api/v1/chat",
        json={"message": ""},
        headers=_headers_for("praveen.baburaya@delta.com"),
    )
    assert response.status_code == 422


def test_chat_greeting_uses_groq_without_retrieval(monkeypatch) -> None:
    client = TestClient(app)
    calls = []

    def fake_generate_text(provider, prompt, model=None):
        calls.append((provider, prompt, model))
        return "Hi! How can I help?", "llama-test"

    monkeypatch.setattr("app.services.llm.generate_text", fake_generate_text)
    response = client.post("/api/v1/chat", json={"message": "Hi"}, headers=_headers_for("praveen.baburaya@delta.com"))

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Hi! How can I help?"
    assert body["provider"] == "groq"
    assert body["model"] == "llama-test"
    assert body["retrieval_mode"] == "GENERAL_CHAT"
    assert body["sources"] == []
    assert calls[0][0] == "groq"


def test_chat_db_retrieval_returns_authorized_trimble_context(monkeypatch) -> None:
    client = TestClient(app)
    captured = {}

    def fake_generate_text(provider, prompt, model=None):
        captured["prompt"] = prompt
        return "Trimble has Trimble Finance AI Assistant.", "llama-test"

    monkeypatch.setattr("app.services.llm.generate_text", fake_generate_text)
    response = client.post(
        "/api/v1/chat",
        json={"message": "What projects are under Trimble?"},
        headers=_headers_for("praveen.baburaya@delta.com"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["retrieval_mode"] == "DB_ONLY"
    assert body["state"]["active_account"]
    assert body["state"]["last_entities"]["project_ids"]
    assert any(source["type"] == "project" and "Trimble Finance AI Assistant" in source["title"] for source in body["sources"])
    assert "Trimble Finance AI Assistant" in captured["prompt"]


def test_chat_conversation_context_resolves_first_project(monkeypatch) -> None:
    client = TestClient(app)
    def fake_generate_text(provider, prompt, model=None):
        return "The first project has the listed active allocations.", "llama-test"

    monkeypatch.setattr("app.services.llm.generate_text", fake_generate_text)
    headers = _headers_for("praveen.baburaya@delta.com")
    first = client.post("/api/v1/chat", json={"message": "What projects are under Trimble?"}, headers=headers)
    response = client.post(
        "/api/v1/chat",
        json={
            "message": "Who is assigned to the first project?",
            "conversation_id": first.json()["conversation_id"],
            "state": first.json()["state"],
            "messages": [
                {"role": "user", "content": "What projects are under Trimble?"},
                {"role": "assistant", "content": first.json()["answer"]},
            ],
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["state"]["active_project"] == first.json()["state"]["last_entities"]["project_ids"][0]


def test_chat_rag_retrieval_filters_to_visible_projects(monkeypatch) -> None:
    client = TestClient(app)
    captured = {}

    def fake_search(question, top_k=5, project_id=None, allowed_project_ids=None):
        captured["allowed_project_ids"] = allowed_project_ids
        return [{"document": "Architecture uses FastAPI gateway with RBAC.", "metadata": {"project_id": sorted(allowed_project_ids)[0]}, "distance": 0.1}]

    def fake_generate_text(provider, prompt, model=None):
        captured["prompt"] = prompt
        return "Architecture uses FastAPI gateway with RBAC.", "llama-test"

    monkeypatch.setattr(chat_service, "search_knowledge", fake_search)
    monkeypatch.setattr("app.services.llm.generate_text", fake_generate_text)

    response = client.post(
        "/api/v1/chat",
        json={"message": "Tell me about the architecture"},
        headers=_headers_for("praveen.baburaya@delta.com"),
    )

    assert response.status_code == 200
    assert response.json()["retrieval_mode"] == "RAG_ONLY"
    assert captured["allowed_project_ids"]
    assert "Architecture uses FastAPI gateway" in captured["prompt"]


def test_chat_empty_results_do_not_invent_records(monkeypatch) -> None:
    client = TestClient(app)
    def fake_generate_text(provider, prompt, model=None):
        raise AssertionError("Groq should not be called when the entity cannot be resolved")
        return "I do not see any authorized records for that.", "llama-test"

    monkeypatch.setattr("app.services.llm.generate_text", fake_generate_text)
    response = client.post(
        "/api/v1/chat",
        json={"message": "What projects are under NoSuchAccountEver?"},
        headers=_headers_for("praveen.baburaya@delta.com"),
    )

    assert response.status_code == 200
    assert "could not find an authorized account or project" in response.json()["answer"]


def test_chat_reports_db_rag_when_question_needs_both(monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(chat_service, "search_knowledge", lambda *args, **kwargs: [{"document": "Architecture risk is ERP schema drift.", "metadata": {}, "distance": 0.2}])
    monkeypatch.setattr("app.services.llm.generate_text", lambda *args, **kwargs: ("Status is green; architecture risk is ERP schema drift.", "llama-test"))

    response = client.post(
        "/api/v1/chat",
        json={"message": "What is the current status of Trimble and what are its architecture risks?"},
        headers=_headers_for("praveen.baburaya@delta.com"),
    )

    assert response.status_code == 200
    assert response.json()["retrieval_mode"] == "DB_RAG"


def test_chat_db_failure_surfaces_error(monkeypatch) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    def fail_context(*args, **kwargs):
        raise OperationalError("select 1", {}, RuntimeError("database down"))

    monkeypatch.setattr(chat_service, "_build_db_context", fail_context)
    response = client.post(
        "/api/v1/chat",
        json={"message": "What accounts exist?"},
        headers=_headers_for("praveen.baburaya@delta.com"),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "The governance database is temporarily unavailable."


def test_chat_groq_failure_is_distinct(monkeypatch) -> None:
    def fail_groq(*args, **kwargs):
        from fastapi import HTTPException

        raise HTTPException(status_code=502, detail="Groq generation failed.")

    monkeypatch.setattr("app.services.llm.generate_text", fail_groq)
    response = TestClient(app).post(
        "/api/v1/chat",
        json={"message": "Hi"},
        headers=_headers_for("praveen.baburaya@delta.com"),
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Groq generation failed."


def test_chat_rag_failure_is_distinct(monkeypatch) -> None:
    monkeypatch.setattr(chat_service, "search_knowledge", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("vector store down")))
    response = TestClient(app).post(
        "/api/v1/chat",
        json={"message": "What architecture approach was defined?"},
        headers=_headers_for("praveen.baburaya@delta.com"),
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Semantic retrieval failed."


def test_unavailable_configured_groq_model_selects_available_production_model(monkeypatch) -> None:
    settings = SimpleNamespace(
        groq_api_key="configured-test-key",
        groq_default_model="retired-model",
        gemini_default_model="gemini-test",
    )

    class FakeGroq:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "configured-test-key"
            self.models = SimpleNamespace(
                list=lambda: SimpleNamespace(
                    data=[SimpleNamespace(id="llama-3.1-8b-instant")]
                )
            )

    monkeypatch.setattr(llm_service, "get_settings", lambda: settings)
    monkeypatch.setattr("groq.Groq", FakeGroq)

    assert llm_service.resolve_available_groq_model() == "llama-3.1-8b-instant"


def test_chat_uses_real_seeded_allocations_in_context(monkeypatch) -> None:
    captured = {}

    def fake_generate_text(provider, prompt, model=None):
        captured["prompt"] = prompt
        return "Here are the assigned people.", "llama-test"

    monkeypatch.setattr("app.services.llm.generate_text", fake_generate_text)
    with SessionLocal() as db:
        actor = db.query(Employee).filter(Employee.email == "praveen.baburaya@delta.com").one()
        payload = chat_service.ChatRequest(message="List people assigned to Trimble projects")
        chat_service.answer_chat(payload, actor, db)

    assert "Active allocations:" in captured["prompt"]
    assert "Trimble Finance AI Assistant" in captured["prompt"]
