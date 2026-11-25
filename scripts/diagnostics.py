"""Diagnóstico en consola: Problema 1, Problema 2, Problema 2.1 (línea a 66 kV) y comparación 2 vs. 2.1."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.optimization.capacitor_optimizer import format_set  # noqa: E402
from src.optimization.comparison import comparison_table, format_comparison  # noqa: E402
from src.optimization.economics import format_cop, format_number  # noqa: E402
from src.optimization.pipeline import AnalysisBundle, run_full_analysis, run_problem_2_1  # noqa: E402


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
            "Payback [d]": table["Payback_dias"].map(lambda x: f"{x:.1f}" if np.isfinite(x) else "no se recupera"),
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
    r, free, nc = e.result, e.free, b.no_capacitor
    ec = r.economics
    _rule(f"BANCO FIJO — ÓPTIMO ECONÓMICO (Q_C = {e.q_c_design_kvar:g} kvar)")
    print(
        f"  Máximo de horas en banda con un banco fijo: {e.band.hours_in_band}/24, para Q_C ∈ "
        f"{format_set(e.band.window)} kvar"
    )
    print(
        f"  Mínimo de J en esa ventana = {e.q_c_band_optimum_kvar:.6f} kvar → adoptado {e.q_c_design_kvar:g} kvar "
        f"(dJ/dQ_C = {e.derivative_at_design:,.0f} COP/kvar)"
    )
    print(
        f"  |V_gen| ∈ [{r.v_gen_mag.min():.3f}, {r.v_gen_mag.max():.3f}] V | fuera de banda: horas {list(e.hours_out)} "
        f"(máx {r.max_violation_v:.3f} V) | fp neto {r.pf_net.min():.4f}–{r.pf_net.max():.4f}, {r.pf_status}"
    )
    print(
        f"  |I_line| ∈ [{np.abs(r.circuit.i_line).min():.4f}, {np.abs(r.circuit.i_line).max():.4f}] A | "
        f"E_loss = {ec.daily_loss_kwh:,.4f} kWh/día ({r.circuit.p_loss_line_kw.sum():,.4f} línea + "
        f"{r.circuit.p_loss_gen_kw.sum():,.4f} generador)"
    )
    print(
        f"  CAPEX = {format_cop(ec.capex_cop)} | OPEX = {format_cop(ec.annual_loss_cost_cop)} | "
        f"J = {format_cop(ec.total_annual_cost_cop)} | Ahorro vs Q_C = 0 = {format_cop(ec.annual_savings_cop)}"
    )
    payback = "no se recupera" if not np.isfinite(ec.payback_days) else f"{ec.payback_days:.2f} días"
    print(
        f"  Payback = {payback} | ROI 1/3/5 a = "
        + " / ".join(f"{format_number(v, 1)} %" for v in ec.roi_table.values())
    )

    _rule("OBSERVACIONES MATEMÁTICAS")
    print(
        f"  1. Mínimo libre de J(Q_C): {e.q_c_free_kvar:.6f} kvar (cerrado) = {e.q_c_free_numeric_kvar:.6f} kvar "
        f"(minimize_scalar), dJ/dQ_C = {e.derivative_at_free:.2e}; J = "
        f"{format_cop(free.economics.total_annual_cost_cop)}, pero {free.hours_out_of_band} h fuera de banda."
    )
    print(
        f"  2. J({e.q_c_design_kvar:g}) = {ec.total_annual_cost_cop / free.economics.total_annual_cost_cop:.2f} × "
        f"J(mínimo libre) = {ec.total_annual_cost_cop / nc.economics.total_annual_cost_cop:.2f} × J(0): el banco "
        f"sobrecompensa las {r.hours_leading} h y las pérdidas suben de {nc.economics.daily_loss_kwh:,.2f} a "
        f"{ec.daily_loss_kwh:,.2f} kWh/día."
    )
    print(
        f"  3. Ningún banco fijo cumple la banda las 24 h; {e.q_c_design_kvar:g} kvar deja fuera la hora "
        f"{', '.join(map(str, e.hours_out))} y el margen mínimo dentro de la banda es "
        f"{np.min(np.where(r.violation_v <= 1e-6, r.v_gen_mag - b.params.v_gen_min, np.inf)):.4f} V."
    )

    if b.sensitivity is not None:
        _rule("SENSIBILIDAD X_line — rangos con banco FIJO factible")
        print(f"  Rangos factibles de X_line: {format_set(b.sensitivity.feasible_ranges)} Ω")
        print(f"  X_line crítica (al reducir desde 900 Ω): {b.sensitivity.x_critical_upper:.4f} Ω")


def print_report_21(b21: AnalysisBundle, b2: AnalysisBundle) -> None:
    """Resultados del Problema 2.1 y tabla comparativa con el Problema 2."""
    p, e, nc = b21.params, b21.economic, b21.no_capacitor
    r, free = e.result, e.free
    ec, e0 = r.economics, nc.economics
    days = p.days_per_year
    _rule(f"PROBLEMA 2.1 — T1 = {p.t1_label}, T2 = {p.t2_label} (lo demás, igual al Problema 2)")
    z_line = p.z_line / p.n1**2
    print(f"  n1 = {p.n1:g} | a2 = {p.a2:g} | V_0 referida al generador = {abs(p.v_load_gen_side):,.1f} V")
    print(
        f"  Z_line/n1² = {z_line.real:.6f} + j{z_line.imag:.6f} Ω | Z vista por el generador = "
        f"{p.z_gen_side.real:.6f} + j{p.z_gen_side.imag:.6f} Ω | R_eq referida a la línea = {p.r_eq_line_side:,.2f} Ω"
    )
    print(
        f"  Q_C = 0: |V_gen| ∈ [{nc.v_gen_mag.min():.3f}, {nc.v_gen_mag.max():.3f}] V, {nc.hours_out_of_band} h fuera "
        f"de banda | |I_line| máx = {np.abs(nc.circuit.i_line).max():.4f} A | "
        f"E_loss = {e0.daily_loss_kwh:,.4f} kWh/día → {format_cop(e0.annual_loss_cost_cop)}/año"
    )
    f = b21.feasibility
    print(
        f"  Intersección 24 h: {format_set(f.global_set)} kvar → {'FACTIBLE' if f.is_feasible else 'INFACTIBLE'} | "
        f"máximo {e.band.hours_in_band}/24 h para Q_C ∈ {format_set(e.band.window)}"
    )
    print(
        f"  Mínimo libre de J = {e.q_c_free_kvar:.6f} kvar ({free.hours_out_of_band} h fuera, "
        f"{free.max_violation_v:.4f} V) | mínimo en la ventana = {e.q_c_band_optimum_kvar:.6f} kvar → "
        f"adoptado {e.q_c_design_kvar:g} kvar"
    )
    print(
        f"  Q_C = {e.q_c_design_kvar:g} kvar: |V_gen| ∈ [{r.v_gen_mag.min():.3f}, {r.v_gen_mag.max():.4f}] V, "
        f"{24 - r.hours_out_of_band}/24 h en banda | |I_line| ∈ [{np.abs(r.circuit.i_line).min():.4f}, "
        f"{np.abs(r.circuit.i_line).max():.4f}] A | fp neto {r.pf_net.min():.4f}–{r.pf_net.max():.4f}, {r.pf_status}"
    )
    print(
        f"  E_loss = {ec.daily_loss_kwh:,.4f} kWh/día ({r.circuit.p_loss_line_kw.sum():,.4f} línea + "
        f"{r.circuit.p_loss_gen_kw.sum():,.4f} generador) = {ec.daily_loss_kwh * days:,.1f} kWh/año"
    )
    print(
        f"  CAPEX = {format_cop(ec.capex_cop)} | OPEX = {format_cop(ec.annual_loss_cost_cop)} | "
        f"J = {format_cop(ec.total_annual_cost_cop)} | Ahorro vs Q_C = 0 = {format_cop(ec.annual_savings_cop)}"
    )
    print(
        f"  Payback = {ec.payback_days:.2f} días | ROI 1/3/5 a = "
        + " / ".join(f"{format_number(v, 1)} %" for v in ec.roi_table.values())
    )

    _rule(f"COMPARACIÓN — {b2.title} vs. {b21.title}")
    with pd.option_context("display.width", 300, "display.max_columns", 10, "display.max_rows", 100):
        print(format_comparison(comparison_table(b2, b21)).to_string(index=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    bundle = run_full_analysis()
    print_report(bundle)
    print_report_21(run_problem_2_1(bundle.demand), bundle)
