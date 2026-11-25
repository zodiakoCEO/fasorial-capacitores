"""La auditoría independiente (sin src/) debe coincidir con el solucionador del proyecto."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from scripts import auditoria_independiente as audit
from src.domain.constants import DEMAND_TABLE, QC_FIXED_ECONOMIC_KVAR
from src.domain.models import DemandProfile
from src.optimization.capacitor_optimizer import fixed_economic_optimum
from src.optimization.pipeline import run_full_analysis
from src.physics.circuit_solver import solve_problem2
from src.reporting.analysis_text import problem1_analysis, problem2_analysis
from src.reporting.presentation_export import export_tables


def test_audit_does_not_import_src() -> None:
    tree = ast.parse(Path(audit.__file__).read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m and m.split(".")[0] in {"src", "numpy", "scipy", "pandas"} for m in modules)
    assert audit.QC_AUDITED == QC_FIXED_ECONOMIC_KVAR
    assert tuple(tuple(float(x) for x in row) for row in audit.TABLE) == tuple(
        tuple(float(x) for x in row) for row in DEMAND_TABLE
    )


@pytest.mark.parametrize("q_c", [0.0, QC_FIXED_ECONOMIC_KVAR])
def test_audit_matches_solver(q_c: float) -> None:
    hours = audit.solve_day(q_c)
    r = solve_problem2(DemandProfile.default(), q_c)
    np.testing.assert_allclose([h.v_gen for h in hours], r.v_gen, rtol=1e-12)
    np.testing.assert_allclose([h.i_line for h in hours], r.i_line, rtol=1e-12)
    np.testing.assert_allclose([h.i_gen for h in hours], r.i_gen, rtol=1e-12)
    np.testing.assert_allclose([h.p_loss_kw for h in hours], r.p_loss_kw, rtol=1e-12)
    np.testing.assert_allclose([h.pf_net for h in hours], r.pf_net, rtol=1e-12)
    np.testing.assert_allclose([h.s_gen_kva for h in hours], r.s_gen_kva, rtol=1e-12)
    assert max(h.balance_error for h in hours) < 1e-12
    assert max(h.path_error for h in hours) < 1e-12


def test_audit_report_passes_and_matches_csv(tmp_path: Path) -> None:
    export_tables(run_full_analysis(include_sensitivity=False), tmp_path)
    rep = audit.run_audit(QC_FIXED_ECONOMIC_KVAR, tmp_path)
    assert rep.ok, [c for c in rep.checks if not c[1]]
    assert len(rep.checks) == 12  # incluye el contraste con los dos CSV horarios
    files = audit.write_outputs(rep, tmp_path)
    assert all(f.exists() and f.stat().st_size > 0 for f in files)
    eco = fixed_economic_optimum(DemandProfile.default()).result.economics
    assert audit.annual_cost(QC_FIXED_ECONOMIC_KVAR) == pytest.approx(eco.total_annual_cost_cop, rel=1e-12)
    assert audit.daily_loss_kwh(QC_FIXED_ECONOMIC_KVAR) == pytest.approx(eco.daily_loss_kwh, rel=1e-12)
    assert audit.hours_in_band(QC_FIXED_ECONOMIC_KVAR) == 23


def test_analysis_text_uses_computed_values() -> None:
    b = run_full_analysis(include_sensitivity=False)
    assert len(problem1_analysis(b)) == 5
    sections = problem2_analysis(b)
    assert list(sections) == ["Tensión del generador |Vgen(t)|", "Corriente de línea |Iline(t)|", "Pérdidas Ploss(t)"]
    text = " ".join(line for lines in sections.values() for line in lines)
    for token in ("378.35 kvar", "23 de 24 horas", "Hora 8, fuera de banda", "838.84 V", "26.587 A", "2,233.73 kWh"):
        assert token in text, token
