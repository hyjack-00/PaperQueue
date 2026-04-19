from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_queue.config import Settings
from paper_queue.runtime import Runtime
from paper_queue.workflow import PaperWorkflow


REGRESSION_FILE = ROOT / "benchmarks" / "metadata_regression.json"
OUTPUT_FILE = ROOT / "benchmarks" / "metadata_regression.latest.json"


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def main() -> int:
    cases = json.loads(REGRESSION_FILE.read_text(encoding="utf-8"))
    runtime = Runtime(Settings())
    workflow = PaperWorkflow(runtime)
    results: list[dict] = []
    all_passed = True

    for idx, case in enumerate(cases, start=1):
        artifact_dir = ROOT / "var" / "job_artifacts" / f"metadata-regression-{idx:02d}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        initial = dict(case["initial_metadata"])
        initial["paper_url"] = case["paper_url"]
        initial["metadata_answer"] = initial.get("metadata_answer", "")
        job = {
            "id": 98000 + idx,
            "input_text": case["paper_url"],
            "artifact_dir": str(artifact_dir),
            "paper_title": initial.get("paper_title", ""),
            "notebook_title": "",
            "notebook_id": "",
        }
        recovered = workflow._fallback_metadata(
            job,
            {"paper_url": case["paper_url"], "source_title": initial.get("paper_title", ""), "source_id": ""},
            dict(initial),
            lambda *_args: None,
        )
        validation_error = ""
        try:
            recovered = workflow._validate_metadata(dict(recovered))
        except Exception as exc:  # pragma: no cover - regression script
            validation_error = str(exc)
            all_passed = False

        expected = case["expected"]
        checks = {
            "title_exact": recovered.get("paper_title", "") == expected["title"],
            "venue_exact": recovered.get("conference", "") == expected["venue"],
            "authors_present": bool(recovered.get("authors")),
            "authors_keywords": _contains_any(recovered.get("authors", ""), expected.get("author_keywords", [])),
            "institution_present": bool(recovered.get("university")),
            "institution_keywords": _contains_any(recovered.get("university", ""), expected.get("institution_keywords", [])),
            "validated": not validation_error,
        }
        passed = all(checks.values())
        if not passed:
            all_passed = False
        results.append(
            {
                "name": case["name"],
                "paper_url": case["paper_url"],
                "recovered": {k: recovered.get(k, "") for k in ["paper_title", "conference", "year", "authors", "university", "paper_url"]},
                "checks": checks,
                "passed": passed,
                "validation_error": validation_error,
            }
        )

    summary = {
        "all_passed": all_passed,
        "passed_count": sum(1 for item in results if item["passed"]),
        "total_count": len(results),
        "results": results,
    }
    OUTPUT_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
