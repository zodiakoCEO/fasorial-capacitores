"""Comparación directa entre dos casos del Problema 2 con distinta tensión de línea.

Problema 2:   T1 = 1 kV : 13.2 kV,  T2 = 13.2 kV : 120 V
Problema 2.1: T1 = 1 kV : 66 kV,    T2 = 66 kV : 120 V

Cada caso se resume con su banco fijo adoptado (y la referencia sin capacitor) en las mismas magnitudes,
de modo que la tabla contrasta columna contra columna.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src.optimization.economics import format_cop
from src.optimization.pipeline import AnalysisBundle

RATIO_COLUMN = "Relación 2.1 / 2"


def case_metrics(b: AnalysisBundle) -> dict[str, tuple[str, float | str]]:
    """Magnitudes de un caso: nombre → (unidad, valor). El orden es el de la tabla comparativa."""
    prm, r, nc = b.params, b.economic.result, b.no_capacitor
    e, e0 = r.economics, nc.economics
    c = r.circuit
    i_line, i_gen = np.abs(c.i_line), np.abs(c.i_gen)
    days = prm.days_per_year
    lead = r.hours_leading
    return {
        "Transformador T1": ("", prm.t1_label),
        "Transformador T2": ("", prm.t2_label),
        "Tensión de línea": ("kV", prm.line_kv),
        "Relación n1 (T1)": ("", prm.n1),
        "Relación a2 (T2)": ("", prm.a2),
        "R total vista por el generador": ("Ω", prm.z_gen_side.real),
        "X total vista por el generador": ("Ω", prm.z_gen_side.imag),
        "Q_C del banco fijo": ("kvar", r.q_c_installed_kvar),
        "|I_line| máx": ("A", float(i_line.max())),
        "|I_line| promedio": ("A", float(i_line.mean())),
        "|I_gen| máx": ("A", float(i_gen.max())),
        "|V_gen| mín": ("V", float(r.v_gen_mag.min())),
        "|V_gen| máx": ("V", float(r.v_gen_mag.max())),
        "Horas dentro de [950, 1100] V": ("h", 24 - r.hours_out_of_band),
        "Horas fuera de [950, 1100] V": ("h", r.hours_out_of_band),
        "Violación máxima de tensión": ("V", r.max_violation_v),
        "fp neto mín": ("", float(r.pf_net.min())),
        "fp neto máx": ("", float(r.pf_net.max())),
        "Horas con fp en adelanto": ("h", lead),
        "Pérdidas diarias": ("kWh/día", e.daily_loss_kwh),
        "Pérdidas diarias en la línea": ("kWh/día", float(c.p_loss_line_kw.sum())),
        "Pérdidas diarias en el generador": ("kWh/día", float(c.p_loss_gen_kw.sum())),
        "Pérdidas anuales": ("kWh/año", e.daily_loss_kwh * days),
        "Costo de pérdidas por día": ("COP/día", e.daily_loss_kwh * prm.energy_price_cop_per_kwh),
        "Costo de pérdidas por año (OPEX)": ("COP/año", e.annual_loss_cost_cop),
        "CAPEX del banco": ("COP", e.capex_cop),
        "Costo total anual J": ("COP/año", e.total_annual_cost_cop),
        "Ahorro anual frente a Q_C = 0": ("COP/año", e.annual_savings_cop),
        "Payback": ("días", e.payback_days),
        "ROI a 5 años": ("%", e.roi_pct(5)),
        "Sin capacitor: |V_gen| máx": ("V", float(nc.v_gen_mag.max())),
        "Sin capacitor: horas dentro de la banda": ("h", 24 - nc.hours_out_of_band),
        "Sin capacitor: |I_line| máx": ("A", float(np.abs(nc.circuit.i_line).max())),
        "Sin capacitor: pérdidas diarias": ("kWh/día", e0.daily_loss_kwh),
        "Sin capacitor: costo de pérdidas por año": ("COP/año", e0.annual_loss_cost_cop),
    }


def _ratio(a: float | str, b: float | str) -> float:
    """b / a cuando ambos son números finitos, a > 0 y b ≥ 0; NaN en otro caso (p. ej. ahorros de signo opuesto)."""
    if isinstance(a, str) or isinstance(b, str):
        return math.nan
    if not (math.isfinite(a) and math.isfinite(b)) or a <= 0 or b < 0:
        return math.nan
    return float(b) / float(a)


def comparison_table(b2: AnalysisBundle, b21: AnalysisBundle) -> pd.DataFrame:
    """Tabla comparativa: Magnitud, Unidad, valor en cada caso y relación (2.1 / 2)."""
    m2, m21 = case_metrics(b2), case_metrics(b21)
    rows = []
    for name, (unit, v2) in m2.items():
        v21 = m21[name][1]
        rows.append({"Magnitud": name, "Unidad": unit, b2.name: v2, b21.name: v21, RATIO_COLUMN: _ratio(v2, v21)})
    return pd.DataFrame(rows)


def comparison_value(table: pd.DataFrame, magnitude: str, column: str) -> float | str:
    """Valor de una celda de la tabla comparativa por nombre de magnitud."""
    return table.loc[table["Magnitud"] == magnitude, column].iloc[0]


def _format_value(name: str, unit: str, value: float | str) -> str:
    if isinstance(value, str):
        return value
    if unit.startswith("COP"):
        return format_cop(value)
    if unit == "días":
        return "no se recupera" if not math.isfinite(value) else f"{value:,.1f}"
    if unit == "h":
        return f"{int(value)}"
    if unit == "kWh/año":
        return f"{value:,.0f}"
    if unit in ("kWh/día", "V", "kvar"):
        return f"{value:,.2f}"
    if unit in ("A", "Ω"):
        return f"{value:,.4f}"
    if unit == "%":
        return f"{value:,.1f}"
    if name.startswith("fp"):
        return f"{value:.3f}"
    return f"{value:g}"


def format_comparison(table: pd.DataFrame) -> pd.DataFrame:
    """Tabla comparativa con los valores ya formateados como texto (para el dashboard y el reporte)."""
    cases = [c for c in table.columns if c not in ("Magnitud", "Unidad", RATIO_COLUMN)]
    out = {"Magnitud": table["Magnitud"], "Unidad": table["Unidad"]}
    for case in cases:
        out[case] = [
            _format_value(n, u, v) for n, u, v in zip(table["Magnitud"], table["Unidad"], table[case], strict=True)
        ]
    out[RATIO_COLUMN] = ["—" if not math.isfinite(x) else f"×{x:,.3f}" for x in table[RATIO_COLUMN]]
    return pd.DataFrame(out)


__all__ = ["RATIO_COLUMN", "case_metrics", "comparison_table", "comparison_value", "format_comparison"]
