"""Problema 2.1: misma red con T1 = 1 kV : 66 kV y T2 = 66 kV : 120 V, y comparación con el Problema 2."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import auditoria_independiente as audit
from src.domain.constants import LINE_VOLTAGE_2_1_V, QC_FIXED_ECONOMIC_2_1_KVAR, QC_FIXED_ECONOMIC_KVAR
from src.domain.models import DemandProfile, NetworkParameters, Strategy
from src.optimization.capacitor_optimizer import Interval, feasibility_analysis
from src.optimization.comparison import (
    RATIO_COLUMN,
    case_metrics,
    comparison_table,
    comparison_value,
    format_comparison,
)
from src.optimization.pipeline import CASE_2, CASE_2_1, params_2_1, run_full_analysis, run_problem_2_1
from src.physics.circuit_solver import affine_voltage_model, daily_loss_quadratic, solve_problem2
from src.physics.step_by_step import hourly_step_table, power_balance_error
from src.reporting import charts as CH
from src.reporting.analysis_text import comparison_synthesis, problem21_analysis
from src.reporting.presentation_export import (
    build_markdown_report,
    chart_catalog_21,
    export_tables,
    export_tables_21,
)


@pytest.fixture(scope="module")
def demand() -> DemandProfile:
    return DemandProfile.default()


@pytest.fixture(scope="module")
def p2() -> NetworkParameters:
    return NetworkParameters()


@pytest.fixture(scope="module")
def p21() -> NetworkParameters:
    return params_2_1()


@pytest.fixture(scope="module")
def b2(demand):
    return run_full_analysis(demand, include_sensitivity=False)


@pytest.fixture(scope="module")
def b21(demand):
    return run_problem_2_1(demand)


# ----------------------------------------------------------------------------------
# Relaciones de transformación a 66 kV y reflejo de magnitudes
# ----------------------------------------------------------------------------------
def test_transformer_ratios_66kv(p21: NetworkParameters, p2: NetworkParameters) -> None:
    assert LINE_VOLTAGE_2_1_V == 66_000.0
    assert p21.t1_primary_v == 1_000.0 and p21.t1_secondary_v == 66_000.0
    assert p21.t2_primary_v == 66_000.0 and p21.t2_secondary_v == 120.0
    assert p21.n1 == pytest.approx(66.0) and p21.a2 == pytest.approx(550.0)
    assert (p21.t1_label, p21.t2_label, p21.line_kv) == ("1kV:66kV", "66kV:120V", 66.0)
    assert (p2.t1_label, p2.t2_label, p2.line_kv) == ("1kV:13.2kV", "13.2kV:120V", 13.2)
    # Solo cambian T1 y T2: el resto de los parámetros es el del enunciado
    for name in ("v_load", "r_gen", "z_line", "energy_price_cop_per_kwh", "days_per_year"):
        assert getattr(p21, name) == getattr(p2, name)
    assert (p21.capacitor_cost_cop_per_kvar, p21.v_gen_min, p21.v_gen_max) == (100_000.0, 950.0, 1_100.0)


def test_reflected_quantities_66kv(p21: NetworkParameters, p2: NetworkParameters) -> None:
    assert p21.v_line_receiving == pytest.approx(66_000.0)  # V_0·a2
    assert p21.v_load_gen_side == pytest.approx(1_000.0)  # V_0·a2/n1, igual que a 13.2 kV
    assert p2.v_load_gen_side == pytest.approx(1_000.0)
    assert p21.r_gen_line_side == pytest.approx(0.5 * 66**2) == pytest.approx(2_178.0)
    assert p21.r_eq_line_side == pytest.approx(2_258.0)
    assert p21.z_gen_side == pytest.approx(0.5 + complex(80, 900) / 66**2)
    assert p21.z_gen_side.real == pytest.approx(0.5183654729, abs=1e-9)
    assert p21.z_gen_side.imag == pytest.approx(0.2066115702, abs=1e-9)
    # La línea vista desde el generador se divide por (66/13.2)² = 25
    assert (p2.z_line / p2.n1**2) / (p21.z_line / p21.n1**2) == pytest.approx(25.0)


@pytest.mark.parametrize("q_c", [0.0, 50.0, QC_FIXED_ECONOMIC_2_1_KVAR, 300.0])
def test_currents_scale_with_line_voltage(demand, p2, p21, q_c: float) -> None:
    r2, r21 = solve_problem2(demand, q_c, p2), solve_problem2(demand, q_c, p21)
    np.testing.assert_allclose(r21.i_load, r2.i_load, rtol=1e-13)  # la carga no cambia
    np.testing.assert_allclose(r21.i_line, r2.i_line / 5.0, rtol=1e-13)  # 550 / 110 = 5
    np.testing.assert_allclose(r21.i_gen, r2.i_gen, rtol=1e-13)  # el generador ve la misma corriente
    np.testing.assert_allclose(np.abs(r21.i_line), np.abs(r21.i_load) / 550.0, rtol=1e-13)
    np.testing.assert_allclose(np.abs(r21.i_gen), np.abs(r21.i_line) * 66.0, rtol=1e-13)
    np.testing.assert_allclose(r21.p_loss_gen_kw, r2.p_loss_gen_kw, rtol=1e-12)  # misma I_gen ⇒ misma pérdida en R_gen
    np.testing.assert_allclose(r21.p_loss_line_kw, r2.p_loss_line_kw / 25.0, rtol=1e-12)
    np.testing.assert_allclose(r21.q_loss_kvar, r2.q_loss_kvar / 25.0, rtol=1e-12)


@pytest.mark.parametrize("q_c", [0.0, 50.0, QC_FIXED_ECONOMIC_2_1_KVAR, 300.0, 1500.0])
def test_power_conservation_66kv(demand, p21, q_c: float) -> None:
    r = solve_problem2(demand, q_c, p21)
    assert power_balance_error(r, p21).max() < 1e-12
    s_gen = r.v_gen * np.conj(r.i_gen) / 1000
    np.testing.assert_allclose(s_gen, r.s_gen_kva, rtol=1e-12)
    # Transformadores ideales: la potencia compleja es la misma a ambos lados de T1 y de T2
    np.testing.assert_allclose(r.v_t1_primary * np.conj(r.i_gen), r.v_line_send * np.conj(r.i_line), rtol=1e-12)
    np.testing.assert_allclose(r.v_line_receiving * np.conj(r.i_line), r.v_load * np.conj(r.i_load), rtol=1e-12)
    # V_gen por el camino reflejado al generador
    v_ref = p21.v_load_gen_side + r.i_gen * p21.z_gen_side
    np.testing.assert_allclose(r.v_gen, v_ref, rtol=1e-12)


def test_affine_model_and_loss_formula_66kv(demand, p21) -> None:
    model = affine_voltage_model(demand, p21)
    kappa, q = daily_loss_quadratic(demand, p21)
    assert kappa == pytest.approx(2258.0 * 1000 / 66_000.0**2)
    for q_c in (0.0, QC_FIXED_ECONOMIC_2_1_KVAR, 400.0):
        r = solve_problem2(demand, q_c, p21)
        np.testing.assert_allclose(model.v_gen(q_c), r.v_gen, rtol=1e-12)
        np.testing.assert_allclose(r.p_loss_kw, kappa * (demand.p_total_kw**2 + (q - q_c) ** 2), rtol=1e-12)
    share = solve_problem2(demand, QC_FIXED_ECONOMIC_2_1_KVAR, p21)
    assert share.p_loss_gen_kw.sum() / share.p_loss_kw.sum() == pytest.approx(2178.0 / 2258.0)


# ----------------------------------------------------------------------------------
# Factibilidad y banco del Problema 2.1
# ----------------------------------------------------------------------------------
def test_feasibility_66kv_has_common_window(demand, p21) -> None:
    feas = feasibility_analysis(demand, p21)
    assert feas.is_feasible and feas.conflicting_pairs == ()
    assert feas.max_numeric_deviation_kvar < 1e-6
    assert len(feas.global_set) == 1
    assert feas.global_set[0].lo == pytest.approx(87.248090, abs=1e-5)
    assert feas.global_set[0].hi == pytest.approx(1530.469, abs=1e-2)
    # La cota inferior la impone la hora 12 (mayor carga); las horas valle admiten Q_C = 0
    assert int(np.nanargmax(feas.hourly_q_min)) + 1 == 12
    assert feas.hourly_sets[3][0].lo == 0.0


def test_fixed_bank_design_66kv(b21) -> None:
    eco = b21.economic
    assert QC_FIXED_ECONOMIC_2_1_KVAR == 87.25
    assert eco.q_c_design_kvar == QC_FIXED_ECONOMIC_2_1_KVAR  # el código deduce exactamente el valor adoptado
    assert eco.band.hours_in_band == 24 and eco.band.is_fully_feasible
    assert eco.band.window == (Interval(eco.band.window[0].lo, eco.band.window[0].hi),)
    assert eco.q_c_band_optimum_kvar == pytest.approx(87.2480902, abs=1e-6)
    assert 0 <= eco.q_c_design_kvar - eco.q_c_band_optimum_kvar < 0.01
    # El mínimo libre de J queda 1.49 kvar por debajo de la ventana y deja la hora 12 fuera por 0.31 V
    assert eco.q_c_free_kvar == pytest.approx(85.7587298, abs=1e-6)
    assert eco.q_c_free_kvar == pytest.approx(eco.q_c_free_numeric_kvar, abs=1e-5)
    assert eco.free.hours_out_of_band == 1 and eco.free.max_violation_v == pytest.approx(0.30954, abs=1e-4)
    assert eco.derivative_at_design > 0
    assert eco.hours_out == ()


def test_no_smaller_fixed_bank_is_feasible_66kv(demand, p21) -> None:
    model = affine_voltage_model(demand, p21)
    q = np.linspace(0.0, 87.24, 8725)
    v = np.abs(model.A[:, None] + model.B * q[None, :])
    ok = ((v >= p21.v_gen_min) & (v <= p21.v_gen_max)).all(axis=0)
    assert not ok.any()
    v_design = np.abs(model.v_gen(QC_FIXED_ECONOMIC_2_1_KVAR))
    assert np.all((v_design >= p21.v_gen_min) & (v_design <= p21.v_gen_max))


def test_problem_2_1_reference_values(b21) -> None:
    """Valores de referencia con Q_C = 87.25 kvar (contrastados con la auditoría independiente)."""
    r, nc = b21.economic.result, b21.no_capacitor
    e, e0 = r.economics, nc.economics
    # Sin capacitor
    assert e0.daily_loss_kwh == pytest.approx(341.6402521, abs=1e-6)
    assert e0.annual_loss_cost_cop == pytest.approx(119_710_744.32, abs=0.01)
    assert nc.hours_out_of_band == 10 and nc.max_violation_v == pytest.approx(19.02998, abs=1e-4)
    assert nc.v_gen_mag.min() == pytest.approx(1032.3365, abs=1e-3)
    assert np.abs(nc.circuit.i_line).max() == pytest.approx(3.45372, abs=1e-4)
    # Con el banco
    assert e.daily_loss_kwh == pytest.approx(225.2714088, abs=1e-6)
    assert r.circuit.p_loss_line_kw.sum() == pytest.approx(7.9813, abs=1e-3)
    assert r.circuit.p_loss_gen_kw.sum() == pytest.approx(217.2901, abs=1e-3)
    assert e.capex_cop == pytest.approx(8_725_000.0)
    assert e.annual_loss_cost_cop == pytest.approx(78_935_101.63, abs=0.01)
    assert e.total_annual_cost_cop == pytest.approx(87_660_101.63, abs=0.01)
    assert e.annual_savings_cop == pytest.approx(40_775_642.69, abs=0.01)
    assert e.payback_days == pytest.approx(78.10116, abs=1e-4)
    assert e.payback_days == pytest.approx(e.capex_cop / e.annual_savings_cop * 365)
    assert e.roi_pct(1) == pytest.approx(367.3426, abs=1e-3)
    assert e.roi_pct(5) == pytest.approx(2236.7130, abs=1e-3)
    assert r.is_voltage_feasible and r.hours_out_of_band == 0
    assert r.v_gen_mag.min() == pytest.approx(1015.0624, abs=1e-3) and int(np.argmin(r.v_gen_mag)) + 1 == 4
    assert r.v_gen_mag.max() == pytest.approx(1099.9996, abs=1e-3) and int(np.argmax(r.v_gen_mag)) + 1 == 12
    assert r.v_gen_mag.max() <= 1100.0
    i_line = np.abs(r.circuit.i_line)
    assert i_line.max() == pytest.approx(2.71580, abs=1e-4) and int(np.argmax(i_line)) + 1 == 12
    assert i_line.min() == pytest.approx(1.04451, abs=1e-4) and int(np.argmin(i_line)) + 1 == 8
    assert i_line.mean() == pytest.approx(1.95195, abs=1e-4)
    # fp: 8 horas valle en adelanto (Q_carga < 87.25 kvar) y 16 en atraso
    assert r.hours_leading == 8
    assert r.circuit.leading_mask.tolist() == [True] * 8 + [False] * 16
    assert r.pf_net.min() == pytest.approx(0.66428, abs=1e-4)
    assert r.pf_net.max() == pytest.approx(0.99883, abs=1e-4)


def test_step_table_and_hourly_profiles_66kv(b21) -> None:
    table = hourly_step_table(b21.demand, b21.economic.result.circuit, b21.params)
    assert len(table) == 24
    assert table["error_conservacion_rel"].max() < 1e-12
    assert (table["Q_C_kvar"] == QC_FIXED_ECONOMIC_2_1_KVAR).all()
    df = b21.economic.result.circuit.to_dataframe()
    for column in ("I_line_A", "V_gen_V", "P_loss_line_kW", "P_loss_gen_kW", "Q_loss_kvar", "S_gen_kVA", "pf_net"):
        assert df[column].notna().all() and len(df[column]) == 24
    np.testing.assert_allclose(df["P_loss_kW"], df["P_loss_line_kW"] + df["P_loss_gen_kW"])


# ----------------------------------------------------------------------------------
# Comparación Problema 2 vs. Problema 2.1
# ----------------------------------------------------------------------------------
def test_bundles_are_named_and_independent(b2, b21) -> None:
    assert (b2.name, b21.name) == (CASE_2, CASE_2_1)
    assert b21.title == "Problema 2.1 (1kV:66kV / 66kV:120V)"
    assert list(b21.strategies) == [Strategy.NO_CAPACITOR, Strategy.FIXED_ECONOMIC]
    assert b2.economic.q_c_design_kvar == QC_FIXED_ECONOMIC_KVAR  # el Problema 2 no cambia
    np.testing.assert_array_equal(b2.demand.p_total_kw, b21.demand.p_total_kw)
    np.testing.assert_allclose(b2.problem1.p_loss_kw, b21.problem1.p_loss_kw)  # el Problema 1 no depende de T1/T2


def test_comparison_table_values(b2, b21) -> None:
    table = comparison_table(b2, b21)
    assert list(table.columns) == ["Magnitud", "Unidad", CASE_2, CASE_2_1, RATIO_COLUMN]
    assert list(table["Magnitud"]) == list(case_metrics(b2))
    r2, r21 = b2.economic.result, b21.economic.result

    def cell(name: str, case: str) -> float:
        return comparison_value(table, name, case)  # type: ignore[return-value]

    assert cell("Q_C del banco fijo", CASE_2) == 378.35 and cell("Q_C del banco fijo", CASE_2_1) == 87.25
    assert cell("Tensión de línea", RATIO_COLUMN) == pytest.approx(5.0)
    assert cell("|I_line| máx", CASE_2_1) == pytest.approx(np.abs(r21.circuit.i_line).max())
    assert cell("|I_line| promedio", CASE_2) == pytest.approx(np.abs(r2.circuit.i_line).mean())
    assert cell("Horas dentro de [950, 1100] V", CASE_2) == 23
    assert cell("Horas dentro de [950, 1100] V", CASE_2_1) == 24
    assert cell("Pérdidas diarias", CASE_2_1) == pytest.approx(r21.economics.daily_loss_kwh)
    assert cell("Pérdidas anuales", CASE_2_1) == pytest.approx(r21.economics.daily_loss_kwh * 365)
    assert cell("Costo de pérdidas por día", CASE_2_1) == pytest.approx(r21.economics.daily_loss_kwh * 960)
    assert cell("Pérdidas diarias", RATIO_COLUMN) == pytest.approx(225.2714088 / 2233.7263575, rel=1e-9)
    assert cell("Costo total anual J", RATIO_COLUMN) == pytest.approx(87_660_101.63 / 820_532_715.66, rel=1e-9)
    assert cell("Sin capacitor: |I_line| máx", RATIO_COLUMN) == pytest.approx(0.2)  # ÷5 exacto para la misma carga
    assert math.isinf(cell("Payback", CASE_2)) and cell("Payback", CASE_2_1) == pytest.approx(78.10116, abs=1e-4)
    assert math.isnan(cell("Payback", RATIO_COLUMN))
    assert math.isnan(cell("Ahorro anual frente a Q_C = 0", RATIO_COLUMN))  # signos opuestos: sin relación
    assert cell("Ahorro anual frente a Q_C = 0", CASE_2) < 0 < cell("Ahorro anual frente a Q_C = 0", CASE_2_1)


def test_comparison_physical_conclusions(b2, b21) -> None:
    r2, r21 = b2.economic.result, b21.economic.result
    n2, n21 = b2.no_capacitor, b21.no_capacitor
    assert r21.q_c_installed_kvar < r2.q_c_installed_kvar
    assert r21.hours_out_of_band < r2.hours_out_of_band
    assert r21.economics.total_annual_cost_cop < n21.economics.total_annual_cost_cop  # a 66 kV el banco sí ahorra
    assert r2.economics.total_annual_cost_cop > n2.economics.total_annual_cost_cop  # a 13.2 kV encarece
    # Sin capacitor las pérdidas no bajan 25 veces: R_gen (lado de 1 kV) no depende de la tensión de línea
    ratio = n2.economics.daily_loss_kwh / n21.economics.daily_loss_kwh
    assert ratio == pytest.approx(167.12 / 80.0 * 80.0 / 2258.0 * 25.0, rel=1e-9) == pytest.approx(1.8503, abs=1e-3)
    np.testing.assert_allclose(n21.circuit.p_loss_gen_kw, n2.circuit.p_loss_gen_kw, rtol=1e-12)


def test_format_comparison_is_text(b2, b21) -> None:
    shown = format_comparison(comparison_table(b2, b21))
    assert shown.shape == (len(case_metrics(b2)), 5)
    assert all(isinstance(v, str) for v in shown[CASE_2_1])
    row = dict(zip(shown["Magnitud"], shown[CASE_2], strict=True))
    assert row["Payback"] == "no se recupera"
    assert row["CAPEX del banco"] == "$ 37.835.000 COP"
    assert dict(zip(shown["Magnitud"], shown[CASE_2_1], strict=True))["CAPEX del banco"] == "$ 8.725.000 COP"


def test_analysis_and_synthesis_text(b2, b21) -> None:
    sections = problem21_analysis(b21, b2)
    assert list(sections) == [
        "Efecto de elevar la línea de 13.2 kV a 66 kV",
        "Banco capacitivo y tensión |Vgen(t)|",
        "Corriente de línea |Iline(t)|",
        "Factor de potencia neto",
        "Pérdidas Ploss(t) y costo",
    ]
    text = " ".join(line for lines in sections.values() for line in lines)
    for token in (
        "n₁ = 66",
        "a₂ = 550",
        "25 veces menor",
        "87.25 kvar",
        "24 de 24 horas",
        "225.27 kWh/día",
        "78.1 días",
    ):
        assert token in text, token
    synthesis = " ".join(comparison_synthesis(b2, b21))
    for token in ("378.35 kvar", "87.25 kvar", "24/24 h", "no se recupera", "se recupera en 78 días"):
        assert token in synthesis, token


# ----------------------------------------------------------------------------------
# Auditoría independiente, exportación y diagrama del caso 2.1
# ----------------------------------------------------------------------------------
def test_audit_net_66kv_matches_solver(demand, p21) -> None:
    net = audit.NET_P21
    assert (net.n1, net.a2, net.q_c) == (66.0, 550.0, QC_FIXED_ECONOMIC_2_1_KVAR)
    assert net.z_ref == pytest.approx(p21.z_gen_side) and net.r_eq_line == pytest.approx(p21.r_eq_line_side)
    for q_c in (0.0, QC_FIXED_ECONOMIC_2_1_KVAR):
        hours = audit.solve_day(q_c, net)
        r = solve_problem2(demand, q_c, p21)
        np.testing.assert_allclose([h.v_gen for h in hours], r.v_gen, rtol=1e-12)
        np.testing.assert_allclose([h.i_line for h in hours], r.i_line, rtol=1e-12)
        np.testing.assert_allclose([h.p_loss_kw for h in hours], r.p_loss_kw, rtol=1e-12)
        np.testing.assert_allclose([h.q_loss_kvar for h in hours], r.q_loss_kvar, rtol=1e-12)
        np.testing.assert_allclose([h.s_gen_kva for h in hours], r.s_gen_kva, rtol=1e-12)
        assert max(h.balance_error for h in hours) < 1e-12 and max(h.path_error for h in hours) < 1e-12


def test_audit_derives_both_banks_independently() -> None:
    d21, d2 = audit.derive_design(audit.NET_P21), audit.derive_design(audit.NET_P2)
    assert (d21.best_hours, d21.q_design) == (24, QC_FIXED_ECONOMIC_2_1_KVAR)
    assert (d2.best_hours, d2.q_design) == (23, QC_FIXED_ECONOMIC_KVAR)
    assert d21.q_free == pytest.approx(85.75873, abs=1e-4) and d21.q_exact == pytest.approx(87.24809, abs=1e-5)
    assert d21.windows[0][0] == pytest.approx(87.24809, abs=1e-5)
    assert d21.windows[0][1] == pytest.approx(1530.469, abs=1e-2)


def test_audit_report_66kv_passes_and_matches_csv(b2, b21, tmp_path: Path) -> None:
    export_tables_21(b21, b2, tmp_path)
    rep = audit.run_audit(b21.economic.q_c_design_kvar, tmp_path, audit.NET_P21)
    assert rep.ok, [c for c in rep.checks if not c[1]]
    assert len(rep.checks) == 12  # incluye el contraste con los dos CSV horarios del caso
    files = audit.write_outputs(rep, tmp_path)
    assert [f.name for f in files] == ["auditoria_p21.txt", "auditoria_p21_24h.csv"]
    e = b21.economic.result.economics
    assert audit.annual_cost(87.25, audit.NET_P21) == pytest.approx(e.total_annual_cost_cop, rel=1e-12)
    assert audit.daily_loss_kwh(87.25, audit.NET_P21) == pytest.approx(e.daily_loss_kwh, rel=1e-12)
    assert audit.hours_in_band(87.25, audit.NET_P21) == 24 and audit.hours_in_band(87.24, audit.NET_P21) == 23
    table = pd.read_csv(tmp_path / "auditoria_p21_24h.csv")
    assert len(table) == 24 and table["en_banda"].all()


def test_export_tables_and_report_include_2_1(b2, b21, tmp_path: Path) -> None:
    export_tables(b2, tmp_path)
    paths = export_tables_21(b21, b2, tmp_path)
    names = {p.name for p in paths}
    assert {
        "p21_sin_capacitor_horario.csv",
        "p21_fijo_economico_horario.csv",
        "p21_factibilidad_horaria.csv",
        "p21_barrido_qc_fijo.csv",
        "p21_paso_a_paso_24h_fijo_economico.csv",
        "comparacion_p2_vs_p21.csv",
    } <= names
    hourly = pd.read_csv(tmp_path / "p21_fijo_economico_horario.csv")
    assert (hourly["Q_C_kvar"] == 87.25).all() and hourly["V_gen_V"].between(950, 1100).all()
    cmp_csv = pd.read_csv(tmp_path / "comparacion_p2_vs_p21.csv")
    assert list(cmp_csv.columns) == ["Magnitud", "Unidad", CASE_2, CASE_2_1, RATIO_COLUMN]

    catalog = chart_catalog_21(b21, b2)
    assert [spec.filename[:2] for spec in catalog] == ["17", "18", "19", "20", "21", "22", "23"]
    charts21 = [(spec, tmp_path / spec.filename) for spec in catalog]
    report = build_markdown_report(b2, [], b21, charts21)
    for heading in (
        "## 7. Problema 2.1 — Red con T1 = 1 kV : 66 kV y T2 = 66 kV : 120 V",
        "### 7.7 Análisis",
        "### 7.8 Comparación — Problema 2 vs. Problema 2.1",
        "## 8. Desarrollo Matemático Paso a Paso",
        "## 12. Guion de exposición",
    ):
        assert heading in report, heading
    assert report.index("### 7.7 Análisis") < report.index("### 7.8 Comparación")
    assert "Q_C = 87.25 kvar" in report and "23_comparacion_p2_vs_p21.png" in report
    # Sin el caso 2.1 el reporte conserva su numeración original
    assert "## 7. Desarrollo Matemático Paso a Paso" in build_markdown_report(b2, [])


def test_circuit_diagram_2_1_labels(b21) -> None:
    svg = CH.circuit_svg(
        b21.params, b21.economic.result.circuit, 11, problem2=True, demand=b21.demand, title="Problema 2.1"
    )
    for label in ("1kV:66kV", "66kV:120V", "0.5 Ω", "80 Ω", "j900 Ω", "87.25 kvar", "Línea (66 kV)", "Problema 2.1"):
        assert label in svg, label
    assert "13.2kV" not in svg
    assert svg.count('r="3.4"') == 4  # dos puntos de polaridad por transformador
