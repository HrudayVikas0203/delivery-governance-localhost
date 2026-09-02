from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.delivery import Account, Project, ResourceAllocation
from app.models.people import Employee
from app.models.status import WeeklyStatus
from app.rag.store import search_knowledge
from app.schemas.common import LLMSelection, RagQueryIn, RagQueryOut
from app.services.access import visible_account_ids, visible_project_ids
from app.services.llm import generate_text


def _build_static_knowledge() -> str:
    return """
Platform purpose: Delivery Governance Platform for delivery teams to manage accounts, programs, projects, staffing, status, governance, and reports.
Roles and hierarchy: Studio Head > Program Director / Program Manager > Project Manager > Developers / Resources.
Modules: Account governance, project management, resource allocation, task tracker, weekly/daily/monthly status, reports, BRD Studio, architecture, business flow, AI insights.
Security: Users can only see data within their authorized scope. Never reveal unrestricted account or project data.
PPT workflow: Accounts have templates, project status feeds into report generation, and PPT output is created from account-specific templates.
AI: Gemini powers BRD generation and reporting; Groq powers the shared governance chatbot.
"""


def _build_dynamic_context(db: Session, actor: Employee, project_id: str | None) -> tuple[str, list[dict]]:
    project_ids = visible_project_ids(db, actor)
    account_ids = visible_account_ids(db, actor)
    sources: list[dict] = []
    lines: list[str] = [
        f"User: {actor.name}",
        f"Role: {actor.role.value}",
        f"Visible accounts: {len(account_ids)}",
        f"Visible projects: {len(project_ids)}",
    ]

    if account_ids:
        accounts = db.scalars(select(Account).where(Account.id.in_(sorted(account_ids))).order_by(Account.name)).all()
        lines.append("Accounts:")
        for account in accounts[:10]:
            lines.append(f"- {account.name} (program_manager_id={account.program_manager_id}, health={account.health.value if hasattr(account.health, 'value') else account.health})")
    if project_ids:
        projects = db.scalars(select(Project).where(Project.id.in_(sorted(project_ids))).order_by(Project.name)).all()
        lines.append("Projects:")
        for project in projects[:12]:
            lines.append(f"- {project.name} (account_id={project.account_id}, project_manager_id={project.project_manager_id}, phase={project.phase.value if hasattr(project.phase, 'value') else project.phase})")

    allocations = db.scalars(
        select(ResourceAllocation).where(
            ResourceAllocation.is_active.is_(True),
            ResourceAllocation.employee_id == actor.id,
        )
    ).all()
    if allocations:
        lines.append("My allocations:")
        for allocation in allocations[:10]:
            lines.append(f"- {allocation.project_id} as {allocation.allocation_role.value} ({allocation.allocation_percent}%)")

    if project_id and project_id in project_ids:
        statuses = db.scalars(select(WeeklyStatus).where(WeeklyStatus.project_id == project_id).order_by(WeeklyStatus.week_start.desc()).limit(10)).all()
        lines.append("Recent project status:")
        for status in statuses:
            lines.append(f"- {status.week_start}: {status.status.value} | {status.fields}")

    if project_ids:
        knowledge_sources = search_knowledge("governance status project risk", top_k=6, project_id=project_id, allowed_project_ids=project_ids)
        for source in knowledge_sources:
            sources.append(source)
    return "\n".join(lines), sources


def answer_with_rag(payload: RagQueryIn, actor: Employee, db: Session) -> RagQueryOut:
    project_ids = visible_project_ids(db, actor)
    if payload.project_id and payload.project_id not in project_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if payload.llm and payload.llm.provider != "groq":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The platform RAG chatbot uses Groq only")

    static_context = _build_static_knowledge()
    dynamic_context, sources = _build_dynamic_context(db, actor, payload.project_id)
    rag_sources = search_knowledge(payload.question, payload.top_k, payload.project_id, project_ids if project_ids else set()) if project_ids else []
    context = "\n\n---\n\n".join(source["document"] for source in rag_sources)
    context_text = "\n\n---\n\n".join(filter(None, [static_context, dynamic_context, context]))

    llm = payload.llm or LLMSelection(provider="groq", model=get_settings().groq_default_model)
    prompt = f"""
You are a senior delivery governance analyst for an IT services organization.
Answer using only the supplied governance context. Be concise, factual, client-safe,
and call out delivery risks, blockers, ownership, and next actions when relevant.

Context:
{context_text}

Question:
{payload.question}
"""
    answer, model = generate_text("groq", prompt, llm.model)
    final_sources = rag_sources or sources
    return RagQueryOut(answer=answer, provider="groq", model=model, sources=final_sources)
