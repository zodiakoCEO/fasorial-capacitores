"""Diagnóstico en consola (Fase 3): tabla comparativa de todos los escenarios."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.optimization.capacitor_optimizer import format_set  # noqa: E402
from src.optimization.economics import format_cop, format_number  # noqa: E402
from src.optimization.pipeline import AnalysisBundle, run_full_analysis  # noqa: E402


def _rule(title: str) -> None:
    print("\n" + "=" * 100 + f"\n  {title}\n" + "=" * 100)


def print_report(b: AnalysisBundle) -> None:
    p1 = b.problem1
    _rule("PROBLEMA 1 — Red directa a 120 V (sin transformadores, sin capacitor)")
    print(f"  |I_line(1)|  = {abs(p1.i_line[0]):.7f} A ∠ {np.degrees(np.angle(p1.i_line[0])):.8f}°")
    print(f"  P_loss(1)    = {p1.p_loss_kw[0]:,.5f} kW")
    print(f"  Q_loss(1)    = {p1.q_loss_kvar[0]:,.4f} kvar")
    print(f"  |S_gen(1)|   = {abs(p1.s_gen_kva[0]):,.4f} kVA")
    print(f"  |I_line| máx = {np.abs(p1.i_line).max():,.2f} A   |V_gen| máx = {np.abs(p1.v_gen).max():,.0f} V")
    print(
        f"  E_loss diaria = {p1.daily_energy_loss_kwh:,.2f} kWh  vs  energía servida = "
        f"{p1.daily_energy_served_kwh:,.0f} kWh  (×{p1.daily_energy_loss_kwh / p1.daily_energy_served_kwh:,.0f})"
    )
    daily_cost = p1.daily_energy_loss_kwh * b.params.energy_price_cop_per_kwh
    print(f"  Costo diario pérdidas (b) = {format_cop(daily_cost)} (E_loss × 960 COP/kWh)")
    print(f"  Costo anual pérdidas      = {format_cop(daily_cost * b.params.days_per_year)}")

    f = b.feasibility
    _rule("ANÁLISIS DE FACTIBILIDAD |V_gen| ∈ [950, 1100] V (Problema 2, Q_C fijo)")
    df = f.to_dataframe()[["hour", "conjunto_analitico"]]
    for _, r in df.iterrows():
        print(f"  h{int(r.hour):02d}: Q_C ∈ {r.conjunto_analitico}")
    print(f"\n  Verificación numérica (malla + brentq): desviación máx = {f.max_numeric_deviation_kvar:.2e} kvar")
    print(
        f"  Intersección global 24 h: {format_set(f.global_set)}  →  "
        f"{'FACTIBLE' if f.is_feasible else 'INFACTIBLE (vacía)'}"
    )
    print(f"  Pares de horas en conflicto: {list(f.conflicting_pairs)}  | par crítico: {f.critical_pair}")

    _rule("COMPARATIVA DE ESTRATEGIAS (Problema 2)")
    table = b.comparison_table()
    show = pd.DataFrame(
        {
            "Estrategia": table["Estrategia"],
            "Q_C inst [kvar]": table["Q_C_instalado_kvar"].map(lambda x: f"{x:.3f}"),
            "I_line máx [A]": table["I_line_max_A"].map(lambda x: f"{x:.3f}"),
            "E_loss [kWh/d]": table["E_loss_kWh_dia"].map(lambda x: f"{x:.3f}"),
            "J anual [MCOP]": (table["Costo_total_anual_COP"] / 1e6).map(lambda x: f"{x:.3f}"),
            "Ahorro [MCOP/a]": (table["Ahorro_anual_COP"] / 1e6).map(lambda x: f"{x:.3f}"),
            "Payback [d]": table["Payback_dias"].map(lambda x: f"{x:.1f}"),
            "|Vg| min-max [V]": [
                f"{a:.1f}–{c:.1f}" for a, c in zip(table["V_gen_min_V"], table["V_gen_max_V"], strict=True)
            ],
            "h fuera": table["Horas_fuera_banda"],
            "Viol máx [V]": table["Violacion_max_V"].map(lambda x: f"{x:.2f}"),
            "fp neto mín–máx": [
                f"{a:.3f}–{c:.3f}" for a, c in zip(table["fp_neto_min"], table["fp_neto_max"], strict=True)
            ],
            "Estado fp (24 h)": table["Estado_fp_24h"],
        }
    )
    with pd.option_context("display.width", 300, "display.max_columns", 20):
        print(show.to_string(index=False))

    e = b.economic
    _rule("ÓPTIMO ECONÓMICO FIJO")
    print(
        f"  Q_C* (cerrado) = {e.q_c_closed_form_kvar:.6f} kvar | Q_C* (minimize_scalar) = "
        f"{e.q_c_numeric_kvar:.6f} kvar | dJ/dQ_C(Q_C*) = {e.derivative_at_optimum:.2e}"
    )
    ec = e.result.economics
    print(
        f"  CAPEX = {format_cop(ec.capex_cop)} | OPEX = {format_cop(ec.annual_loss_cost_cop)} | "
        f"Ahorro = {format_cop(ec.annual_savings_cop)}"
    )
    print(
        f"  Payback = {ec.payback_months:.3f} meses = {ec.payback_days:.2f} días | ROI 1/3/5 a = "
        + " / ".join(f"{format_number(v, 1)} %" for v in ec.roi_table.values())
    )

    par = b.pareto
    _rule("COMPROMISO PARETO (banco fijo)")
    print(
        f"  Q_C minimax = {par.minimax.q_c_installed_kvar:.4f} kvar → violación máx = "
        f"{par.minimax.max_violation_v:.3f} V, RMS = {par.minimax.rms_violation_v:.3f} V, "
        f"{par.minimax.hours_out_of_band} h fuera de banda, "
        f"J = {format_cop(par.minimax.economics.total_annual_cost_cop)}"
    )
    print(f"  Puntos en la frontera de Pareto: {len(par.front)}")

    sw = b.switched
    _rule("BANCO AUTOMÁTICO POR PASOS (100 % factible)")
    print(
        f"  Instalado: {sw.n_steps} × {sw.step_kvar:g} kvar = {sw.q_c_max_kvar:g} kvar "
        f"(cota inferior técnica = {sw.q_c_max_lower_bound_kvar:.3f} kvar)"
    )
    se = sw.result.economics
    print(
        f"  CAPEX = {format_cop(se.capex_cop)} | Ahorro = {format_cop(se.annual_savings_cop)} | "
        f"Payback = {se.payback_days:.1f} días | ROI 5 a = {format_number(se.roi_pct(5), 1)} %"
    )
    print("  Programa horario Q_C(t) [kvar]: " + ", ".join(f"{q:g}" for q in sw.result.q_c_profile_kvar))

    fl, sl, lag = b.fixed_lagging, b.switched_lagging, b.lagging_limit
    _rule("REQUISITO fp NETO EN ATRASO (Q_net(t) = Q(t) − Q_C(t) ≥ 0)")
    print(
        f"  Banco fijo en atraso: Q_C ≤ min Q(t) = {fl.q_c_upper_bound_kvar:.4f} kvar (hora {fl.binding_hour}); "
        f"óptimo libre {fl.q_c_unconstrained_kvar:.4f} → Q_C* = {fl.q_c_closed_form_kvar:.4f} kvar "
        f"(numérico {fl.q_c_numeric_kvar:.6f}); {fl.result.hours_out_of_band} h fuera de banda"
    )
    print(
        f"  Banco por pasos en atraso: {sl.n_steps} × {sl.step_kvar:g} kvar; J = "
        f"{format_cop(sl.result.economics.total_annual_cost_cop)}; {sl.result.hours_out_of_band} h fuera de banda"
    )
    print("  Programa horario Q_C(t) [kvar]: " + ", ".join(f"{q:g}" for q in sl.result.q_c_profile_kvar))
    print(
        f"  Teorema: máx_t mín_(0≤Q_C≤Q) |V_gen| = {lag.max_floor_v:.4f} V en la hora {lag.worst_hour} "
        f"(Q_net = 0, fp = 1) > {lag.v_gen_max_allowed:g} V; banda alcanzable en atraso en "
        f"{lag.hours_band_reachable_lagging}/24 h"
    )

    if b.sensitivity is not None:
        _rule("SENSIBILIDAD X_line — rangos con banco FIJO factible")
        print(f"  Rangos factibles de X_line: {format_set(b.sensitivity.feasible_ranges)} Ω")
        print(f"  X_line crítica (al reducir desde 900 Ω): {b.sensitivity.x_critical_upper:.4f} Ω")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print_report(run_full_analysis())
