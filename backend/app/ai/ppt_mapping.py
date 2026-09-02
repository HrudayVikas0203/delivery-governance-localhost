import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.ai.gemini_response import GeminiResponseError, parse_gemini_json
from app.ai.template_analysis import TemplateStructure, analyze_template
from app.core.config import get_settings
from app.models.delivery import Account, Project
from app.models.people import Employee
from app.models.status import WeeklyStatus


ReportField = Literal[
    "ACCOUNT_NAME",
    "PROJECT_NAME",
    "REPORT_DATE",
    "OVERALL_STATUS",
    "COMPLETION",
    "HOURS",
    "EXECUTIVE_SUMMARY",
    "ACHIEVEMENTS",
    "BLOCKERS",
    "RISKS",
    "NEXT_WEEK_PLAN",
    "NEXT_STEPS",
    "PROJECT_METRICS",
]


class GeminiMappingConfigurationError(RuntimeError):
    pass


class GeminiMappingError(RuntimeError):
    pass


class GeminiMappingValidationError(GeminiMappingError):
    pass


class SlideMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_index: int = Field(ge=0)
    mapped_content: dict[str, str] = Field(default_factory=dict)


class PPTMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slides: list[SlideMapping] = Field(min_length=1)


def normalize_status_data(
    db: Session,
    projects: list[Project],
    statuses: list[WeeklyStatus],
    report_metadata: dict | None = None,
) -> dict:
    account_ids = {project.account_id for project in projects}
    accounts = [db.get(Account, account_id) for account_id in account_ids]
    employees = []
    weekly_statuses = []
    for status in statuses:
        employee = db.get(Employee, status.employee_id)
        project = db.get(Project, status.project_id) if status.project_id else None
        employees.append({"id": status.employee_id, "name": employee.name if employee else None, "project_id": status.project_id})
        weekly_statuses.append({"employee": employee.name if employee else None, "project": project.name if project else status.fields.get("project"), "week_start": status.week_start.isoformat(), "status": status.status.value, "fields": {key: value for key, value in status.fields.items() if key in {"overallStatus", "completionPercent", "hoursWorked", "achievements", "blockers", "risks", "nextWeekPlan", "supportRequired", "reportingFrequency", "frequency"}}})
    return {
        "report": report_metadata or {},
        "account": {"id": next(iter(account_ids), None), "name": accounts[0].name if accounts and accounts[0] else None},
        "projects": [{"id": project.id, "name": project.name, "phase": project.phase.value, "health": project.health.value, "risk": project.risk.value, "completion_percent": project.completion_percent} for project in projects],
        "reporting_period": {"status_count": len(statuses), "start": min((row.week_start for row in statuses), default=date.today()).isoformat(), "end": max((row.week_start for row in statuses), default=date.today()).isoformat()},
        "employees": employees,
        "weekly_statuses": weekly_statuses,
    }


def mapping_prompt(template: TemplateStructure, status_data: dict) -> str:
    return """You are an expert delivery governance PowerPoint AI agent. Your task is to map the AVAILABLE REPORT DATA into the uploaded template. 
Return only structured JSON of the form {"slides":[{"slide_index":0,"mapped_content":{"slide_0_shape_0":"Optimized and aligned content for this shape"}}]}

STRICT RULES:
1. For each writable element id from the TEMPLATE STRUCTURE that should be populated with report data, generate the final, optimized, and aligned content string.
2. DO NOT REPEAT bullet points or sentences. If you run out of unique updates, leave the rest of the space blank. Repetition is strictly forbidden.
3. Respect the 'char_limit_estimate' provided for each element in the template structure. Do not exceed this limit.
4. Optimize and align the content as required for a premium, executive-ready presentation. 
5. Do not invent facts, dates, or names. Do not redesign the template or add slides.
6. Summarize content logically (e.g. group by themes) to fit the space if there is too much data.

TEMPLATE STRUCTURE:
""" + template.model_dump_json() + "\n\nAVAILABLE REPORT DATA:\n" + json.dumps(status_data, default=str)


def map_with_gemini(template: TemplateStructure, status_data: dict) -> PPTMapping:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise GeminiMappingConfigurationError("Gemini PPT mapping is not configured.")
    model_name = (settings.gemini_default_model or "").strip()
    if not model_name:
        raise GeminiMappingConfigurationError("Gemini PPT mapping model is not configured.")
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=25_000),
    )
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=mapping_prompt(template, status_data),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
    except Exception as exc:
        raise GeminiMappingError("Gemini PPT mapping failed.") from exc

    try:
        parsed = getattr(response, "parsed", None)
        mapping = parsed if isinstance(parsed, PPTMapping) else PPTMapping.model_validate(parsed or parse_gemini_json(response))
    except (GeminiResponseError, ValidationError, ValueError, json.JSONDecodeError) as exc:
        raise GeminiMappingValidationError("Gemini returned an invalid PPT mapping response.") from exc
    if not any(slide.mapped_content for slide in mapping.slides):
        raise GeminiMappingValidationError("Gemini returned an empty PPT mapping.")
    return mapping


def map_template(
    path: str | Path,
    db: Session,
    projects: list[Project],
    statuses: list[WeeklyStatus],
    report_metadata: dict | None = None,
) -> tuple[TemplateStructure, PPTMapping]:
    template = analyze_template(path)
    mapping = map_with_gemini(template, normalize_status_data(db, projects, statuses, report_metadata))
    writable_elements = {
        element.id: (slide.slide_index, element.type)
        for slide in template.slides
        for element in slide.elements
        if element.type in {"shape", "placeholder", "table_cell"}
    }
    for slide in mapping.slides:
        if slide.slide_index >= template.slide_count:
            raise GeminiMappingValidationError("Gemini mapping referenced a slide outside the uploaded template.")
        for element_id, content in slide.mapped_content.items():
            target = writable_elements.get(element_id)
            if target is None or target[0] != slide.slide_index:
                raise GeminiMappingValidationError("Gemini mapping referenced an invalid template element.")
            if not content:
                raise GeminiMappingValidationError("Gemini mapping contains an empty element assignment.")
    return template, mapping
