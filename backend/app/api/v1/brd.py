import json
import io
import math
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings, resolve_app_path
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.brd import BRDDesignArtifact, BRDDocument, BRDDocumentStatus, BRDRequirementSet
from app.models.delivery import Account, Project
from app.models.people import Employee
from app.schemas.common import (
    BRDArtifactCreate,
    BRDArtifactOut,
    BRDDocumentOut,
    BRDGenerateRequest,
    RequirementOut,
    RequirementSave,
)
from app.services.audit import audit
from app.services.access import require_project_access, require_project_manager, visible_project_ids
from app.services.llm import generate_text
from starlette.responses import Response

router = APIRouter(prefix="/brd", tags=["brd-studio"])
SUPPORTED_ARTIFACT_TYPES = {"business_flow", "architecture"}


def _json_dump(value: object) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _json_load(value: str | None, fallback: object) -> object:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _gemini_json(prompt: str, model: str | None = None) -> tuple[dict, str]:
    try:
        text, model_used = generate_text("gemini", prompt, model)
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise ValueError("Gemini response is not an object")
        return payload, model_used
    except HTTPException:
        raise
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Gemini returned an invalid structured artifact.") from exc


def _validate_diagram_payload(artifact_type: str, payload: dict) -> dict:
    if artifact_type == "business_flow":
        nodes = payload.get("nodes")
        edges = payload.get("edges")
        if not isinstance(nodes, list) or len(nodes) < 3 or not isinstance(edges, list) or len(edges) < 2:
            raise HTTPException(status_code=502, detail="Gemini returned an incomplete business flow.")
        node_ids = {
            str(node.get("id"))
            for node in nodes
            if isinstance(node, dict) and node.get("id") and node.get("label")
        }
        valid_edges = [edge for edge in edges if isinstance(edge, dict)]
        if len(node_ids) != len(nodes) or len(valid_edges) != len(edges) or any(
            edge.get("source") not in node_ids or edge.get("target") not in node_ids
            for edge in valid_edges
        ):
            raise HTTPException(status_code=502, detail="Gemini returned invalid business-flow connections.")
    elif artifact_type == "architecture":
        layers = payload.get("layers")

        if not isinstance(layers, list) or len(layers) < 4:
            raise HTTPException(
                status_code=502,
                detail="Gemini returned an insufficiently detailed solution architecture.",
            )

        total_components = 0
        component_names = set()

        for layer in layers:
            if (
                not isinstance(layer, dict)
                or not layer.get("name")
                or not isinstance(layer.get("components"), list)
            ):
                raise HTTPException(
                    status_code=502,
                    detail="Gemini returned an invalid solution architecture.",
                )

            components = layer["components"]

            if len(components) < 2:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Architecture layer '{layer.get('name')}' "
                        "contains fewer than 2 meaningful components."
                    ),
                )

            if len(components) > 8:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"Architecture layer '{layer.get('name')}' "
                        "contains too many components."
                    ),
                )

            for component in components:
                if isinstance(component, str):
                    name = component.strip()
                elif isinstance(component, dict):
                    name = str(component.get("name") or "").strip()
                else:
                    name = ""

                if not name:
                    raise HTTPException(
                        status_code=502,
                        detail="Gemini returned an architecture component without a name.",
                    )

                normalized_name = name.lower()

                if normalized_name in component_names:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Duplicate architecture component: {name}",
                    )

                component_names.add(normalized_name)
                total_components += 1

        if total_components < 12:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Gemini returned an architecture that is too shallow. "
                    "At least 12 meaningful components are required."
                ),
            )

        external_systems = payload.get("external_systems", [])

        if isinstance(external_systems, list):
            for system in external_systems:
                if isinstance(system, str):
                    name = system.strip()
                elif isinstance(system, dict):
                    name = str(system.get("name") or "").strip()
                else:
                    name = ""

                if name:
                    component_names.add(name.lower())

        connections = []
        for key in ("connections", "relationships"):
            if isinstance(payload.get(key), list):
                connections.extend(payload[key])

        if len(connections) < 8:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Gemini returned too few architecture relationships. "
                    "At least 8 meaningful connections are required."
                ),
            )

        for connection in connections:
            if not isinstance(connection, dict):
                raise HTTPException(
                    status_code=502,
                    detail="Gemini returned an invalid architecture connection.",
                )

            source = str(
                connection.get("from")
                or connection.get("source")
                or ""
            ).strip().lower()

            target = str(
                connection.get("to")
                or connection.get("target")
                or ""
            ).strip().lower()

            if source not in component_names or target not in component_names:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Gemini returned architecture connections "
                        "with unknown components."
                    ),
                )
    return payload


def _extract_document_text(content: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        elif suffix == ".docx":
            from docx import Document

            document = Document(io.BytesIO(content))
            paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
            table_rows = [
                " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                for table in document.tables
                for row in table.rows
            ]
            extracted = "\n".join([*paragraphs, *filter(None, table_rows)])
        elif suffix in {".txt", ".md"}:
            extracted = content.decode("utf-8-sig", errors="replace")
        else:
            raise HTTPException(
                status_code=422,
                detail="BRD files must use PDF, DOCX, TXT, or Markdown format.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="The selected BRD file could not be read.") from exc

    normalized = "\n".join(line.strip() for line in extracted.splitlines() if line.strip())
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail="No readable text was found in the BRD. Scanned documents require OCR before upload.",
        )
    return normalized[:120000]


def _artifact_sections(artifact: BRDDesignArtifact) -> list[tuple[str, list[str]]]:
    payload = _json_load(artifact.payload_json, {})
    if not isinstance(payload, dict):
        return [(artifact.title, ["No structured artifact content is available."])]
    sections: list[tuple[str, list[str]]] = []
    if artifact.artifact_type == "business_flow":
        for node in payload.get("nodes", []):
            if isinstance(node, dict):
                details = []
                if node.get("description"):
                    details.append(str(node["description"]))
                if node.get("actor") or node.get("system"):
                    details.append(f"Actor/System: {node.get('actor') or node.get('system')}")
                if node.get("inputs"):
                    details.append(f"Inputs: {', '.join(map(str, node['inputs']))}")
                if node.get("outputs"):
                    details.append(f"Outputs: {', '.join(map(str, node['outputs']))}")
                if node.get("business_rule"):
                    details.append(f"Rule: {node['business_rule']}")
                sections.append((str(node.get("label") or node.get("id") or "Step"), details or ["Process step"]))
    else:
        for layer in payload.get("layers", []):
            if isinstance(layer, dict):
                components = []
                for item in layer.get("components", []):
                    if isinstance(item, dict):
                        detail = item.get("responsibility") or item.get("description")
                        technology = item.get("technology")
                        suffix = " — ".join(str(value) for value in (detail, technology) if value)
                        components.append(f"{item.get('name', 'Component')}{': ' + suffix if suffix else ''}")
                    elif isinstance(item, str):
                        components.append(item)
                if layer.get("purpose"):
                    components.insert(0, str(layer["purpose"]))
                sections.append((str(layer.get("name") or "Layer"), components))
        for heading, key in (("Security", "security"), ("Deployment", "deployment")):
            values = payload.get(key)
            if isinstance(values, list) and values:
                sections.append((heading, [str(value) for value in values]))
    return sections


def _flow_positions(nodes: list[dict], edges: list[dict]) -> dict[str, tuple[int, int]]:
    node_ids = [str(node.get("id")) for node in nodes]
    incoming = {node_id: 0 for node_id in node_ids}
    outgoing = {node_id: [] for node_id in node_ids}

    for edge in edges:
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if source in outgoing and target in incoming:
            outgoing[source].append(target)
            incoming[target] += 1

    ranks = {node_id: 0 for node_id in node_ids}
    pending = dict(incoming)
    queue = [node_id for node_id in node_ids if pending[node_id] == 0]
    visited = set()

    while queue:
        node_id = queue.pop(0)
        visited.add(node_id)
        for target in outgoing[node_id]:
            ranks[target] = max(ranks[target], ranks[node_id] + 1)
            pending[target] -= 1
            if pending[target] == 0:
                queue.append(target)

    for node_id in node_ids:
        if node_id not in visited:
            ranks[node_id] = max(ranks.values(), default=0) + 1

    groups: dict[int, list[str]] = {}
    for node_id in node_ids:
        groups.setdefault(ranks[node_id], []).append(node_id)

    # Wrap rank columns into visual bands so a business flow does not become
    # one extremely wide horizontal strip.
    positions: dict[str, tuple[int, int]] = {}
    for rank, group in groups.items():
        visual_column = rank % 3
        visual_band = rank // 3

        for row, node_id in enumerate(group):
            positions[node_id] = (
                80 + visual_column * 360,
                150 + visual_band * 230 + row * 150,
            )

    return positions


def _resolve_component_id(name: object, name_to_id: dict[str, str]) -> str | None:
    value = str(name or "").strip().lower()
    if not value:
        return None

    if value in name_to_id:
        return name_to_id[value]

    normalized = " ".join(value.replace("-", " ").replace("_", " ").split())

    for candidate, node_id in name_to_id.items():
        candidate_normalized = " ".join(
            candidate.replace("-", " ").replace("_", " ").split()
        )
        if normalized == candidate_normalized:
            return node_id

    for candidate, node_id in name_to_id.items():
        if normalized in candidate or candidate in normalized:
            return node_id

    return None


def _architecture_graph(payload: dict) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    name_to_id: dict[str, str] = {}
    column = 0
    external = payload.get("external_systems", [])
    if isinstance(external, list) and external:
        for row, item in enumerate(external):
            component = {"name": item} if isinstance(item, str) else item
            if not isinstance(component, dict) or not component.get("name"):
                continue
            node_id = f"external-{row}"
            name_to_id[str(component["name"]).lower()] = node_id
            nodes.append({"id": node_id, "label": component["name"], "description": component.get("description", "External system"), "x": 60, "y": 110 + row * 145, "style": "external"})
        column = 1
    for layer_index, layer in enumerate(payload.get("layers", [])):
        if not isinstance(layer, dict):
            continue
        for row, item in enumerate(layer.get("components", [])):
            component = {"name": item} if isinstance(item, str) else item
            if not isinstance(component, dict) or not component.get("name"):
                continue
            node_id = f"layer-{layer_index}-component-{row}"
            name_to_id[str(component["name"]).lower()] = node_id
            detail = component.get("responsibility") or component.get("description") or component.get("technology") or layer.get("purpose", "")
            nodes.append({"id": node_id, "label": component["name"], "description": detail, "layer": layer.get("name", "Layer"), "x": 60 + (column + layer_index) * 330, "y": 110 + row * 145, "style": f"layer-{layer_index % 5}"})
    edges = []
    relationships = []
    for key in ("relationships", "connections"):
        if isinstance(payload.get(key), list):
            relationships.extend(payload[key])
    for relationship in relationships:
        if not isinstance(relationship, dict):
            continue
        source_id = _resolve_component_id(
            relationship.get("source") or relationship.get("from"),
            name_to_id,
        )
        target_id = _resolve_component_id(
            relationship.get("target") or relationship.get("to"),
            name_to_id,
        )
        if source_id and target_id and source_id != target_id:
            edges.append(
                {
                    "source": source_id,
                    "target": target_id,
                    "label": (
                        relationship.get("label")
                        or relationship.get("protocol")
                        or relationship.get("type")
                        or ""
                    ),
                }
            )
    return nodes, edges


def _artifact_graph(artifact: BRDDesignArtifact) -> tuple[list[dict], list[dict]]:
    payload = _json_load(artifact.payload_json, {})
    if not isinstance(payload, dict):
        return [], []
    if artifact.artifact_type == "business_flow":
        nodes = [node for node in payload.get("nodes", []) if isinstance(node, dict)]
        edges = [edge for edge in payload.get("edges", []) if isinstance(edge, dict)]
        positions = _flow_positions(nodes, edges)
        normalized = []
        for node in nodes:
            node_id = str(node.get("id", ""))
            x, y = positions.get(node_id, (60, 110))
            detail_parts = [node.get("description"), node.get("actor") or node.get("system")]
            normalized.append({**node, "id": node_id, "x": x, "y": y, "description": " | ".join(str(value) for value in detail_parts if value)})
        return normalized, edges
    return _architecture_graph(payload)


def _drawio_bytes(artifact: BRDDesignArtifact) -> bytes:
    nodes, edges = _artifact_graph(artifact)
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    ids = set()
    palette = {"external": ("FFF7ED", "FB923C"), "layer-0": ("F5F3FF", "8B5CF6"), "layer-1": ("EFF6FF", "3B82F6"), "layer-2": ("ECFEFF", "06B6D4"), "layer-3": ("F0FDF4", "22C55E"), "layer-4": ("F8FAFC", "64748B")}
    for index, node in enumerate(nodes):
        node_id = str(node.get("id") or f"node-{index}")
        ids.add(node_id)
        label = escape(str(node.get("label") or node_id))
        detail = escape(str(node.get("description") or ""))
        value = f"&lt;b&gt;{label}&lt;/b&gt;{'&#xa;' + detail if detail else ''}"
        fill, stroke = palette.get(str(node.get("style")), ("EFF6FF", "3B82F6"))
        shape = "rhombus;" if str(node.get("type", "")).lower() == "decision" else "rounded=1;arcSize=12;"
        dashed = "dashed=1;" if node.get("style") == "external" else ""
        cells.append(f'<mxCell id="{escape(node_id)}" value="{value}" style="{shape}{dashed}whiteSpace=wrap;html=1;fillColor=#{fill};strokeColor=#{stroke};fontColor=#0F172A;spacing=10;" vertex="1" parent="1"><mxGeometry x="{int(node.get("x", 60))}" y="{int(node.get("y", 110))}" width="250" height="105" as="geometry"/></mxCell>')
    for index, edge in enumerate(edges):
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if source in ids and target in ids:
            cells.append(f'<mxCell id="edge-{index}" value="{escape(str(edge.get("label", "")))}" style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;strokeColor=#64748B;" edge="1" parent="1" source="{escape(source)}" target="{escape(target)}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    xml = f'<mxfile host="app.diagrams.net"><diagram name="{escape(artifact.title)}"><mxGraphModel grid="1" gridSize="10"><root>{"".join(cells)}</root></mxGraphModel></diagram></mxfile>'
    return xml.encode("utf-8")


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    candidates = ["arialbd.ttf" if bold else "arial.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _arrow(draw, start: tuple[float, float], end: tuple[float, float], color: str = "#64748b") -> None:
    draw.line([start, end], fill=color, width=4)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 13
    draw.polygon(
        [
            end,
            (end[0] - size * math.cos(angle - math.pi / 6), end[1] - size * math.sin(angle - math.pi / 6)),
            (end[0] - size * math.cos(angle + math.pi / 6), end[1] - size * math.sin(angle + math.pi / 6)),
        ],
        fill=color,
    )


def _diagram_png(artifact: BRDDesignArtifact) -> bytes:
    from PIL import Image, ImageDraw

    nodes, edges = _artifact_graph(artifact)
    max_x = max((int(node.get("x", 0)) for node in nodes), default=900)
    max_y = max((int(node.get("y", 0)) for node in nodes), default=420)
    width, height = max(1400, max_x + 340), max(620, max_y + 210)
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    title_font, heading_font, body_font, small_font = _font(25, True), _font(17, True), _font(13), _font(11, True)
    draw.rounded_rectangle((28, 24, width - 28, 84), radius=14, fill="#0f172a")
    draw.text((52, 40), artifact.title, fill="white", font=title_font)
    by_id = {str(node.get("id")): node for node in nodes}
    for edge in edges:
        source, target = by_id.get(str(edge.get("source"))), by_id.get(str(edge.get("target")))
        if not source or not target:
            continue
        start = (int(source.get("x", 0)) + 250, int(source.get("y", 0)) + 52)
        end = (int(target.get("x", 0)), int(target.get("y", 0)) + 52)
        _arrow(draw, start, end)
        label = str(edge.get("label") or "")
        if label:
            draw.text(((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 - 18), label[:32], fill="#334155", font=small_font, anchor="mm")
    colors = [("#f5f3ff", "#8b5cf6"), ("#eff6ff", "#3b82f6"), ("#ecfeff", "#06b6d4"), ("#f0fdf4", "#22c55e"), ("#fff7ed", "#fb923c")]
    for index, node in enumerate(nodes):
        x, y = int(node.get("x", 60)), int(node.get("y", 110))
        fill, outline = colors[index % len(colors)]
        if node.get("style") == "external" or node.get("type") == "exception":
            fill, outline = "#fff7ed", "#fb923c"
        is_decision = str(node.get("type", "")).lower() == "decision"
        if is_decision:
            draw.polygon([(x + 125, y), (x + 250, y + 52), (x + 125, y + 104), (x, y + 52)], fill=fill, outline=outline, width=3)
        else:
            draw.rounded_rectangle((x, y, x + 250, y + 104), radius=12, fill=fill, outline=outline, width=3)
        label = str(node.get("label") or "Component")
        details = str(node.get("description") or "")
        if is_decision:
            draw.multiline_text((x + 125, y + 25), "\n".join(textwrap.wrap(label, 22)[:2]), fill="#0f172a", font=heading_font, anchor="ma", align="center", spacing=3)
        else:
            draw.multiline_text((x + 14, y + 13), "\n".join(textwrap.wrap(label, 31)[:2]), fill="#0f172a", font=heading_font, spacing=3)
            if details:
                draw.multiline_text((x + 14, y + 58), "\n".join(textwrap.wrap(details, 38)[:2]), fill="#475569", font=body_font, spacing=2)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _artifact_export(artifact: BRDDesignArtifact, export_format: str) -> tuple[bytes, str, str]:
    sections = _artifact_sections(artifact)
    safe_stem = "".join(char if char.isalnum() or char in "-_" else "_" for char in artifact.title).strip("_") or "architecture"
    if export_format in {"drawio", "io"}:
        return _drawio_bytes(artifact), "application/vnd.jgraph.mxfile", f"{safe_stem}.drawio"
    diagram_png = _diagram_png(artifact)
    if export_format == "png":
        return diagram_png, "image/png", f"{safe_stem}.png"
    if export_format == "pdf":
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Image as ReportImage, Paragraph, SimpleDocTemplate, Spacer

        output = io.BytesIO()
        styles = getSampleStyleSheet()
        page_size = landscape(A4)
        document = SimpleDocTemplate(output, pagesize=page_size, leftMargin=28, rightMargin=28, topMargin=28, bottomMargin=28)
        story = [Paragraph(escape(artifact.title), styles["Title"]), Spacer(1, 12)]
        diagram = ReportImage(io.BytesIO(diagram_png))
        scale = min((page_size[0] - 56) / diagram.imageWidth, (page_size[1] - 120) / diagram.imageHeight)
        diagram.drawWidth, diagram.drawHeight = diagram.imageWidth * scale, diagram.imageHeight * scale
        story.extend([diagram, Spacer(1, 16)])
        for heading, lines in sections:
            story.extend([Paragraph(escape(heading), styles["Heading2"]), Paragraph(escape(" • ".join(lines)), styles["BodyText"]), Spacer(1, 8)])
        document.build(story)
        return output.getvalue(), "application/pdf", f"{safe_stem}.pdf"
    if export_format == "docx":
        from docx import Document
        from docx.enum.section import WD_ORIENT
        from docx.shared import Inches

        document = Document()
        section = document.sections[0]
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
        document.add_heading(artifact.title, 0)
        document.add_picture(io.BytesIO(diagram_png), width=Inches(9.2))
        for heading, lines in sections:
            document.add_heading(heading, level=1)
            for line in lines:
                document.add_paragraph(line, style="List Bullet")
        output = io.BytesIO()
        document.save(output)
        return output.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"{safe_stem}.docx"
    raise HTTPException(status_code=422, detail="Export format must be pdf, docx, png, or drawio")


def _hydrate_document(document: BRDDocument, db: Session) -> BRDDocument:
    project = db.get(Project, document.project_id)
    setattr(document, "project_name", project.name if project else None)
    return document


def _hydrate_requirement(req: BRDRequirementSet) -> BRDRequirementSet:
    setattr(req, "functional", _json_load(req.functional_json, []))
    setattr(req, "non_functional", _json_load(req.non_functional_json, []))
    setattr(req, "assumptions", _json_load(req.assumptions_json, []))
    return req


def _hydrate_artifact(artifact: BRDDesignArtifact) -> BRDDesignArtifact:
    setattr(artifact, "payload", _json_load(artifact.payload_json, {}))
    return artifact


def _artifact_dict(artifact: BRDDesignArtifact) -> dict:
    hydrated = _hydrate_artifact(artifact)
    return jsonable_encoder({
        "id": hydrated.id,
        "project_id": hydrated.project_id,
        "document_id": hydrated.document_id,
        "artifact_type": hydrated.artifact_type,
        "version": hydrated.version,
        "title": hydrated.title,
        "payload": getattr(hydrated, "payload", {}),
        "ai_provider": hydrated.ai_provider,
        "model_used": hydrated.model_used,
        "created_by_id": hydrated.created_by_id,
        "created_at": hydrated.created_at,
    })


def _requirement_dict(req: BRDRequirementSet) -> dict:
    hydrated = _hydrate_requirement(req)
    return jsonable_encoder({
        "id": hydrated.id,
        "document_id": hydrated.document_id,
        "project_id": hydrated.project_id,
        "version": hydrated.version,
        "overview": hydrated.overview,
        "functional": getattr(hydrated, "functional", []),
        "non_functional": getattr(hydrated, "non_functional", []),
        "assumptions": getattr(hydrated, "assumptions", []),
        "created_by": hydrated.created_by,
        "created_at": hydrated.created_at,
    })


@router.get("/documents", response_model=list[BRDDocumentOut])
def list_documents(
    project_id: str | None = None,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> list[BRDDocument]:
    allowed_ids = visible_project_ids(db, actor)
    if project_id and project_id not in allowed_ids:
        raise HTTPException(status_code=404, detail="Project not found")
    if not allowed_ids:
        return []
    stmt = select(BRDDocument).where(BRDDocument.project_id.in_(allowed_ids)).order_by(BRDDocument.uploaded_at.desc())
    if project_id:
        stmt = stmt.where(BRDDocument.project_id == project_id)
    return [_hydrate_document(document, db) for document in db.scalars(stmt).all()]


@router.post("/documents/upload", response_model=BRDDocumentOut, status_code=201)
async def upload_document(
    project_id: str = Form(...),
    document_type: str = Form("brd"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> BRDDocument:
    project = db.get(Project, project_id)
    project = require_project_access(db, actor, project)
    require_project_manager(
        actor,
        project,
        db.get(Account, project.account_id),
    )

    settings = get_settings()
    storage_dir = resolve_app_path(
        str(settings.report_dir.parent / "brd" / project_id)
    )
    storage_dir.mkdir(parents=True, exist_ok=True)

    safe_filename = Path(file.filename or "uploaded-brd").name
    if not safe_filename.strip():
        raise HTTPException(
            status_code=422,
            detail="The selected BRD file does not have a valid filename.",
        )

    # Give the user a useful response instead of allowing the database
    # UNIQUE(project_id, filename) constraint to become an HTTP 500.
    existing_document = db.scalar(
        select(BRDDocument).where(
            BRDDocument.project_id == project_id,
            BRDDocument.filename == safe_filename,
        )
    )
    if existing_document:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A BRD document named '{safe_filename}' already exists "
                "for this project. Please rename the file before uploading it."
            ),
        )

    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="BRD file exceeds the 10 MB limit",
        )
    if not content:
        raise HTTPException(
            status_code=422,
            detail="The selected BRD file is empty.",
        )

    extracted_text = _extract_document_text(content, safe_filename)

    document = BRDDocument(
        project_id=project_id,
        filename=safe_filename,
        document_type=document_type,
        content_type=file.content_type,
        size_bytes=len(content),
        status=BRDDocumentStatus.READY,
        uploaded_by_id=actor.id,
        extracted_text=extracted_text,
    )
    db.add(document)

    try:
        # The database constraint remains the final protection against
        # simultaneous duplicate uploads.
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        error_text = str(exc)
        if "brd_documents.project_id" in error_text and "filename" in error_text:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"A BRD document named '{safe_filename}' already exists "
                    "for this project. Please rename the file before uploading it."
                ),
            ) from exc
        raise

    target = storage_dir / f"{document.id}_{document.filename}"
    try:
        target.write_bytes(content)
        document.storage_path = str(target)

        audit(
            db,
            actor.id,
            "BRD Uploaded",
            "BRD Studio",
            f"BRD {document.filename} uploaded for {project.name}",
        )
        db.commit()
        db.refresh(document)
    except Exception:
        db.rollback()
        try:
            if target.exists():
                target.unlink()
        except OSError:
            pass
        raise

    return _hydrate_document(document, db)


@router.get("/projects/{project_id}/requirements", response_model=list[RequirementOut])
def list_project_requirements(project_id: str, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> list[BRDRequirementSet]:
    require_project_access(db, actor, db.get(Project, project_id))
    reqs = db.scalars(
        select(BRDRequirementSet).where(BRDRequirementSet.project_id == project_id).order_by(BRDRequirementSet.created_at.desc())
    ).all()
    return [_hydrate_requirement(req) for req in reqs]


@router.post("/requirements", response_model=RequirementOut, status_code=201)
def save_requirements(
    payload: RequirementSave,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> BRDRequirementSet:
    document = db.get(BRDDocument, payload.document_id)
    if not document:
        raise HTTPException(status_code=404, detail="BRD document not found")
    if document.project_id != payload.project_id:
        raise HTTPException(status_code=422, detail="BRD document does not belong to the selected project")
    project = require_project_access(db, actor, db.get(Project, payload.project_id))
    require_project_manager(actor, project, db.get(Account, project.account_id))
    latest_version = db.scalar(
        select(func.max(BRDRequirementSet.version)).where(BRDRequirementSet.document_id == payload.document_id)
    ) or 0
    req = BRDRequirementSet(
        document_id=payload.document_id,
        project_id=payload.project_id,
        version=latest_version + 1,
        overview=payload.overview,
        functional_json=_json_dump(payload.functional),
        non_functional_json=_json_dump(payload.non_functional),
        assumptions_json=_json_dump(payload.assumptions),
        created_by=payload.created_by,
    )
    db.add(req)
    audit(db, actor.id, "Requirements Saved", "BRD Studio", f"Requirements saved for document {payload.document_id}")
    db.commit()
    db.refresh(req)
    return _hydrate_requirement(req)


@router.get("/projects/{project_id}/artifacts", response_model=list[BRDArtifactOut])
def list_artifacts(
    project_id: str,
    artifact_type: str | None = None,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> list[BRDDesignArtifact]:
    require_project_access(db, actor, db.get(Project, project_id))
    if artifact_type and artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise HTTPException(status_code=422, detail="Only business flow and architecture artifacts are supported")
    stmt = select(BRDDesignArtifact).where(
        BRDDesignArtifact.project_id == project_id,
        BRDDesignArtifact.artifact_type.in_(SUPPORTED_ARTIFACT_TYPES),
    ).order_by(BRDDesignArtifact.created_at.desc())
    if artifact_type:
        stmt = stmt.where(BRDDesignArtifact.artifact_type == artifact_type)
    return [_hydrate_artifact(artifact) for artifact in db.scalars(stmt).all()]


@router.get("/artifacts/{artifact_id}", response_model=BRDArtifactOut)
def get_artifact(artifact_id: str, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> BRDDesignArtifact:
    artifact = db.get(BRDDesignArtifact, artifact_id)
    if not artifact or artifact.artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise HTTPException(status_code=404, detail="Artifact not found")
    require_project_access(db, actor, db.get(Project, artifact.project_id))
    return _hydrate_artifact(artifact)


@router.get("/artifacts/{artifact_id}/export")
def export_artifact(
    artifact_id: str,
    format: str,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> Response:
    artifact = db.get(BRDDesignArtifact, artifact_id)
    if not artifact or artifact.artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise HTTPException(status_code=404, detail="Artifact not found")
    require_project_access(db, actor, db.get(Project, artifact.project_id))
    content, content_type, filename = _artifact_export(artifact, format.lower())
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/artifacts", response_model=BRDArtifactOut, status_code=201)
def create_artifact(
    payload: BRDArtifactCreate,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> BRDDesignArtifact:
    if payload.artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise HTTPException(status_code=422, detail="Only business flow and architecture artifacts are supported")
    project = require_project_access(db, actor, db.get(Project, payload.project_id))
    require_project_manager(actor, project, db.get(Account, project.account_id))
    _validate_diagram_payload(payload.artifact_type, payload.payload)
    if payload.document_id:
        document = db.get(BRDDocument, payload.document_id)
        if not document or document.project_id != payload.project_id:
            raise HTTPException(status_code=422, detail="BRD document does not belong to the selected project")
    latest_version = db.scalar(
        select(func.max(BRDDesignArtifact.version)).where(
            BRDDesignArtifact.project_id == payload.project_id,
            BRDDesignArtifact.artifact_type == payload.artifact_type,
        )
    ) or 0
    artifact = BRDDesignArtifact(
        project_id=payload.project_id,
        document_id=payload.document_id,
        artifact_type=payload.artifact_type,
        version=latest_version + 1,
        title=payload.title,
        payload_json=json.dumps(payload.payload, ensure_ascii=False),
        ai_provider=payload.ai_provider,
        model_used=payload.model_used,
        created_by_id=actor.id,
    )
    db.add(artifact)
    audit(db, actor.id, "BRD Artifact Saved", "BRD Studio", f"{payload.artifact_type} saved for project {payload.project_id}")
    db.commit()
    db.refresh(artifact)
    return _hydrate_artifact(artifact)


@router.get("/documents/{document_id}/artifacts/{artifact_type}/versions", response_model=list[BRDArtifactOut])
def list_artifact_versions(
    document_id: str,
    artifact_type: str,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> list[BRDDesignArtifact]:
    if artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise HTTPException(status_code=422, detail="Only business flow and architecture artifacts are supported")
    document = db.get(BRDDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="BRD document not found")
    require_project_access(db, actor, db.get(Project, document.project_id))
    artifacts = db.scalars(
        select(BRDDesignArtifact)
        .where(BRDDesignArtifact.document_id == document_id)
        .where(BRDDesignArtifact.artifact_type == artifact_type)
        .order_by(BRDDesignArtifact.version.desc())
    ).all()
    return [_hydrate_artifact(artifact) for artifact in artifacts]


@router.get("/documents/{document_id}/artifacts/{artifact_type}/compare", response_model=dict)
def compare_artifact_versions(
    document_id: str,
    artifact_type: str,
    v1: int,
    v2: int,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> dict:
    if artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise HTTPException(status_code=422, detail="Only business flow and architecture artifacts are supported")
    document = db.get(BRDDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="BRD document not found")
    require_project_access(db, actor, db.get(Project, document.project_id))
    rows = db.scalars(
        select(BRDDesignArtifact)
        .where(BRDDesignArtifact.document_id == document_id)
        .where(BRDDesignArtifact.artifact_type == artifact_type)
        .where(BRDDesignArtifact.version.in_([v1, v2]))
    ).all()
    by_version = {row.version: _json_load(row.payload_json, {}) for row in rows}
    if v1 not in by_version or v2 not in by_version:
        raise HTTPException(status_code=404, detail="One or both versions not found")
    left = json.dumps(by_version[v1], sort_keys=True, indent=2)
    right = json.dumps(by_version[v2], sort_keys=True, indent=2)
    return {
        "documentId": document_id,
        "artifactType": artifact_type,
        "v1": v1,
        "v2": v2,
        "same": left == right,
        "v1Size": len(left),
        "v2Size": len(right),
    }


@router.post("/documents/{document_id}/artifacts/{artifact_type}/restore/{version}", response_model=BRDArtifactOut)
def restore_artifact_version(
    document_id: str,
    artifact_type: str,
    version: int,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> BRDDesignArtifact:
    if artifact_type not in SUPPORTED_ARTIFACT_TYPES:
        raise HTTPException(status_code=422, detail="Only business flow and architecture artifacts are supported")
    target = db.scalar(
        select(BRDDesignArtifact)
        .where(BRDDesignArtifact.document_id == document_id)
        .where(BRDDesignArtifact.artifact_type == artifact_type)
        .where(BRDDesignArtifact.version == version)
    )
    if not target:
        raise HTTPException(status_code=404, detail="Version not found")
    project = require_project_access(db, actor, db.get(Project, target.project_id))
    require_project_manager(actor, project, db.get(Account, project.account_id))
    payload = _json_load(target.payload_json, {})
    restored_payload = BRDArtifactCreate(
        project_id=target.project_id,
        document_id=document_id,
        artifact_type=artifact_type,
        title=f"{target.title} Restored",
        payload=payload if isinstance(payload, dict) else {"payload": payload},
        ai_provider=target.ai_provider,
        model_used=target.model_used,
    )
    return create_artifact(restored_payload, db, actor)


@router.post("/generate", response_model=dict)
def generate_brd_asset(
    payload: BRDGenerateRequest,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> dict:
    project = db.get(Project, payload.project_id)
    project = require_project_access(db, actor, project)
    require_project_manager(actor, project, db.get(Account, project.account_id))
    if payload.artifact_type not in {"requirements", *SUPPORTED_ARTIFACT_TYPES}:
        raise HTTPException(status_code=422, detail="Unsupported BRD artifact type")
    document = db.get(BRDDocument, payload.document_id) if payload.document_id else None
    if document and document.project_id != project.id:
        raise HTTPException(status_code=422, detail="BRD document does not belong to the selected project")
    doc_text = (document.extracted_text if document else "") or payload.prompt or project.description or project.name

    latest_req = db.scalar(
        select(BRDRequirementSet).where(BRDRequirementSet.project_id == project.id).order_by(BRDRequirementSet.version.desc())
    )
    latest_requirements = _hydrate_requirement(latest_req) if latest_req else None
    req_payload = {
        "overview": getattr(latest_requirements, "overview", None) if latest_requirements else None,
        "functional": getattr(latest_requirements, "functional", []) if latest_requirements else [],
        "nonFunctional": getattr(latest_requirements, "non_functional", []) if latest_requirements else [],
        "assumptions": getattr(latest_requirements, "assumptions", []) if latest_requirements else [],
    }

    provider_used = "gemini"
    if payload.artifact_type == "requirements":
        result, model_used = _gemini_json(
            "Return only JSON with overview, functional, nonFunctional, assumptions. "
            "Extract requirements from the supplied BRD; do not invent project facts. "
            f"Project: {project.name}\nBRD:\n{doc_text[:16000]}",
            payload.model,
        )
        if document:
            saved = save_requirements(
                RequirementSave(
                    document_id=document.id,
                    project_id=project.id,
                    overview=result.get("overview"),
                    functional=result.get("functional", []),
                    non_functional=result.get("nonFunctional", result.get("non_functional", [])),
                    assumptions=result.get("assumptions", []),
                    created_by=provider_used,
                ),
                db,
                actor,
            )
            return {"status": "saved", "provider": provider_used, "model": model_used, "requirements": _requirement_dict(saved)}
        return {"status": "generated", "provider": provider_used, "model": model_used, "requirements": result}

    if payload.artifact_type == "business_flow":
        schema = (
            '{"nodes":[{"id":"stable-kebab-case-id","label":"concise step name","description":"specific business activity",'
            '"type":"start|process|decision|input|output|exception|end","actor":"business role or system",'
            '"system":"system name when explicit","inputs":["named input"],"outputs":["named output"],'
            '"business_rule":"rule only when supported","status":"stage when supported"}],'
            '"edges":[{"source":"node-id","target":"node-id","label":"condition or outcome",'
            '"kind":"normal|alternate|exception"}],'
            '"swimlanes":[{"name":"role or system","description":"responsibility"}],"outcome":"supported end result"}'
        )
        instructions = (
            "Act as a senior business process architect and enterprise process analyst.\n\n"
            "Create a detailed, end-to-end business process derived strictly from the supplied BRD, "
            "requirements and project context.\n\n"

            "PROCESS DEPTH:\n"
            "- Target 8-16 meaningful process nodes for a substantial BRD.\n"
            "- Include one explicit START node.\n"
            "- Include one or more INPUT nodes where business inputs enter the process.\n"
            "- Include detailed business activities rather than generic verbs.\n"
            "- Include DECISION nodes for meaningful business rules or approval points.\n"
            "- Include OUTPUT nodes where meaningful business outputs are produced.\n"
            "- Include EXCEPTION nodes for important failure, rejection, blocking or escalation scenarios supported by the BRD.\n"
            "- Include one or more END/OUTCOME nodes.\n\n"

            "ACTORS AND SYSTEMS:\n"
            "- Every meaningful process stage should identify the responsible actor or system where supported.\n"
            "- Show interactions between business users and systems.\n"
            "- Do not merge distinct actors into a generic 'User' when the BRD identifies specific roles.\n\n"

            "DECISIONS:\n"
            "- Decisions must use decision nodes.\n"
            "- Every decision must have at least two outgoing paths when the source supports them.\n"
            "- Decision edges must have meaningful labels such as Approved, Rejected, Valid, Invalid, "
            "Available, Unavailable, Yes or No.\n\n"

            "ALTERNATE AND EXCEPTION FLOWS:\n"
            "- Include rejection, validation failure, exception, escalation or retry paths when supported.\n"
            "- Do not create fictional business rules.\n\n"

            "TRACEABILITY:\n"
            "- Every node must represent something supported by the BRD or project requirements.\n"
            "- Every edge must represent an actual process transition.\n"
            "- Do not create decorative nodes or arrows.\n\n"

            "VISUAL STRUCTURE:\n"
            "- Organize the process logically as Entry → Activities → Decisions → Alternate Paths → Outcome.\n"
            "- Use swimlanes for distinct business roles or systems when supported.\n"
            "- Make the resulting structure suitable for an enterprise process presentation.\n\n"

            "Return only valid JSON matching the requested schema."
        )
    else:
        schema = (
            '{"title":"context-specific architecture title","objective":"business and technical objective",'
            '"layers":[{"name":"supported architectural layer","purpose":"specific responsibility",'
            '"securityBoundary":"boundary when supported","components":[{"name":"unique component name",'
            '"type":"experience|api|service|integration|messaging|ai|database|storage|infrastructure",'
            '"responsibility":"specific responsibility","technology":"technology only when supported"}]}],'
            '"external_systems":[{"name":"external system","type":"external","description":"integration purpose"}],'
            '"connections":[{"from":"exact component or external-system name","to":"exact component name",'
            '"label":"data flow","protocol":"protocol only when supported"}],'
            '"cross_cutting_concerns":{"Identity and access":["supported control"],"Observability":["supported capability"]},'
            '"deployment":["runtime or cloud detail"],"security":["specific control"],'
            '"decisions":[{"decision":"decision","rationale":"reason","trade_offs":"trade-off"}],'
            '"risks":[{"description":"risk","impact":"impact","mitigation":"mitigation"}],"so_what":"executive value"}'
        )
        instructions = (
            "Act as a senior enterprise solution architect and create a detailed, client-ready solution architecture "
    "directly from the supplied BRD, project description, and requirements.\n\n"

    "ARCHITECTURE DEPTH:\n"
    "- Create 5-8 logically ordered architectural layers when the source supports them.\n"
    "- Create 3-6 meaningful components per layer where supported.\n"
    "- Target approximately 15-30 total components for a substantial enterprise BRD.\n"
    "- Do not compress multiple distinct responsibilities into one generic component.\n"
    "- Do not produce a minimal 3-layer diagram merely because it satisfies the schema.\n\n"

    "LAYERS SHOULD BE SEMANTICALLY MEANINGFUL. Depending on the BRD, consider:\n"
    "- Users / Actors / Channels\n"
    "- Experience / Frontend\n"
    "- API / Gateway\n"
    "- Authentication / Authorization\n"
    "- Core Business Services\n"
    "- Workflow / Task / Process Services\n"
    "- Integration / Messaging\n"
    "- AI / Intelligence\n"
    "- Data / Database\n"
    "- Search / Vector / Knowledge\n"
    "- File / Object Storage\n"
    "- External Systems\n"
    "- Infrastructure / Deployment\n"
    "Only include layers actually supported by the source.\n\n"

    "COMPONENT DETAIL:\n"
    "Every component must have:\n"
    "- unique name\n"
    "- type\n"
    "- specific responsibility\n"
    "- technology only when supported by the BRD or project context\n"
    "Avoid generic labels such as 'Backend', 'Service', or 'Database' when the BRD identifies a more specific responsibility.\n\n"

    "RELATIONSHIPS:\n"
    "- Generate explicit component-to-component data flows.\n"
    "- Target at least 12 meaningful connections for a substantial architecture.\n"
    "- Every connection must have valid source and target names.\n"
    "- Describe what data, request, event, or control flows between the components.\n"
    "- Include important cross-layer relationships, not only relationships inside one layer.\n"
    "- Include external-system integrations when supported.\n"
    "- Do not create decorative or imaginary arrows.\n\n"

    "ARCHITECTURAL CONCERNS:\n"
    "Where supported by the BRD, explicitly represent:\n"
    "- authentication and authorization\n"
    "- RBAC\n"
    "- API gateway\n"
    "- business services\n"
    "- workflow/process orchestration\n"
    "- AI/LLM services\n"
    "- relational data\n"
    "- vector/search storage\n"
    "- document/file storage\n"
    "- notifications\n"
    "- external integrations\n"
    "- monitoring/observability\n"
    "- security boundaries\n"
    "- deployment/infrastructure\n\n"

    "QUALITY RULES:\n"
    "- The diagram must tell a complete technical story from user interaction to backend processing, "
    "business services, integrations, AI, persistence and external systems.\n"
    "- Prefer meaningful detail over large empty boxes.\n"
    "- Do not invent technologies, systems, vendors, APIs or business rules that are absent from the source.\n"
    "- Use the BRD as the source of truth.\n"
    "- Return only valid JSON matching the requested schema."
        )
    result, model_used = _gemini_json(
        f"Return only valid JSON matching this shape: {schema}\n{instructions}\n"
        f"Project: {project.name}\nDescription: {project.description or ''}\n"
        f"Requirements: {json.dumps(req_payload, ensure_ascii=False)[:12000]}\n"
        f"BRD source text: {doc_text[:16000]}\n"
        f"Additional prompt: {(payload.prompt or '')[:2000]}",
        payload.model,
    )
    result = _validate_diagram_payload(payload.artifact_type, result)
    created = create_artifact(
        BRDArtifactCreate(
            project_id=project.id,
            document_id=document.id if document else None,
            artifact_type=payload.artifact_type,
            title=f"{payload.artifact_type.replace('_', ' ').title()} Generated",
            payload=result,
            ai_provider=provider_used,
            model_used=model_used,
        ),
        db,
        actor,
    )
    return {"status": "saved", "provider": provider_used, "model": model_used, "artifact": _artifact_dict(created)}
