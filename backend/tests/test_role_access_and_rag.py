from fastapi.testclient import TestClient

from app.core.security import normalize_role_value
from app.main import app


def test_normalize_role_value_for_studio_head() -> None:
    assert normalize_role_value("studio_head") == "studio_head"
    assert normalize_role_value("STUDIO_HEAD") == "studio_head"
    assert normalize_role_value("delivery_head") == "studio_head"


def test_studio_head_rag_request_is_authorized() -> None:
    client = TestClient(app)
    login = client.post("/api/v1/auth/login", json={"email": "praveen.baburaya@delta.com", "password": "Demo@123"})
    assert login.status_code == 200
    token = login.json()["access_token"]

    response = client.post(
        "/api/v1/ai/rag/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"question": "What accounts are visible to the studio head?", "top_k": 3},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "groq"
    assert len(body["answer"]) > 0
