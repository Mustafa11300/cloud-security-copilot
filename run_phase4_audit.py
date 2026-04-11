"""
Phase 4 Validation Runner — executes all 5 scenarios and writes the full
Temporal Audit Report to phase4_temporal_audit_report.txt.

Run:  venv\Scripts\python.exe run_phase4_audit.py
"""
import sys
import asyncio
import traceback

sys.path.insert(0, ".")

# ── Syntax checks ─────────────────────────────────────────────────────────────
RESULTS = []

def _check_import(module_path: str) -> bool:
    try:
        parts = module_path.split(".")
        mod = __import__(module_path, fromlist=[parts[-1]])
        RESULTS.append(f"  IMPORT OK  {module_path}")
        return True
    except Exception as e:
        RESULTS.append(f"  IMPORT ERR {module_path}: {e}\n{traceback.format_exc()}")
        return False

_check_import("cloudguard.forecaster.threat_forecaster")
_check_import("cloudguard.forecaster.dissipation_handler")
_check_import("cloudguard.forecaster.validation_queue")
_check_import("cloudguard.api.narrative_engine")
_check_import("tests.test_phase4_validation_suite")

# ── Report import diagnostics ─────────────────────────────────────────────────
diag_path = "phase4_import_diag.txt"
with open(diag_path, "w", encoding="utf-8") as f:
    f.write("=== Phase 4 Import Diagnostics ===\n")
    f.write(f"Python: {sys.version}\n")
    f.write(f"sys.path: {sys.path[:4]}\n\n")
    for r in RESULTS:
        f.write(r + "\n")
    f.write("\n=== END ===\n")

print(f"Diagnostics written to {diag_path}")

# ── Run the actual suite ──────────────────────────────────────────────────────
if all("IMPORT OK" in r for r in RESULTS):
    from tests.test_phase4_validation_suite import _run_all_scenarios, _REPORT_LINES
    try:
        asyncio.run(_run_all_scenarios())
        # Write report
        with open("phase4_temporal_audit_report.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(_REPORT_LINES))
        print(f"Report written: phase4_temporal_audit_report.txt ({len(_REPORT_LINES)} lines)")
    except Exception as e:
        with open("phase4_temporal_audit_report.txt", "w", encoding="utf-8") as f:
            f.write(f"FATAL ERROR: {e}\n{traceback.format_exc()}")
        print(f"Suite failed: {e}")
else:
    print("Import errors found — see phase4_import_diag.txt")
