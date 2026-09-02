"""Run and translate the backend's real pytest/Coverage.py results for the dashboard."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COVERAGE_DIR = ROOT / "coverage"
JSON_REPORT = COVERAGE_DIR / "coverage.json"
JUNIT_REPORT = COVERAGE_DIR / "junit.xml"
HTML_REPORT = COVERAGE_DIR / "html"
LCOV_REPORT = COVERAGE_DIR / "lcov.info"
HISTORY_FILE = COVERAGE_DIR / "history.json"
THRESHOLDS = {"statements": 80, "branches": 75, "functions": 80, "lines": 80}
_run_lock = threading.Lock()


def _pct(covered: int, total: int) -> float | None:
    return round(covered * 100 / total, 1) if total else None


def _status(value: float | None, threshold: int) -> str:
    if value is None:
        return "Not available"
    if value >= threshold:
        return "Healthy"
    if value >= threshold - 15:
        return "Needs Attention"
    return "Critical"


def _test_statistics() -> dict:
    if not JUNIT_REPORT.exists():
        return {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "suites": 0, "duration": 0}
    root = ET.parse(JUNIT_REPORT).getroot()
    suites = list(root.iter("testsuite"))
    cases = list(root.iter("testcase"))
    failed = sum(1 for case in cases if case.find("failure") is not None or case.find("error") is not None)
    skipped = sum(1 for case in cases if case.find("skipped") is not None)
    return {
        "total": len(cases), "passed": len(cases) - failed - skipped, "failed": failed,
        "skipped": skipped, "suites": len(suites),
        "duration": round(sum(float(suite.get("time", 0)) for suite in suites), 2),
    }


def _function_metric(files: dict) -> float | None:
    """Coverage.py exposes per-function executed lines; calculate entered functions from it."""
    covered = total = 0
    for file_data in files.values():
        for name, function in file_data.get("functions", {}).items():
            if not name or not function["summary"].get("num_statements"):
                continue
            total += 1
            if function.get("executed_lines"):
                covered += 1
    return _pct(covered, total)


def _coverage_payload() -> dict:
    if not JSON_REPORT.exists():
        return {"available": False, "message": "No coverage analysis has been run yet.", "thresholds": THRESHOLDS, "history": []}
    report = json.loads(JSON_REPORT.read_text(encoding="utf-8"))
    files = report.get("files", {})
    totals = report.get("totals", {})
    statements = _pct(totals.get("covered_lines", 0), totals.get("num_statements", 0))
    lines = statements
    branches = _pct(totals.get("covered_branches", 0), totals.get("num_branches", 0)) if totals.get("num_branches") else None
    functions = _function_metric(files)
    metrics = {"statements": statements, "branches": branches, "functions": functions, "lines": lines}
    folders: dict[str, dict[str, int]] = defaultdict(lambda: {"covered": 0, "total": 0})
    file_rows = []
    for filename, data in files.items():
        summary = data.get("summary", {})
        total = summary.get("num_statements", 0)
        covered = summary.get("covered_lines", 0)
        if not total:
            continue
        folder = str(Path(filename).parent).replace("\\", "/") or "app"
        folders[folder]["covered"] += covered
        folders[folder]["total"] += total
        file_rows.append({"file": filename.replace("\\", "/"), "coverage": _pct(covered, total)})
    modules = [
        {"module": name, "coverage": _pct(item["covered"], item["total"]), "status": _status(_pct(item["covered"], item["total"]), THRESHOLDS["statements"])}
        for name, item in sorted(folders.items())
    ]
    low_areas = [
        {"file": item["file"], "coverage": item["coverage"], "status": _status(item["coverage"], THRESHOLDS["statements"])}
        for item in sorted(file_rows, key=lambda item: item["coverage"] if item["coverage"] is not None else -1)
        if item["coverage"] is not None and item["coverage"] < THRESHOLDS["statements"]
    ]
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    timestamp = datetime.fromtimestamp(JSON_REPORT.stat().st_mtime, timezone.utc).isoformat()
    return {
        "available": True, "metrics": metrics,
        "overall": statements, "overall_status": _status(statements, THRESHOLDS["statements"]),
        "thresholds": THRESHOLDS, "test_statistics": _test_statistics(),
        "test_status": "Failed" if _test_statistics()["failed"] else ("Passed" if _test_statistics()["total"] else "Not run"), "modules": modules,
        "low_areas": low_areas, "last_analyzed": timestamp, "history": history,
        "reports": {"html": HTML_REPORT.joinpath("index.html").exists(), "lcov": LCOV_REPORT.exists()},
    }


def get_coverage() -> dict:
    return _coverage_payload()


def run_coverage() -> dict:
    if not _run_lock.acquire(blocking=False):
        raise RuntimeError("A coverage analysis is already running.")
    try:
        COVERAGE_DIR.mkdir(exist_ok=True)
        commands = [
            [sys.executable, "-m", "coverage", "erase"],
            [sys.executable, "-m", "coverage", "run", "--rcfile=.coveragerc", "-m", "pytest", "tests", f"--junitxml={JUNIT_REPORT}"],
            [sys.executable, "-m", "coverage", "json", "-o", str(JSON_REPORT)],
            [sys.executable, "-m", "coverage", "html", "-d", str(HTML_REPORT)],
            [sys.executable, "-m", "coverage", "lcov", "-o", str(LCOV_REPORT)],
        ]
        test_result = subprocess.run(commands[0], cwd=ROOT, capture_output=True, text=True)
        if test_result.returncode:
            raise RuntimeError(test_result.stderr or test_result.stdout)
        test_result = subprocess.run(commands[1], cwd=ROOT, capture_output=True, text=True)
        for command in commands[2:]:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr or result.stdout)
        payload = _coverage_payload()
        payload["test_status"] = "Passed" if test_result.returncode == 0 else "Failed"
        snapshot = {"timestamp": payload["last_analyzed"], "overall": payload["overall"]}
        history = payload["history"]
        if not history or history[-1] != snapshot:
            history = (history + [snapshot])[-30:]
            HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")
        payload["history"] = history
        return payload
    finally:
        _run_lock.release()
