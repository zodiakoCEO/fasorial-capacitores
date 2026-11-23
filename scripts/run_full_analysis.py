"""Ejecuta el análisis completo y exporta todos los entregables a ``outputs/``.

Uso:
    python scripts/run_full_analysis.py [--step 25] [--out outputs]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.diagnostics import print_report  # noqa: E402
from scripts.generate_demand_csv import DEMAND_CSV, write_demand_csv  # noqa: E402
from src.domain.models import DemandProfile  # noqa: E402
from src.optimization.pipeline import run_full_analysis  # noqa: E402
from src.reporting.presentation_export import export_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", type=float, default=25.0, help="Tamaño del paso del banco automático [kvar]")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs", help="Carpeta de salida")
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    if not DEMAND_CSV.exists():
        write_demand_csv()
    demand = DemandProfile.from_csv(DEMAND_CSV)
    bundle = run_full_analysis(demand, switched_step_kvar=args.step)
    print_report(bundle)
    files = export_all(bundle, args.out)
    print("\n" + "=" * 100)
    print(f"  Entregables exportados en {args.out}  ({time.perf_counter() - t0:.1f} s)")
    for kind, paths in files.items():
        print(f"  - {kind}: {len(paths)} archivo(s)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    raise SystemExit(main())
