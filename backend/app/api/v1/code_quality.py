from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.core.security import require_min_role
from app.models.people import Employee, Role
from app.services import code_quality

router = APIRouter(prefix="/code-quality", tags=["code-quality"])


@router.get("/coverage")
def coverage(_: Employee = Depends(require_min_role(Role.PROJECT_MANAGER))) -> dict:
    return code_quality.get_coverage()


@router.post("/coverage/refresh")
def refresh_coverage(_: Employee = Depends(require_min_role(Role.PROJECT_MANAGER))) -> dict:
    try:
        return code_quality.run_coverage()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/coverage/report/{report_type}")
def download_coverage_report(report_type: str, _: Employee = Depends(require_min_role(Role.PROJECT_MANAGER))):
    reports = {"html": code_quality.HTML_REPORT / "index.html", "lcov": code_quality.LCOV_REPORT}
    report = reports.get(report_type)
    if report is None or not report.exists():
        raise HTTPException(status_code=404, detail="Coverage report is not available")
    return FileResponse(report, filename=report.name, media_type="text/html" if report_type == "html" else "text/plain")
