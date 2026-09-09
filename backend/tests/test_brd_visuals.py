from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "praveen.baburaya@delta.com", "password": "Demo@123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_brd_upload_generation_context_and_visual_exports(monkeypatch, tmp_path) -> None:
    prompts: list[str] = []

    def fake_gemini(provider: str, prompt: str, model: str | None = None):
        assert provider == "gemini"
        prompts.append(prompt)
        if "business process architect" in prompt:
            return (
                '{"nodes":['
                '{"id":"start","label":"Receive onboarding request","description":"Capture the approved client request","type":"start","actor":"Account Manager","inputs":["Approved request"],"outputs":["Onboarding case"]},'
                '{"id":"validate","label":"Validate commercial terms","description":"Check contract and mandatory data","type":"decision","actor":"Operations Lead","business_rule":"All mandatory terms must be approved"},'
                '{"id":"provision","label":"Provision client workspace","description":"Create the governed delivery workspace","type":"process","actor":"Platform Service","inputs":["Validated case"],"outputs":["Active workspace"]},'
                '{"id":"complete","label":"Confirm onboarding","description":"Notify stakeholders that onboarding is complete","type":"end","actor":"Account Manager"}],'
                '"edges":['
                '{"source":"start","target":"validate","label":"submitted","kind":"normal"},'
                '{"source":"validate","target":"provision","label":"approved","kind":"normal"},'
                '{"source":"provision","target":"complete","label":"workspace active","kind":"normal"}],'
                '"outcome":"Client workspace is ready for governed delivery."}',
                model or "test-gemini-model",
            )
        raise AssertionError("Unexpected Gemini prompt")

    monkeypatch.setattr("app.api.v1.brd.generate_text", fake_gemini)
    monkeypatch.setattr("app.api.v1.brd.resolve_app_path", lambda _path: tmp_path / "uploaded-brds")

    with TestClient(app) as client:
        headers = _auth_headers(client)
        projects = client.get("/api/v1/governance/projects", headers=headers)
        assert projects.status_code == 200
        project_id = projects.json()[0]["id"]

        unique_source = "Settlement exceptions require a finance controller approval before onboarding."
        uploaded = client.post(
            "/api/v1/brd/documents/upload",
            headers=headers,
            data={"project_id": project_id, "document_type": "brd"},
            files={"file": ("client-onboarding.md", unique_source.encode(), "text/markdown")},
        )
        assert uploaded.status_code == 201, uploaded.text
        document = uploaded.json()
        assert document["filename"] == "client-onboarding.md"
        assert document["status"] == "ready"

        register = client.get(f"/api/v1/brd/documents?project_id={project_id}", headers=headers)
        assert register.status_code == 200
        assert document["id"] in {item["id"] for item in register.json()}

        generated = client.post(
            "/api/v1/brd/generate",
            headers=headers,
            json={
                "project_id": project_id,
                "document_id": document["id"],
                "artifact_type": "business_flow",
                "provider": "gemini",
            },
        )
        assert generated.status_code == 200, generated.text
        flow = generated.json()["artifact"]
        assert flow["ai_provider"] == "gemini"
        assert unique_source in prompts[-1]
        assert len(flow["payload"]["nodes"]) == 4

        architecture_payload = {
            "title": "Client Onboarding Architecture",
            "objective": "Provide governed onboarding with explicit approval controls.",
            "external_systems": [
                {"name": "Client CRM", "type": "external", "description": "Originates approved onboarding requests"}
            ],
            "layers": [
                {
                    "name": "Experience",
                    "purpose": "Stakeholder interactions",
                    "components": [{"name": "Operations Portal", "type": "experience", "responsibility": "Capture and track requests", "technology": "Web"}],
                },
                {
                    "name": "Application and API",
                    "purpose": "Secure orchestration",
                    "components": [{"name": "Onboarding API", "type": "api", "responsibility": "Validate and route onboarding commands", "technology": "REST"}],
                },
                {
                    "name": "Business Services",
                    "purpose": "Approval and workspace provisioning",
                    "components": [{"name": "Approval Service", "type": "service", "responsibility": "Enforce finance approval policy"}],
                },
                {
                    "name": "Data",
                    "purpose": "Durable case records",
                    "components": [{"name": "Onboarding Store", "type": "database", "responsibility": "Persist cases and audit history", "technology": "SQL"}],
                },
            ],
            "connections": [
                {"from": "Client CRM", "to": "Operations Portal", "label": "approved request", "protocol": "HTTPS"},
                {"from": "Operations Portal", "to": "Onboarding API", "label": "commands", "protocol": "REST"},
                {"from": "Onboarding API", "to": "Approval Service", "label": "approval check"},
                {"from": "Approval Service", "to": "Onboarding Store", "label": "case and audit event"},
            ],
            "security": ["Role-based access", "Immutable approval audit trail"],
            "deployment": ["Managed application runtime"],
        }
        architecture = client.post(
            "/api/v1/brd/artifacts",
            headers=headers,
            json={
                "project_id": project_id,
                "document_id": document["id"],
                "artifact_type": "architecture",
                "title": "Client Onboarding Architecture",
                "payload": architecture_payload,
                "ai_provider": "gemini",
                "model_used": "test-gemini-model",
            },
        )
        assert architecture.status_code == 201, architecture.text

        for artifact in (flow, architecture.json()):
            for export_format, signature in (("png", b"\x89PNG"), ("pdf", b"%PDF"), ("docx", b"PK")):
                exported = client.get(
                    f"/api/v1/brd/artifacts/{artifact['id']}/export?format={export_format}",
                    headers=headers,
                )
                assert exported.status_code == 200, exported.text
                assert exported.content.startswith(signature)
                assert len(exported.content) > 1_000
            drawio = client.get(
                f"/api/v1/brd/artifacts/{artifact['id']}/export?format=drawio",
                headers=headers,
            )
            assert drawio.status_code == 200
            assert b"endArrow=block" in drawio.content
            ElementTree.fromstring(drawio.content)

        architecture_png = client.get(
            f"/api/v1/brd/artifacts/{architecture.json()['id']}/export?format=png",
            headers=headers,
        )
        image = Image.open(BytesIO(architecture_png.content))
        assert image.width >= 1400
        assert image.height >= 620
        assert len(image.getcolors(maxcolors=image.width * image.height) or []) > 8


def test_brd_upload_rejects_unsupported_or_empty_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.api.v1.brd.resolve_app_path", lambda _path: tmp_path / "uploaded-brds")
    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = client.get("/api/v1/governance/projects", headers=headers).json()[0]["id"]
        unsupported = client.post(
            "/api/v1/brd/documents/upload",
            headers=headers,
            data={"project_id": project_id},
            files={"file": ("payload.json", b"{}", "application/json")},
        )
        assert unsupported.status_code == 422
        assert "PDF, DOCX, TXT, or Markdown" in unsupported.json()["detail"]

        empty = client.post(
            "/api/v1/brd/documents/upload",
            headers=headers,
            data={"project_id": project_id},
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert empty.status_code == 422
        assert empty.json()["detail"] == "The selected BRD file is empty."
