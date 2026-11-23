"""Genera ``data/demand_profile_24h.csv`` a partir de la Tabla 1 oficial."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.domain.models import DemandProfile  # noqa: E402

DEMAND_CSV = ROOT / "data" / "demand_profile_24h.csv"


def write_demand_csv(path: Path = DEMAND_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    DemandProfile.default().to_dataframe().to_csv(path, index=False)
    return path


if __name__ == "__main__":
    out = write_demand_csv()
    print(f"Perfil de demanda escrito en {out}")
