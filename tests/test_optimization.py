"""Pruebas de la capa de optimización y economía."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.domain.models import DemandProfile, NetworkParameters, Strategy
from src.optimization.capacitor_optimizer import (
    Interval,
    analytic_hour_feasible_set,
    closed_form_fixed_optimum,
    cost_derivative,
    feasibility_analysis,
    fixed_economic_optimum,
    fixed_lagging_optimum,
    fixed_voltage_pareto,
    intersect_many,
    lagging_dispatch,
    lagging_voltage_limit,
    line_reactance_sensitivity,
    pareto_front_mask,
    project_onto_set,
    switched_capacitor_bank,
    switched_lagging_bank,
    total_annual_cost_fixed,
    voltage_violation,
)
from src.optimization.economics import (
    build_economic_summary,
    cumulative_cash_flow,
    format_cop,
)
from src.optimization.pipeline import run_full_analysis
from src.physics.circuit_solver import affine_voltage_model, solve_problem2


@pytest.fixture(scope="module")
def demand() -> DemandProfile:
    return DemandProfile.default()


@pytest.fixture(scope="module")
def params() -> NetworkParameters:
    return NetworkParameters()


@pytest.fixture(scope="module")
def feas(demand: DemandProfile, params: NetworkParameters):
    return feasibility_analysis(demand, params)


# ----------------------------------------------------------------------------------
# Álgebra de intervalos
# ----------------------------------------------------------------------------------
def test_interval_algebra() -> None:
    a = (Interval(0, 10), Interval(20, 30))
    b = (Interval(5, 25),)
    assert intersect_many([a, b]) == (Interval(5, 10), Interval(20, 25))
    assert intersect_many([a, (Interval(11, 19),)]) == ()
    assert project_onto_set(a, 15) in (10, 20)
    assert project_onto_set(a, 27) == 27


def test_analytic_feasible_set_simple_parabola() -> None:
    # |V|² = Q² + 0·Q + 0 → |V| = |Q|; banda [3, 5] en dominio [0, 10] → [3, 5]
    s = analytic_hour_feasible_set(1.0, 0.0, 0.0, 3.0, 5.0, 0.0, 10.0)
    assert len(s) == 1
    assert s[0].lo == pytest.approx(3.0) and s[0].hi == pytest.approx(5.0)
    # Banda [3, 5] en dominio [-10, 10] → dos ramas
    s2 = analytic_hour_feasible_set(1.0, 0.0, 0.0, 3.0, 5.0, -10.0, 10.0)
    assert [(round(i.lo, 9), round(i.hi, 9)) for i in s2] == [(-5, -3), (3, 5)]


# ----------------------------------------------------------------------------------
# 1. Factibilidad
# ----------------------------------------------------------------------------------
def test_feasibility_analytic_matches_numeric(feas) -> None:
    assert feas.max_numeric_deviation_kvar < 1e-6
    for s, ns in zip(feas.hourly_sets, feas.numeric_sets, strict=True):
        assert len(s) == len(ns) >= 1


def test_feasibility_boundaries_hit_voltage_limits(demand, params, feas) -> None:
    model = affine_voltage_model(demand, params)
    for t, s in enumerate(feas.hourly_sets):
        for iv in s:
            for q in (iv.lo, iv.hi):
                v = abs(model.A[t] + model.B * q)
                assert params.v_gen_min - 1e-6 <= v <= params.v_gen_max + 1e-6
                if 0 < q < feas.q_search_max:
                    assert min(abs(v - params.v_gen_min), abs(v - params.v_gen_max)) < 1e-6


def test_global_fixed_bank_is_infeasible_with_conflicts(feas) -> None:
    assert not feas.is_feasible
    assert feas.global_set == ()
    assert 8 in feas.conflict_hours and 19 in feas.conflict_hours
    assert feas.critical_pair == (8, 19)


def test_no_fixed_qc_satisfies_band_dense_grid(demand, params) -> None:
    q = np.linspace(0, 2000, 400_001)
    model = affine_voltage_model(demand, params)
    v = np.abs(model.A[:, None] + model.B * q[None, :])
    ok = ((v >= params.v_gen_min) & (v <= params.v_gen_max)).all(axis=0)
    assert not ok.any()


# ----------------------------------------------------------------------------------
# 2. Óptimo económico fijo
# ----------------------------------------------------------------------------------
def test_economic_optimum_closed_form_vs_numeric(demand, params) -> None:
    res = fixed_economic_optimum(demand, params)
    assert res.q_c_closed_form_kvar == pytest.approx(res.q_c_numeric_kvar, abs=1e-5)
    assert abs(res.derivative_at_optimum) < 1e-4
    q = res.q_c_closed_form_kvar
    j0 = float(total_annual_cost_fixed(q, demand, params))
    for dq in (-1.0, -0.01, 0.01, 1.0):
        assert float(total_annual_cost_fixed(q + dq, demand, params)) > j0


def test_economic_cost_function_matches_circuit(demand, params) -> None:
    q = 91.0
    r = solve_problem2(demand, q, params)
    expected = r.daily_energy_loss_kwh * 960 * 365 + 100_000 * q
    assert float(total_annual_cost_fixed(q, demand, params)) == pytest.approx(expected, rel=1e-12)


def test_economic_summary_kpis(demand, params) -> None:
    res = fixed_economic_optimum(demand, params).result
    e = res.economics
    assert e.capex_cop == pytest.approx(100_000 * res.q_c_installed_kvar)
    assert e.annual_savings_cop > 0
    assert e.payback_days == pytest.approx(e.capex_cop / e.annual_savings_cop * 365)
    assert e.roi_pct(1) == pytest.approx(100 * (e.annual_savings_cop - e.capex_cop) / e.capex_cop)
    assert e.total_annual_cost_cop < e.baseline_annual_loss_cost_cop
    assert res.hours_out_of_band > 0  # el óptimo económico viola la banda de tensión


def test_closed_form_derivative_sign(demand, params) -> None:
    q = closed_form_fixed_optimum(demand, params)
    assert cost_derivative(q - 5, demand, params) < 0 < cost_derivative(q + 5, demand, params)


# ----------------------------------------------------------------------------------
# 3. Pareto
# ----------------------------------------------------------------------------------
def test_pareto_front_is_nondominated() -> None:
    cost = np.array([1, 2, 3, 4, 2.5])
    viol = np.array([5, 3, 4, 1, 3])
    mask = pareto_front_mask(cost, viol)
    assert mask.tolist() == [True, True, False, True, False]


def test_fixed_voltage_pareto(demand, params, feas) -> None:
    par = fixed_voltage_pareto(demand, params, feasibility=feas)
    assert par.feasible_optimum is None
    assert par.recommended is par.minimax
    grid_min = par.grid["Violacion_max_V"].min()
    assert par.minimax.max_violation_v <= grid_min + 1e-9
    assert par.minimax.max_violation_v > 0
    front = par.front.sort_values("Costo_total_anual_COP")
    assert np.all(np.diff(front["Violacion_max_V"].to_numpy()) < 0)


def test_pareto_returns_feasible_optimum_when_region_exists(demand) -> None:
    p = NetworkParameters().with_line_reactance(500.0)
    feas = feasibility_analysis(demand, p, verify_numerically=False)
    assert feas.is_feasible
    par = fixed_voltage_pareto(demand, p, q_search_max=2000, feasibility=feas)
    assert par.feasible_optimum is not None
    assert par.feasible_optimum.is_voltage_feasible


# ----------------------------------------------------------------------------------
# 4. Banco automático por pasos
# ----------------------------------------------------------------------------------
@pytest.mark.parametrize("step", [None, 25.0, 12.5])
def test_switched_bank_is_100pct_feasible(demand, params, feas, step) -> None:
    sw = switched_capacitor_bank(demand, params, step_kvar=step, feasibility=feas)
    r = sw.result
    assert r.is_voltage_feasible
    assert np.all(r.v_gen_mag >= params.v_gen_min - 1e-6)
    assert np.all(r.v_gen_mag <= params.v_gen_max + 1e-6)
    assert np.all(r.q_c_profile_kvar <= sw.q_c_max_kvar + 1e-9)
    assert np.all(r.q_c_profile_kvar >= 0)
    assert sw.q_c_max_kvar >= sw.q_c_max_lower_bound_kvar - 1e-6
    if step is not None:
        assert np.allclose(r.q_c_profile_kvar / step, np.rint(r.q_c_profile_kvar / step))
        assert sw.continuous_reference is not None
        assert r.economics.total_annual_cost_cop >= sw.continuous_reference.economics.total_annual_cost_cop - 1


def test_switched_bank_beats_no_capacitor(demand, params, feas) -> None:
    sw = switched_capacitor_bank(demand, params, feasibility=feas)
    assert sw.result.economics.annual_savings_cop > 0
    assert math.isfinite(sw.result.economics.payback_days)


# ----------------------------------------------------------------------------------
# Sensibilidad y economía auxiliar
# ----------------------------------------------------------------------------------
def test_line_reactance_sensitivity(demand) -> None:
    sens = line_reactance_sensitivity(demand, NetworkParameters(), scan_step=10.0)
    assert not sens.actual_is_feasible
    xc = sens.x_critical_upper
    assert xc is not None and 0 < xc < 900
    base = NetworkParameters()
    assert feasibility_analysis(demand, base.with_line_reactance(xc - 0.01), verify_numerically=False).is_feasible
    assert not feasibility_analysis(demand, base.with_line_reactance(xc + 0.01), verify_numerically=False).is_feasible


def test_voltage_violation() -> None:
    v = voltage_violation([900, 1000, 1200], NetworkParameters())
    np.testing.assert_allclose(v, [50, 0, 100])


def test_cash_flow_and_format(params) -> None:
    e = build_economic_summary(100.0, 400.0, 600.0, params)
    cf = cumulative_cash_flow(e, horizon_years=2)
    assert cf["flujo_acumulado_COP"].iloc[0] == pytest.approx(-e.capex_cop)
    assert cf["flujo_acumulado_COP"].iloc[-1] == pytest.approx(2 * e.annual_savings_cop - e.capex_cop)
    assert format_cop(1234567.8) == "$ 1.234.568 COP"


def test_full_pipeline(demand) -> None:
    bundle = run_full_analysis(demand, include_sensitivity=False)
    assert set(bundle.strategies) == {
        Strategy.NO_CAPACITOR,
        Strategy.FIXED_ECONOMIC,
        Strategy.FIXED_MIN_VIOLATION,
        Strategy.SWITCHED,
        Strategy.FIXED_LAGGING,
        Strategy.SWITCHED_LAGGING,
    }
    table = bundle.comparison_table()
    assert len(table) == 7
    assert {"fp_neto_min", "fp_neto_max", "Estado_fp_24h", "Horas_adelanto"} <= set(table.columns)
    assert bundle.switched.result.hours_out_of_band == 0
    status = dict(zip(table["Estrategia"], table["Estado_fp_24h"], strict=True))
    assert status[bundle.fixed_lagging.result.label] == "24/24 h en atraso"
    assert status[bundle.switched_lagging.result.label] == "24/24 h en atraso"
    assert status[bundle.switched.result.label].endswith("h en adelanto")


# ----------------------------------------------------------------------------------
# Requisito de factor de potencia neto en atraso (Q_net ≥ 0)
# ----------------------------------------------------------------------------------
def test_fixed_lagging_respects_qnet_nonnegative(demand, params) -> None:
    res = fixed_lagging_optimum(demand, params)
    assert res.q_c_upper_bound_kvar == pytest.approx(30.9872, abs=1e-4)
    assert res.binding_hour == 4
    assert res.bound_is_active  # el óptimo libre (91.03 kvar) excede la cota de atraso
    assert res.q_c_closed_form_kvar == pytest.approx(res.q_c_upper_bound_kvar, abs=1e-12)
    assert res.q_c_numeric_kvar == pytest.approx(res.q_c_closed_form_kvar, abs=1e-5)
    q_net = demand.q_total_kvar - res.result.q_c_profile_kvar
    assert np.all(q_net >= -1e-9)
    np.testing.assert_allclose(res.result.q_net_kvar, q_net, atol=1e-12)
    assert res.result.is_always_lagging and res.result.hours_leading == 0
    assert np.all(res.result.pf_net <= 1.0 + 1e-12)
    # El costo restringido no puede ser menor que el óptimo libre
    free = fixed_economic_optimum(demand, params).result.economics.total_annual_cost_cop
    assert res.result.economics.total_annual_cost_cop >= free


@pytest.mark.parametrize("step", [5.0, 12.5, 25.0, 50.0])
def test_switched_lagging_never_leading(demand, params, step: float) -> None:
    res = switched_lagging_bank(demand, params, step_kvar=step)
    q_c = res.result.q_c_profile_kvar
    assert np.all(demand.q_total_kvar - q_c >= -1e-9)  # 24/24 h en atraso
    assert res.result.hours_leading == 0
    np.testing.assert_allclose(np.mod(q_c, step), 0.0, atol=1e-9)  # múltiplos del paso
    assert q_c.max() <= res.q_c_max_kvar + 1e-9
    # El n elegido es el mínimo de la curva de costo exhaustiva
    best = res.cost_curve["Costo_total_anual_COP"].min()
    assert res.result.economics.total_annual_cost_cop == pytest.approx(best, rel=1e-12)


def test_lagging_dispatch_is_largest_level_below_load() -> None:
    q = np.array([30.9, 49.99, 50.0, 157.27])
    np.testing.assert_allclose(lagging_dispatch(q, 6, 25.0), [25.0, 25.0, 50.0, 150.0])
    np.testing.assert_allclose(lagging_dispatch(q, 1, 25.0), [25.0, 25.0, 25.0, 25.0])


def test_lagging_voltage_limit_theorem(demand, params, feas) -> None:
    lag = lagging_voltage_limit(demand, params, feasibility=feas)
    assert lag.worst_hour == 12
    assert lag.max_floor_v == pytest.approx(1438.03, abs=0.05)
    assert lag.max_floor_v > params.v_gen_max
    assert lag.floor_is_unity_pf.all()  # el mínimo en atraso siempre ocurre en Q_net = 0
    assert not lag.lagging_band_feasible
    assert lag.hours_band_reachable_lagging == 2
    # La banda en la hora 12 exige adelanto
    assert lag.q_net_required_kvar[11] < 0
    # Ningún punto del intervalo de atraso de la hora 12 está por debajo de la cota
    model = affine_voltage_model(demand, params)
    grid = np.linspace(0.0, demand.q_total_kvar[11], 2001)
    assert np.abs(model.A[11] + model.B * grid).min() >= lag.max_floor_v - 1e-9
