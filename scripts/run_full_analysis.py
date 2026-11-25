"""Ejecuta el análisis completo y exporta todos los entregables a ``outputs/``.

Uso:
    python scripts/run_full_analysis.py [--out outputs]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.auditoria_independiente import NET_P2, NET_P21, run_audit, write_outputs  # noqa: E402
from scripts.diagnostics import print_report, print_report_21  # noqa: E402
from scripts.generate_demand_csv import DEMAND_CSV, write_demand_csv  # noqa: E402
from src.domain.models import DemandProfile  # noqa: E402
from src.optimization.pipeline import run_full_analysis, run_problem_2_1  # noqa: E402
from src.reporting.presentation_export import export_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs", help="Carpeta de salida")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    if not DEMAND_CSV.exists():
        write_demand_csv()
    demand = DemandProfile.from_csv(DEMAND_CSV)
    bundle = run_full_analysis(demand)
    bundle_21 = run_problem_2_1(demand)  # misma red con T1 = 1 kV : 66 kV y T2 = 66 kV : 120 V
    print_report(bundle)
    print_report_21(bundle_21, bundle)
    files = export_all(bundle, args.out, bundle_21)
    # Auditoría independiente (no usa src/): se ejecuta después de exportar para contrastar los CSV.
    audits = [
        run_audit(bundle.economic.q_c_design_kvar, args.out, NET_P2),
        run_audit(bundle_21.economic.q_c_design_kvar, args.out, NET_P21),
    ]
    files["audit"] = [path for rep in audits for path in write_outputs(rep, args.out)]
    for rep in audits:
        print()
        print(rep.text)
    print("\n" + "=" * 100)
    print(f"  Entregables exportados en {args.out}  ({time.perf_counter() - t0:.1f} s)")
    for kind, paths in files.items():
        print(f"  - {kind}: {len(paths)} archivo(s)")
    return 0 if all(rep.ok for rep in audits) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    raise SystemExit(main())
