"""Golden tests de la física: Hora 1 del Problema 1 y conservación de potencia compleja."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.domain.constants import DEMAND_TABLE
from src.domain.models import DemandProfile, NetworkParameters
from src.physics.circuit_solver import (
    affine_voltage_model,
    daily_loss_quadratic,
    reactive_power_kvar,
    solve_problem1,
    solve_problem2,
)
from src.physics.step_by_step import hourly_step_table, power_balance_error

TOL = 1e-4
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def demand() -> DemandProfile:
    return DemandProfile.default()


@pytest.fixture(scope="module")
def params() -> NetworkParameters:
    return NetworkParameters()


# ----------------------------------------------------------------------------------
# Datos de entrada
# ----------------------------------------------------------------------------------
def test_demand_profile_matches_table_1(demand: DemandProfile) -> None:
    assert demand.n_hours == 24
    np.testing.assert_array_equal(demand.hours, np.arange(1, 25))
    table = np.array(DEMAND_TABLE, float)
    np.testing.assert_array_equal(demand.p1_kw, table[:, 1])
    np.testing.assert_array_equal(demand.p2_kw, table[:, 3])
    assert demand.p1_kw.sum() == 1775 and demand.p2_kw.sum() == 1088


def test_demand_csv_roundtrip(demand: DemandProfile) -> None:
    csv = ROOT / "data" / "demand_profile_24h.csv"
    if not csv.exists():
        pytest.skip("CSV aún no generado")
    loaded = DemandProfile.from_csv(csv)
    np.testing.assert_allclose(loaded.s_total_kva, demand.s_total_kva)


def test_domain_arrays_are_immutable(demand: DemandProfile) -> None:
    with pytest.raises(ValueError):
        demand.p1_kw[0] = 1.0


def test_reactive_power_formula() -> None:
    assert reactive_power_kvar(70, 0.85) == pytest.approx(43.38207, rel=1e-6)
    assert reactive_power_kvar(80, 0.75) == pytest.approx(70.55336, rel=1e-6)


# ----------------------------------------------------------------------------------
# Problema 1 — Golden Test Hora 1
# ----------------------------------------------------------------------------------
def test_problem1_golden_hour_1(demand: DemandProfile) -> None:
    r = solve_problem1(demand)
    i1 = r.i_line[0]
    assert abs(i1) == pytest.approx(686.2745098, abs=TOL)
    assert np.degrees(np.angle(i1)) == pytest.approx(-31.78833062, abs=TOL)
    assert r.p_loss_kw[0] == pytest.approx(37_913.30258, abs=TOL)
    assert r.q_loss_kvar[0] == pytest.approx(423_875.4325, abs=TOL)
    assert abs(r.s_gen_kva[0]) == pytest.approx(425_617.0728, abs=TOL)


def test_problem1_power_conservation(demand: DemandProfile, params: NetworkParameters) -> None:
    r = solve_problem1(demand, params)
    s_gen_from_v = r.v_gen * np.conj(r.i_gen) / 1000.0
    np.testing.assert_allclose(s_gen_from_v, r.s_gen_kva, rtol=1e-12)
    np.testing.assert_allclose(r.i_line, r.i_load)


# ----------------------------------------------------------------------------------
# Problema 2 — transformadores ideales
# ----------------------------------------------------------------------------------
def test_transformer_ratios_and_equivalent_resistance(params: NetworkParameters) -> None:
    assert params.n1 == pytest.approx(13.2)
    assert params.a2 == pytest.approx(110.0)
    assert params.r_eq_line_side == pytest.approx(80 + 0.5 * 13.2**2)
    assert params.r_eq_line_side == pytest.approx(167.12, abs=1e-12)
    assert params.v_line_receiving == pytest.approx(13_200 + 0j)


@pytest.mark.parametrize("q_c", [0.0, 50.0, 137.5, 400.0])
def test_problem2_complex_power_conservation(demand: DemandProfile, params: NetworkParameters, q_c: float) -> None:
    r = solve_problem2(demand, q_c, params)
    lhs = r.v_gen * np.conj(r.i_gen)  # VA
    s_load_va = r.s_load_kva * 1000
    s_loss_line = np.abs(r.i_line) ** 2 * params.z_line
    s_loss_gen = np.abs(r.i_gen) ** 2 * params.r_gen
    np.testing.assert_allclose(lhs, s_load_va + s_loss_line + s_loss_gen, rtol=1e-12)
    np.testing.assert_allclose(r.s_gen_kva * 1000, lhs, rtol=1e-12)


def test_problem2_losses_use_equivalent_resistance(demand: DemandProfile, params: NetworkParameters) -> None:
    r = solve_problem2(demand, 0.0, params)
    expected = np.abs(r.i_line) ** 2 * 167.12 / 1000
    np.testing.assert_allclose(r.p_loss_kw, expected, rtol=1e-12)
    kappa, q = daily_loss_quadratic(demand, params)
    np.testing.assert_allclose(kappa * (demand.p_total_kw**2 + q**2), r.p_loss_kw, rtol=1e-12)


def test_problem2_hour1_reference_values(demand: DemandProfile) -> None:
    r = solve_problem2(demand, 0.0)
    s1 = np.hypot(70.0, reactive_power_kvar(70, 0.85))
    assert abs(r.i_load[0]) == pytest.approx(s1 * 1000 / 120, rel=1e-12)
    assert abs(r.i_line[0]) == pytest.approx(s1 * 1000 / 13_200, rel=1e-12)
    assert abs(r.i_gen[0]) == pytest.approx(s1 * 1000 / 13_200 * 13.2, rel=1e-12)
    assert r.v_t1_primary[0] == pytest.approx(r.v_line_send[0] / 13.2)


@pytest.mark.parametrize("q_c", [0.0, 75.0, 300.0])
def test_affine_voltage_model_matches_solver(demand: DemandProfile, q_c: float) -> None:
    model = affine_voltage_model(demand)
    r = solve_problem2(demand, q_c)
    np.testing.assert_allclose(model.v_gen(q_c), r.v_gen, rtol=1e-12)
    a, b, c = model.quadratic
    np.testing.assert_allclose(a * q_c**2 + b * q_c + c, np.abs(r.v_gen) ** 2, rtol=1e-12)


def test_hourly_vector_qc(demand: DemandProfile) -> None:
    q = np.linspace(0, 230, 24)
    r = solve_problem2(demand, q)
    for t in (0, 11, 23):
        single = solve_problem2(demand, q[t])
        assert r.v_gen[t] == pytest.approx(single.v_gen[t])
    with pytest.raises(ValueError):
        solve_problem2(demand, np.zeros(5))


# ----------------------------------------------------------------------------------
# Re-auditoría: costo diario P1(b), fp en atraso, conservación y desarrollo paso a paso
# ----------------------------------------------------------------------------------
def test_problem1_daily_cost(demand: DemandProfile, params: NetworkParameters) -> None:
    r = solve_problem1(demand, params)
    e_loss = r.daily_energy_loss_kwh
    assert e_loss == pytest.approx(3_684_396.4517, abs=1e-3)
    daily_cost = e_loss * params.energy_price_cop_per_kwh
    assert daily_cost == e_loss * 960
    assert daily_cost == pytest.approx(3_537_020_593.64, abs=0.01)
    assert round(e_loss) * 960 == 3_537_020_160  # cifra con kWh redondeados del enunciado


def test_loads_are_lagging(demand: DemandProfile) -> None:
    np.testing.assert_allclose(demand.q1_kvar, demand.p1_kw * np.tan(np.arccos(demand.pf1)), rtol=1e-15)
    np.testing.assert_allclose(demand.q2_kvar, demand.p2_kw * np.tan(np.arccos(demand.pf2)), rtol=1e-15)
    assert np.all(demand.q1_kvar >= 0) and np.all(demand.q2_kvar >= 0)
    assert np.all(solve_problem1(demand).q_net_kvar >= 0)


def test_hour12_unity_pf_voltage(demand: DemandProfile, params: NetworkParameters) -> None:
    q_c = demand.q_total_kvar.copy()  # Q_net = 0 en todas las horas
    r = solve_problem2(demand, q_c, params)
    np.testing.assert_allclose(r.q_net_kvar, 0.0, atol=1e-12)
    np.testing.assert_allclose(r.pf_net, 1.0, atol=1e-15)
    assert abs(r.v_gen[11]) == pytest.approx(1438.03, abs=0.05)


@pytest.mark.parametrize("q_c", [0.0, 30.9872, 125.0, 300.0])
def test_power_balance_error_below_1e12(demand: DemandProfile, params: NetworkParameters, q_c: float) -> None:
    for r in (solve_problem1(demand, params), solve_problem2(demand, q_c, params)):
        assert power_balance_error(r, params).max() < 1e-12


def test_step_table_matches_solver(demand: DemandProfile, params: NetworkParameters) -> None:
    r = solve_problem2(demand, 0.0, params)
    df = hourly_step_table(demand, r, params)
    assert len(df) == 24
    np.testing.assert_allclose(df["I_line_A_mag"], np.abs(r.i_line), rtol=1e-15)
    np.testing.assert_allclose(df["V_gen_V_mag"], np.abs(r.v_gen), rtol=1e-15)
    np.testing.assert_allclose(df["P_loss_total_kW"], df["P_loss_line_kW"] + df["P_loss_gen_kW"], rtol=1e-14)
    assert (df["fp_neto_estado"] == "atraso").all()
    assert df["error_conservacion_rel"].max() < 1e-12
    assert "V_T1_prim_V_mag" not in hourly_step_table(demand, solve_problem1(demand, params), params)
