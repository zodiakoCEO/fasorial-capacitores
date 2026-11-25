"""Exportación de entregables: PNG (Matplotlib, 300 DPI), tablas CSV y reporte Markdown."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from src.domain.models import Strategy
from src.optimization.capacitor_optimizer import StrategyResult, format_set
from src.optimization.comparison import comparison_table, format_comparison
from src.optimization.economics import cumulative_cash_flow, format_cop, format_number
from src.optimization.pipeline import CASE_2, AnalysisBundle
from src.physics.circuit_solver import affine_voltage_model
from src.physics.step_by_step import hourly_step_table, power_balance_error
from src.reporting import theme as T
from src.reporting.analysis_text import (
    comparison_synthesis,
    problem1_analysis,
    problem2_analysis,
    problem21_analysis,
)
from src.reporting.charts import nice_current_scale, pf_label, phasor_components

DPI = 300
TEACHING_HOUR = 12  # hora pico usada en las figuras docentes
NL = chr(10)

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Segoe UI", "Arial"],
        "font.size": 10,
        "axes.edgecolor": "#c3c2b7",
        "axes.labelcolor": T.INK_SECONDARY,
        "axes.titleweight": "bold",
        "axes.titlesize": 12,
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": "#e1e0d9",
        "grid.linewidth": 0.8,
        "xtick.color": T.MUTED,
        "ytick.color": T.MUTED,
        "legend.frameon": False,
        "figure.facecolor": T.SURFACE,
        "axes.facecolor": T.SURFACE,
        "savefig.facecolor": T.SURFACE,
    }
)


# ==================================================================================
# Helpers
# ==================================================================================
def _hours_axis(ax: Axes) -> None:
    ax.set_xlim(0.5, 24.5)
    ax.set_xticks(range(1, 25, 2))
    ax.set_xlabel("Hora del día t")


def _plot_line(ax: Axes, x: np.ndarray, y: np.ndarray, label: str, color: str, dash: str = "solid") -> None:
    ls = {"solid": "-", "dash": "--", "dot": ":", "dashdot": "-.", "longdash": (0, (8, 3))}[dash]
    ax.plot(x, y, linestyle=ls, color=color, lw=2, marker="o", ms=4, mec=T.SURFACE, mew=1, label=label)


def _new(figsize: tuple[float, float] = (8, 4.2)) -> tuple[Figure, Axes]:
    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    return fig, ax


@dataclass(frozen=True, slots=True)
class ChartSpec:
    filename: str
    title: str
    comment: str
    builder: Callable[[AnalysisBundle], Figure]


# ==================================================================================
# Figuras
# ==================================================================================
def _p1_current(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    _plot_line(ax, b.problem1.hours, np.abs(b.problem1.i_line), "|I_line| Problema 1", T.SERIES[0])
    ax.set_title("Problema 1 — Corriente de línea |I_line(t)| a 120 V")
    ax.set_ylabel("|I_line| [A]")
    _hours_axis(ax)
    i_max = int(np.argmax(np.abs(b.problem1.i_line)))
    ax.annotate(
        f"máx {np.abs(b.problem1.i_line[i_max]):,.0f} A (h{i_max + 1})",
        (i_max + 1, np.abs(b.problem1.i_line[i_max])),
        textcoords="offset points",
        xytext=(-10, 8),
        ha="right",
        color=T.INK_SECONDARY,
    )
    return fig


def _p1_losses(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    p1 = b.problem1
    ax.bar(p1.hours, p1.p_loss_kw / 1e3, color=T.SERIES[0], width=0.72, edgecolor=T.SURFACE, lw=1, label="P_loss")
    ax.plot(p1.hours, p1.s_load_kva.real / 1e3, color=T.SERIES[1], lw=2, marker="o", ms=4, label="P carga (útil)")
    ax.set_yscale("log")
    ax.set_title("Problema 1 — Pérdidas activas vs. potencia útil (escala log)")
    ax.set_ylabel("Potencia [MW]")
    ax.legend(loc="upper left", ncols=2)
    _hours_axis(ax)
    return fig


def _p1_sgen(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    p1 = b.problem1
    _plot_line(ax, p1.hours, np.abs(p1.s_gen_kva) / 1e3, "|S_gen|", T.SERIES[0])
    ax.set_title("Problema 1 — Potencia aparente del generador |S_gen(t)|")
    ax.set_ylabel("|S_gen| [MVA]")
    _hours_axis(ax)
    return fig


def _demand(b: AnalysisBundle) -> Figure:
    d = b.demand
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for ax, (v1, v2), unit, title in (
        (axes[0], (d.p1_kw, d.p2_kw), "kW", "Potencia activa P"),
        (axes[1], (d.q1_kvar, d.q2_kvar), "kvar", "Potencia reactiva Q"),
    ):
        ax.bar(d.hours, v1, color=T.SERIES[0], width=0.72, edgecolor=T.SURFACE, lw=1, label="L1 Residencial")
        ax.bar(d.hours, v2, bottom=v1, color=T.SERIES[1], width=0.72, edgecolor=T.SURFACE, lw=1, label="L2 Industrial")
        ax.set_title(f"{title} [{unit}]")
        _hours_axis(ax)
    axes[0].legend(loc="upper left")
    fig.suptitle("Perfil de demanda 24 h — desglose residencial vs. industrial", x=0.01, ha="left", fontweight="bold")
    return fig


def _p1_vs_p2(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    _plot_line(ax, b.problem1.hours, np.abs(b.problem1.i_line), "Problema 1 (120 V directo)", T.SERIES[0])
    _plot_line(ax, b.problem1.hours, np.abs(b.no_capacitor.circuit.i_line), "Problema 2 (línea 13.2 kV)", T.SERIES[1])
    ax.set_yscale("log")
    ax.set_title("Corriente de línea: efecto de elevar la tensión (×110)")
    ax.set_ylabel("|I_line| [A] (log)")
    ax.legend(loc="center right")
    _hours_axis(ax)
    return fig


def _strategies(b: AnalysisBundle) -> list[StrategyResult]:
    return list(b.strategies.values())


def _vgen(b: AnalysisBundle) -> Figure:
    fig, ax = _new((9, 5.6))
    p = b.params
    ax.axhspan(p.v_gen_min, p.v_gen_max, color=T.GOOD, alpha=0.12, lw=0)
    for lim in (p.v_gen_min, p.v_gen_max):
        ax.axhline(lim, color=T.GOOD, lw=1, ls=":")
    ax.text(24.4, p.v_gen_min + 10, "banda admisible [950, 1100] V", color=T.GOOD, fontsize=8.5, ha="right")
    for r in _strategies(b):
        color, dash = T.STRATEGY_COLOR[r.strategy], T.STRATEGY_DASH[r.strategy]
        _plot_line(ax, r.circuit.hours, r.v_gen_mag, r.label, color, dash)
        out = r.violation_v > 1e-6
        ax.scatter(r.circuit.hours[out], r.v_gen_mag[out], marker="x", s=22, color=T.CRITICAL, lw=1.2, zorder=5)
    ax.set_title(f"{b.name} — |V_gen(t)|: sin capacitor vs. banco fijo (× rojo = fuera de banda)")
    ax.set_ylabel("|V_gen| [V]")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), fontsize=7.5, ncols=2)
    _hours_axis(ax)
    return fig


def _losses_stacked(b: AnalysisBundle) -> Figure:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True, constrained_layout=True)
    for ax, r in zip(axes, (b.no_capacitor, b.economic.result), strict=True):
        c = r.circuit
        ax.bar(
            c.hours, c.p_loss_line_kw, color=T.SERIES[0], width=0.72, edgecolor=T.SURFACE, lw=1, label="Línea (80 Ω)"
        )
        ax.bar(
            c.hours,
            c.p_loss_gen_kw,
            bottom=c.p_loss_line_kw,
            color=T.SERIES[1],
            width=0.72,
            edgecolor=T.SURFACE,
            lw=1,
            label="Generador (0.5 Ω)",
        )
        ax.set_title(f"{r.label}\nE_loss = {c.daily_energy_loss_kwh:,.1f} kWh/día", fontsize=10)
        _hours_axis(ax)
    axes[0].set_ylabel("P_loss [kW]")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper right", ncols=2, fontsize=9)
    fig.suptitle(f"{b.name} — Pérdidas activas apiladas (línea vs. generador)", x=0.01, ha="left", fontweight="bold")
    return fig


def _cost_curve(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    g = b.scan[b.scan["Q_C_kvar"] <= 480]
    ax.plot(g["Q_C_kvar"], g["Costo_total_anual_COP"] / 1e6, color=T.SERIES[0], lw=2, label="J(Q_C)")
    eco = b.economic
    for iv in eco.band.window:
        ax.axvspan(iv.lo, min(iv.hi, 480.0), color=T.GOOD, alpha=0.15, lw=0)
    close = abs(eco.q_c_design_kvar - eco.q_c_free_kvar) < 25.0  # etiquetas apiladas si los puntos casi coinciden
    points = (
        (
            eco.result,
            f"Banco fijo adoptado\n{eco.q_c_design_kvar:g} kvar",
            T.SERIES[1],
            (40, 62) if close else (-12, 8),
            "left" if close else "right",
        ),
        (
            eco.free,
            f"Mínimo libre de J\n{eco.q_c_free_kvar:.2f} kvar",
            T.SERIES[6],
            (40, 14) if close else (12, 14),
            "left",
        ),
    )
    for r, name, color, offset, ha in points:
        j = r.economics.total_annual_cost_cop / 1e6
        ax.scatter([r.q_c_installed_kvar], [j], s=60, zorder=5, color=color, edgecolor=T.SURFACE, lw=1.5)
        ax.annotate(
            f"{name}\nJ = {j:,.2f} M",
            (r.q_c_installed_kvar, j),
            textcoords="offset points",
            xytext=offset,
            ha=ha,
            fontsize=8.5,
            color=T.INK_SECONDARY,
        )
    ax.set_title(f"{b.name} — Costo total anual J(Q_C) = OPEX pérdidas + CAPEX")
    ax.set_xlabel(f"Q_C [kvar]  (franja verde: {eco.band.hours_in_band}/24 h dentro de la banda de tensión)")
    ax.set_ylabel("J [millones COP/año]")
    return fig


def _feasibility_map(b: AnalysisBundle) -> Figure:
    fig, ax = _new((9, 4.8))
    f = b.feasibility
    for h, s in zip(f.hours, f.hourly_sets, strict=True):
        for k, iv in enumerate(s):
            ax.bar(h, iv.width, bottom=iv.lo, width=0.6, color=T.GOOD, alpha=0.85 if k == 0 else 0.4, lw=0)
    q = b.economic.q_c_design_kvar
    ax.axhline(q, color=T.SERIES[1], lw=2, label=f"Banco fijo — óptimo económico ({q:g} kvar)")
    ax.set_ylim(0, 480)
    ax.set_title(f"{b.name} — Mapa de factibilidad: Q_C con 950 ≤ |V_gen| ≤ 1100 V (verde)")
    ax.set_ylabel("Q_C [kvar]")
    ax.legend(loc="upper left", fontsize=8)
    _hours_axis(ax)
    return fig


def _band_hours(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    eco = b.economic
    ax.fill_between(b.scan["Q_C_kvar"], b.scan["Horas_en_banda"], step="post", color=T.SERIES[0], alpha=0.15, lw=0)
    ax.step(b.scan["Q_C_kvar"], b.scan["Horas_en_banda"], where="post", color=T.SERIES[0], lw=2)
    ax.scatter(
        [eco.q_c_design_kvar], [eco.band.hours_in_band], s=60, zorder=5, color=T.SERIES[1], edgecolor=T.SURFACE, lw=1.5
    )
    ax.annotate(
        f"{eco.q_c_design_kvar:g} kvar → {eco.band.hours_in_band}/24 h",
        (eco.q_c_design_kvar, eco.band.hours_in_band),
        textcoords="offset points",
        xytext=(-10, 4),
        ha="right",
        fontsize=8.5,
        color=T.INK,
    )
    ax.set_ylim(0, 25.5)
    ax.set_yticks(range(0, 25, 4))
    ax.set_title("Horas dentro de [950, 1100] V según el Q_C fijo instalado")
    ax.set_xlabel("Q_C [kvar]")
    ax.set_ylabel("Horas en banda (de 24)")
    return fig


def _triangle(b: AnalysisBundle) -> Figure:
    t = TEACHING_HOUR - 1
    p, ql = b.demand.p_total_kw[t], b.demand.q_total_kvar[t]
    qc = b.economic.result.q_c_profile_kvar[t]
    qn = ql - qc
    fig, ax = _new((6.5, 6))
    ax.grid(False)
    arrow = {"arrowstyle": "-|>", "lw": 2.2, "mutation_scale": 14}
    ax.annotate("", (p, 0), (0, 0), arrowprops={**arrow, "color": T.SERIES[0]})
    ax.annotate("", (p, ql), (p, 0), arrowprops={**arrow, "color": T.SERIES[1]})
    ax.annotate("", (p * 1.04, qn), (p * 1.04, ql), arrowprops={**arrow, "color": T.SERIES[2]})
    ax.annotate("", (p, ql), (0, 0), arrowprops={**arrow, "color": T.MUTED, "ls": "--"})
    ax.annotate("", (p, qn), (0, 0), arrowprops={**arrow, "color": T.SERIES[6]})
    ax.text(p / 2, -12, f"P = {p:.1f} kW", ha="center", va="top", color=T.INK)
    ax.text(p * 1.02, ql / 2, f"Q_L = {ql:.1f} kvar", color=T.INK)
    ax.text(p * 1.08, (ql + qn) / 2, f"−Q_C = −{qc:.2f} kvar", color=T.INK)
    ax.text(
        p * 0.05,
        ql * 0.95,
        f"S antes = {np.hypot(p, ql):.1f} kVA\nfp = {p / np.hypot(p, ql):.3f} at.",
        color=T.INK_SECONDARY,
        ha="left",
        va="top",
    )
    ax.text(
        p * 0.05,
        qn * 0.75,
        f"S después = {np.hypot(p, qn):.1f} kVA\nfp = {p / np.hypot(p, qn):.3f} {'ad.' if qn < 0 else 'at.'}",
        color=T.INK_SECONDARY,
        va="top",
    )
    lim = max(abs(ql), abs(qn), p) * 1.2
    ax.set_xlim(-0.1 * lim, lim * 1.25)
    ax.set_ylim(min(qn, 0) - 0.25 * lim, max(ql, 0) + 0.15 * lim)
    ax.set_aspect("equal")
    ax.axhline(0, color="#c3c2b7", lw=0.8)
    ax.set_xlabel("P [kW]")
    ax.set_ylabel("Q [kvar]")
    ax.set_title(f"Triángulo de potencias — h{TEACHING_HOUR}, Q_C = {qc:g} kvar")
    return fig


def _phasor(b: AnalysisBundle) -> Figure:
    t = TEACHING_HOUR - 1
    cases = (b.no_capacitor, b.economic.result)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.4), constrained_layout=True)
    lim, i_max = 0.0, 0.0
    for r in cases:
        ph = phasor_components(r.circuit, b.params, t, b.demand)
        lim = max(lim, abs(ph["V_gen"]), abs(ph["V0_ref"] + ph["drop"]))
        i_max = max(i_max, abs(ph["I_gen"]))
    scale = nice_current_scale(i_max)
    lim *= 1.08
    for ax, r in zip(axes, cases, strict=True):
        ph = phasor_components(r.circuit, b.params, t, b.demand)
        ax.grid(False)
        th = np.linspace(0, np.pi, 200)
        for rad in (b.params.v_gen_min, b.params.v_gen_max):
            ax.plot(rad * np.cos(th), rad * np.sin(th), ":", color=T.GOOD, lw=1)

        def arr(z0: complex, z1: complex, color: str, ls: str = "-", lw: float = 2.2, ax: Axes = ax) -> None:
            ax.annotate(
                "",
                (z1.real, z1.imag),
                (z0.real, z0.imag),
                arrowprops={"arrowstyle": "-|>", "color": color, "lw": lw, "ls": ls, "mutation_scale": 13},
            )

        v0, d, vg = ph["V0_ref"], ph["drop"], ph["V_gen"]
        arr(0, v0, T.SERIES[0])
        arr(v0, v0 + ph["drop_R"], T.SERIES[1], ":", 1.8)
        arr(v0 + ph["drop_R"], v0 + d, T.SERIES[4], ":", 1.8)
        arr(0, vg, T.SERIES[2])
        arr(0, ph["I_gen"] * scale, T.SERIES[6], "-", 1.8)
        ax.text(v0.real * 0.5, -40, "V₀·a₂/n₁ = 1000∠0° V", color=T.INK, ha="center", va="top", fontsize=8.5)
        ax.text(
            vg.real * 0.5 - 30,
            vg.imag * 0.55 + 20,
            f"V_gen = {abs(vg):,.1f}∠{np.degrees(np.angle(vg)):.1f}° V",
            color=T.INK,
            fontsize=8.5,
            ha="right",
        )
        ax.text(
            (v0 + d).real,
            (v0 + d).imag + 15,
            f"jI·X/n₁ ({abs(ph['drop_X']):,.0f} V)",
            fontsize=8.5,
            color=T.INK_SECONDARY,
        )
        ig = ph["I_gen"] * scale
        ax.text(
            ig.real,
            ig.imag - 30,
            f"I_gen×{scale:g} ({abs(ph['I_gen']):.2f} A ∠{np.degrees(np.angle(ph['I_gen'])):.1f}°)",
            fontsize=8.5,
            color=T.INK_SECONDARY,
            va="top",
        )
        ax.set_xlim(-0.75 * lim, 1.05 * lim)
        ax.set_ylim(-0.45 * lim, 0.95 * lim)
        ax.set_aspect("equal")
        ax.axhline(0, color="#c3c2b7", lw=0.8)
        ax.axvline(0, color="#c3c2b7", lw=0.8)
        ax.set_title(f"{r.label} — Q_C = {r.q_c_profile_kvar[t]:g} kvar", fontsize=10)
        ax.set_xlabel("Re [V]")
    axes[0].set_ylabel("Im [V]")
    fig.suptitle(
        f"Diagrama fasorial referido al generador — hora {TEACHING_HOUR} (arcos verdes: 950 y 1100 V)",
        x=0.01,
        ha="left",
        fontweight="bold",
    )
    return fig


def _cash_flow(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    r = b.economic.result
    cf = cumulative_cash_flow(r.economics, 5, 24)
    color = T.STRATEGY_COLOR[r.strategy]
    ax.plot(cf["mes"], cf["flujo_acumulado_COP"] / 1e6, color=color, lw=2, label=r.label)
    pb = r.economics.payback_months
    if 0 < pb <= 60:
        ax.scatter([pb], [0], marker="D", s=40, color=color, edgecolor=T.SURFACE, zorder=5)
        ax.annotate(
            f"break-even {r.economics.payback_days:,.0f} d",
            (pb, 0),
            textcoords="offset points",
            xytext=(6, -14),
            fontsize=8.5,
            color=T.INK_SECONDARY,
        )
    ax.axhline(0, color="#c3c2b7", lw=1)
    ax.set_title("Flujo de caja acumulado frente a Q_C = 0 (5 años, sin descuento)")
    ax.set_xlabel("Meses desde la inversión")
    ax.set_ylabel("Flujo acumulado [millones COP]")
    ax.legend(loc="lower left")
    return fig


def _sensitivity(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    s = b.sensitivity
    assert s is not None
    ax.fill_between(s.scan["X_line_ohm"], s.scan["ancho_ventana_kvar"], color=T.SERIES[0], alpha=0.15, lw=0)
    ax.plot(s.scan["X_line_ohm"], s.scan["ancho_ventana_kvar"], color=T.SERIES[0], lw=2)
    ax.axvline(s.x_actual, color=T.CRITICAL, ls="--", lw=1.5)
    ax.text(
        s.x_actual, ax.get_ylim()[1] * 0.92, f" X actual = {s.x_actual:g} Ω\n ✕ infactible", color=T.INK, fontsize=8.5
    )
    for iv in s.feasible_ranges:
        ax.axvline(iv.hi, color=T.GOOD, ls=":", lw=1.5)
        ax.axvline(iv.lo, color=T.GOOD, ls=":", lw=1.5)
        ax.text(iv.hi, ax.get_ylim()[1] * 0.6, f"X_crít = {iv.hi:.2f} Ω ", color=T.INK, ha="right", fontsize=8.5)
        ax.text(iv.lo, ax.get_ylim()[1] * 0.75, f" X_mín = {iv.lo:.2f} Ω", color=T.INK, fontsize=8.5)
    ax.set_title("Sensibilidad: ancho de la ventana Q_C común a las 24 h vs. X_line")
    ax.set_xlabel("X_line [Ω]")
    ax.set_ylabel("Ancho ∩ventanas [kvar]")
    return fig


def _p2_current(b: AnalysisBundle) -> Figure:
    fig, ax = _new((9, 4.6))
    for r in _strategies(b):
        i_mag = np.abs(r.circuit.i_line)
        _plot_line(ax, r.circuit.hours, i_mag, r.label, T.STRATEGY_COLOR[r.strategy], T.STRATEGY_DASH[r.strategy])
    rec = np.abs(b.economic.result.circuit.i_line)
    k_max, k_min = int(np.argmax(rec)), int(np.argmin(rec))
    for k, word, dy in ((k_max, "máx", 8), (k_min, "mín", -14)):
        ax.annotate(
            f"{word} {rec[k]:.3f} A (h{k + 1})",
            (k + 1, rec[k]),
            textcoords="offset points",
            xytext=(6, dy),
            fontsize=8.5,
            color=T.INK,
        )
    ax.set_ylim(0, max(float(np.abs(r.circuit.i_line).max()) for r in _strategies(b)) * 1.15)
    ax.set_title(f"{b.name} — Corriente de línea |I_line(t)| en {b.params.line_kv:g} kV")
    ax.set_ylabel("|I_line| [A]")
    ax.legend(loc="lower right", fontsize=8)
    _hours_axis(ax)
    return fig


def _pf_net(b: AnalysisBundle) -> Figure:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for r in _strategies(b):
        color, dash = T.STRATEGY_COLOR[r.strategy], T.STRATEGY_DASH[r.strategy]
        _plot_line(axes[0], r.circuit.hours, r.pf_net, r.label, color, dash)
        _plot_line(axes[1], r.circuit.hours, r.q_net_kvar, r.label, color, dash)
    axes[0].set_ylim(0, 1.05)
    axes[0].set_title("Factor de potencia neto fp_neto(t)", fontsize=10)
    axes[0].legend(loc="lower right", fontsize=8)
    axes[1].axhline(0, color="#c3c2b7", lw=1)
    axes[1].set_title("Q_neto(t) = Q(t) − Q_C  [kvar]  (< 0 ⇒ adelanto)", fontsize=10)
    for ax in axes:
        _hours_axis(ax)
    fig.suptitle(
        f"{b.name} — Factor de potencia y reactiva neta en la barra de 120 V", x=0.01, ha="left", fontweight="bold"
    )
    return fig


# ==================================================================================
# Catálogo de figuras con comentario técnico
# ==================================================================================
def chart_catalog(b: AnalysisBundle) -> list[ChartSpec]:
    p1 = b.problem1
    eco = b.economic
    e = eco.result
    f = b.feasibility
    nc = b.no_capacitor
    qc = eco.q_c_design_kvar
    i1_max = float(np.abs(p1.i_line).max())
    analysis = problem2_analysis(b)
    t = TEACHING_HOUR - 1
    out_txt = ", ".join(map(str, eco.hours_out)) or "ninguna"

    return [
        ChartSpec(
            "01_p1_corriente_linea.png",
            "Problema 1 — |I_line(t)|",
            f"A 120 V la corriente alcanza {i1_max:,.0f} A en la hora pico. Para transportar "
            "~150 kW a baja tensión se requieren corrientes de miles de amperios; con 80 Ω de resistencia "
            "serie esto es físicamente inviable.",
            _p1_current,
        ),
        ChartSpec(
            "02_p1_perdidas.png",
            "Problema 1 — P_loss(t) vs. P útil",
            f"Las pérdidas diarias ({p1.daily_energy_loss_kwh:,.0f} kWh) superan "
            f"{p1.daily_energy_loss_kwh / p1.daily_energy_served_kwh:,.0f} veces la energía entregada. "
            "La relación P_loss ∝ |I|²·R explica el diagnóstico de 'pérdidas absurdas'.",
            _p1_losses,
        ),
        ChartSpec(
            "03_p1_sgen.png",
            "Problema 1 — |S_gen(t)|",
            "La potencia aparente del generador (miles de MVA) está dominada por Q_loss = |I|²·900; "
            "el generador alimenta principalmente la reactancia de la línea, no la carga.",
            _p1_sgen,
        ),
        ChartSpec(
            "04_demanda_desglose.png",
            "Perfil de demanda",
            "La carga industrial (fp 0.75) entra de 9 a 24 h y domina la demanda reactiva; el bloque 8–16 h "
            "residencial (fp 0.70) agrava el consumo de vars.",
            _demand,
        ),
        ChartSpec(
            "05_p1_vs_p2_corriente.png",
            "Problema 1 vs. Problema 2 — corriente",
            "Al elevar la tensión de transporte a 13.2 kV la corriente de línea cae por el factor a₂ = 110 y "
            "las pérdidas por 110² = 12 100.",
            _p1_vs_p2,
        ),
        ChartSpec(
            "06_p2_vgen_estrategias.png",
            "|V_gen(t)| — sin capacitor vs. banco fijo",
            " ".join(analysis["Tensión del generador |Vgen(t)|"]),
            _vgen,
        ),
        ChartSpec(
            "07_p2_perdidas_apiladas.png",
            "Pérdidas apiladas línea vs. generador",
            " ".join(analysis["Pérdidas Ploss(t)"]),
            _losses_stacked,
        ),
        ChartSpec(
            "08_costo_total_vs_qc.png",
            "Costo total anual J(Q_C)",
            f"J(Q_C) es una parábola convexa con mínimo libre en {eco.q_c_free_kvar:.2f} kvar "
            f"({format_cop(eco.free.economics.total_annual_cost_cop)}/año). El banco adoptado ({qc:g} kvar) está en la "
            f"rama creciente: J = {format_cop(e.economics.total_annual_cost_cop)}/año, "
            f"{e.economics.total_annual_cost_cop / eco.free.economics.total_annual_cost_cop:.2f} veces el mínimo libre. "
            f"La franja verde marca los Q_C con {eco.band.hours_in_band}/24 h en banda; {qc:g} kvar es su extremo de "
            "menor costo.",
            _cost_curve,
        ),
        ChartSpec(
            "09_mapa_factibilidad.png",
            "Mapa de factibilidad horaria",
            f"Las ventanas verdes no comparten un valor común (par crítico: horas {f.critical_pair}). La línea de "
            f"{qc:g} kvar cruza la rama alta de todas las horas menos la {out_txt}, donde cae en el hueco entre sus "
            "dos tramos.",
            _feasibility_map,
        ),
        ChartSpec(
            "10_horas_en_banda_vs_qc.png",
            "Horas en banda según Q_C",
            f"El número de horas con 950 ≤ |V_gen| ≤ 1100 V alcanza su máximo, {eco.band.hours_in_band}/24, para Q_C en "
            f"{format_set(eco.band.window)} kvar. Por debajo de {eco.q_c_band_optimum_kvar:.2f} kvar las horas valle "
            "quedan bajo 950 V; por encima del extremo superior salen las horas pico de la tarde.",
            _band_hours,
        ),
        ChartSpec(
            "11_triangulo_potencias.png",
            f"Triángulo de potencias (h{TEACHING_HOUR})",
            f"En la hora {TEACHING_HOUR} la carga pide {b.demand.q_total_kvar[t]:.2f} kvar y el banco entrega {qc:g} kvar: "
            f"Q_neto = {e.q_net_kvar[t]:.2f} kvar y fp = {e.pf_net[t]:.3f} en adelanto. La potencia aparente sube de "
            f"{abs(b.demand.s_total_kva[t]):.1f} a {abs(e.circuit.s_load_kva[t]):.1f} kVA.",
            _triangle,
        ),
        ChartSpec(
            "12_diagrama_fasorial.png",
            f"Diagrama fasorial (h{TEACHING_HOUR})",
            "Con corriente en atraso la caída jI·X (900 Ω) es casi paralela a V₀ y eleva |V_gen|; con corriente en "
            f"adelanto gira y |V_gen| vuelve a la banda ({e.v_gen_mag[t]:,.1f} V frente a {nc.v_gen_mag[t]:,.1f} V sin "
            "capacitor).",
            _phasor,
        ),
        ChartSpec(
            "13_flujo_caja.png",
            "Flujo de caja acumulado",
            f"Frente a Q_C = 0 el banco de {qc:g} kvar cuesta {format_cop(e.economics.capex_cop)} y aumenta el costo de "
            f"pérdidas en {format_cop(-e.economics.annual_savings_cop)}/año: el flujo acumulado es siempre negativo y "
            "la inversión no se recupera con ahorro de energía.",
            _cash_flow,
        ),
        ChartSpec(
            "14_sensibilidad_xline.png",
            "Sensibilidad X_line",
            "La factibilidad del banco fijo no es monótona en X: con X muy baja el capacitor pierde poder de "
            "regulación y con X alta la dispersión valle-pico excede la banda.",
            _sensitivity,
        ),
        ChartSpec(
            "15_p2_corriente_linea.png",
            "Problema 2 — |I_line(t)|",
            " ".join(analysis["Corriente de línea |Iline(t)|"]),
            _p2_current,
        ),
        ChartSpec(
            "16_p2_fp_neto.png",
            "Problema 2 — fp_neto(t) y Q_neto(t)",
            f"Sin capacitor el fp neto es el de la carga ({nc.pf_net.min():.3f}–{nc.pf_net.max():.3f}, en atraso). Con "
            f"{qc:g} kvar Q_neto es negativo las {e.hours_leading} horas y el fp cae a "
            f"{e.pf_net.min():.3f}–{e.pf_net.max():.3f} en adelanto; el peor valor es el de la hora de menor carga.",
            _pf_net,
        ),
    ]


def export_charts(
    b: AnalysisBundle, out_dir: Path, catalog: list[ChartSpec] | None = None
) -> list[tuple[ChartSpec, Path]]:
    """Exporta las figuras de ``catalog`` (por defecto, las 16 del Problema 1 y del Problema 2)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for spec in catalog or chart_catalog(b):
        fig = spec.builder(b)
        path = out_dir / spec.filename
        fig.savefig(path, dpi=DPI)
        plt.close(fig)
        written.append((spec, path))
    return written


# ==================================================================================
# CSV
# ==================================================================================
def export_tables(b: AnalysisBundle, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    eco = b.economic.result
    tables: dict[str, pd.DataFrame] = {
        "p1_horario.csv": b.problem1.to_dataframe(),
        "p2_sin_capacitor_horario.csv": b.no_capacitor.circuit.to_dataframe(),
        "p2_fijo_economico_horario.csv": eco.circuit.to_dataframe(),
        "factibilidad_horaria.csv": b.feasibility.to_dataframe(),
        "comparativa_estrategias.csv": b.comparison_table(),
        "economia_estrategias.csv": pd.DataFrame(
            [{"Estrategia": r.label, **r.economics.as_dict()} for r in b.strategies.values()]
        ),
        "barrido_qc_fijo.csv": b.scan,
        "fase1_paso_a_paso_24h.csv": hourly_step_table(b.demand, b.problem1, b.params),
        "fase2_paso_a_paso_24h_qc0.csv": hourly_step_table(b.demand, b.no_capacitor.circuit, b.params),
        "fase2_paso_a_paso_24h_fijo_economico.csv": hourly_step_table(b.demand, eco.circuit, b.params),
    }
    if b.sensitivity is not None:
        tables["sensibilidad_xline.csv"] = b.sensitivity.scan
    paths = []
    for name, df in tables.items():
        p = out_dir / name
        df.to_csv(p, index=False, float_format="%.15g")
        paths.append(p)
    return paths


# ==================================================================================
# Problema 2.1 (línea a 66 kV) y comparación con el Problema 2
# ==================================================================================
def _comparison_figure(b2: AnalysisBundle, b21: AnalysisBundle) -> Figure:
    """Cuatro paneles: |V_gen|, |I_line| y P_loss con cada banco fijo, y energía perdida al día por caso."""
    r2, r21 = b2.economic.result, b21.economic.result
    n2, n21 = b2.no_capacitor, b21.no_capacitor
    c2, c21 = T.SERIES[1], T.SERIES[2]
    l2 = f"{b2.name} ({b2.params.line_kv:g} kV, {r2.q_c_installed_kvar:g} kvar)"
    l21 = f"{b21.name} ({b21.params.line_kv:g} kV, {r21.q_c_installed_kvar:g} kvar)"
    fig, axes = plt.subplots(2, 2, figsize=(11, 7.6), constrained_layout=True)
    hours = r2.circuit.hours

    ax = axes[0, 0]
    p = b2.params
    ax.axhspan(p.v_gen_min, p.v_gen_max, color=T.GOOD, alpha=0.12, lw=0)
    for lim in (p.v_gen_min, p.v_gen_max):
        ax.axhline(lim, color=T.GOOD, lw=1, ls=":")
    for r, label, color in ((r2, l2, c2), (r21, l21, c21)):
        _plot_line(ax, hours, r.v_gen_mag, label, color)
        out = r.violation_v > 1e-6
        ax.scatter(hours[out], r.v_gen_mag[out], marker="x", s=30, color=T.CRITICAL, lw=1.4, zorder=5)
    ax.set_title("|V_gen(t)| con banco fijo (banda verde: 950–1100 V)", fontsize=10)
    ax.set_ylabel("|V_gen| [V]")
    _hours_axis(ax)

    ax = axes[0, 1]
    for r, label, color in ((r2, l2, c2), (r21, l21, c21)):
        _plot_line(ax, hours, np.abs(r.circuit.i_line), label, color)
    ax.set_yscale("log")
    ax.set_title("|I_line(t)| con banco fijo (escala log)", fontsize=10)
    ax.set_ylabel("|I_line| [A]")
    _hours_axis(ax)

    ax = axes[1, 0]
    for r, label, color in ((r2, l2, c2), (r21, l21, c21)):
        _plot_line(ax, hours, r.circuit.p_loss_kw, label, color)
    ax.set_yscale("log")
    ax.set_title("P_loss(t) con banco fijo (escala log)", fontsize=10)
    ax.set_ylabel("P_loss [kW]")
    _hours_axis(ax)

    ax = axes[1, 1]
    cases = (
        ("P2\nQ_C = 0", n2.circuit),
        (f"P2\n{r2.q_c_installed_kvar:g} kvar", r2.circuit),
        ("P2.1\nQ_C = 0", n21.circuit),
        (f"P2.1\n{r21.q_c_installed_kvar:g} kvar", r21.circuit),
    )
    names = [n for n, _ in cases]
    line = np.array([c.p_loss_line_kw.sum() for _, c in cases])
    gen = np.array([c.p_loss_gen_kw.sum() for _, c in cases])
    ax.bar(names, line, color=T.SERIES[0], width=0.6, edgecolor=T.SURFACE, lw=1, label="Línea (80 Ω)")
    ax.bar(names, gen, bottom=line, color=T.SERIES[1], width=0.6, edgecolor=T.SURFACE, lw=1, label="Generador (0.5 Ω)")
    for k, total in enumerate(line + gen):
        ax.text(k, total, f"{total:,.1f}", ha="center", va="bottom", fontsize=8.5, color=T.INK)
    ax.set_ylim(0, (line + gen).max() * 1.12)
    ax.set_title("Energía perdida al día [kWh/día]", fontsize=10)
    ax.legend(loc="upper right", fontsize=8)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncols=2, fontsize=9)
    fig.suptitle(f"Comparación — {b2.title} vs. {b21.title}", x=0.01, ha="left", fontweight="bold")
    return fig


def chart_catalog_21(b21: AnalysisBundle, b2: AnalysisBundle) -> list[ChartSpec]:
    """Figuras del Problema 2.1 y figura comparativa con el Problema 2 (numeración a continuación de la 16)."""
    analysis = problem21_analysis(b21, b2)
    eco = b21.economic
    qc = eco.q_c_design_kvar
    return [
        ChartSpec(
            "17_p21_vgen_estrategias.png",
            "Problema 2.1 — |V_gen(t)|: sin capacitor vs. banco fijo",
            " ".join(analysis["Banco capacitivo y tensión |Vgen(t)|"]),
            _vgen,
        ),
        ChartSpec(
            "18_p21_corriente_linea.png",
            "Problema 2.1 — |I_line(t)|",
            " ".join(analysis["Corriente de línea |Iline(t)|"]),
            _p2_current,
        ),
        ChartSpec(
            "19_p21_perdidas_apiladas.png",
            "Problema 2.1 — pérdidas apiladas línea vs. generador",
            " ".join(analysis["Pérdidas Ploss(t) y costo"]),
            _losses_stacked,
        ),
        ChartSpec(
            "20_p21_costo_total_vs_qc.png",
            "Problema 2.1 — costo total anual J(Q_C)",
            f"A 66 kV el mínimo libre de J ({eco.q_c_free_kvar:.2f} kvar) y el banco que cumple la banda ({qc:g} kvar) "
            f"están a {qc - eco.q_c_free_kvar:.2f} kvar: la curva es casi plana entre ambos y exigir tensión cuesta "
            f"{format_cop(eco.result.economics.total_annual_cost_cop - eco.free.economics.total_annual_cost_cop)}/año. "
            f"La franja verde (Q_C con {eco.band.hours_in_band}/24 h en banda) empieza en {eco.band.window[0].lo:.2f} kvar.",
            _cost_curve,
        ),
        ChartSpec(
            "21_p21_mapa_factibilidad.png",
            "Problema 2.1 — mapa de factibilidad horaria",
            f"Las ventanas horarias se solapan: intersección {format_set(b21.feasibility.global_set)} kvar. Las horas "
            "valle admiten cualquier Q_C desde 0; las horas con la industria en servicio exigen un mínimo, y el mayor "
            f"de esos mínimos (hora de mayor carga) fija el banco en {qc:g} kvar.",
            _feasibility_map,
        ),
        ChartSpec(
            "22_p21_fp_neto.png",
            "Problema 2.1 — fp_neto(t) y Q_neto(t)",
            " ".join(analysis["Factor de potencia neto"]),
            _pf_net,
        ),
        ChartSpec(
            "23_comparacion_p2_vs_p21.png",
            "Comparación — Problema 2 vs. Problema 2.1",
            " ".join(comparison_synthesis(b2, b21)[:4]),
            lambda b, ref=b2: _comparison_figure(ref, b),
        ),
    ]


def export_tables_21(b21: AnalysisBundle, b2: AnalysisBundle, out_dir: Path) -> list[Path]:
    """CSV del Problema 2.1 (prefijo ``p21_``) y tabla comparativa con el Problema 2."""
    out_dir.mkdir(parents=True, exist_ok=True)
    eco = b21.economic.result
    tables: dict[str, pd.DataFrame] = {
        "p21_sin_capacitor_horario.csv": b21.no_capacitor.circuit.to_dataframe(),
        "p21_fijo_economico_horario.csv": eco.circuit.to_dataframe(),
        "p21_factibilidad_horaria.csv": b21.feasibility.to_dataframe(),
        "p21_comparativa_estrategias.csv": b21.comparison_table(),
        "p21_economia_estrategias.csv": pd.DataFrame(
            [{"Estrategia": r.label, **r.economics.as_dict()} for r in b21.strategies.values()]
        ),
        "p21_barrido_qc_fijo.csv": b21.scan,
        "p21_paso_a_paso_24h_qc0.csv": hourly_step_table(b21.demand, b21.no_capacitor.circuit, b21.params),
        "p21_paso_a_paso_24h_fijo_economico.csv": hourly_step_table(b21.demand, eco.circuit, b21.params),
        "comparacion_p2_vs_p21.csv": comparison_table(b2, b21),
    }
    paths = []
    for name, df in tables.items():
        p = out_dir / name
        df.to_csv(p, index=False, float_format="%.15g")
        paths.append(p)
    return paths


# ==================================================================================
# Reporte Markdown
# ==================================================================================
def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---:" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line.replace('|', chr(92) + '|')}" for line in lines)


def _critical_pair_text(b: AnalysisBundle) -> str:
    f = b.feasibility
    if f.critical_pair is None:
        return "  Existe al menos un Q_C fijo común a las 24 horas."
    h_a, h_b = f.critical_pair
    idx = {int(h): i for i, h in enumerate(f.hours)}
    sa, sb = f.hourly_sets[idx[h_a]], f.hourly_sets[idx[h_b]]
    return (
        f"  La hora {h_a} exige Q_C ∈ {format_set(sa)} kvar, mientras la hora {h_b} exige "
        f"Q_C ∈ {format_set(sb)} kvar: los conjuntos son disjuntos, luego la intersección de las 24 h es vacía."
    )


def _cplx(z: complex, unit: str, d: int = 4) -> str:
    sign = "+" if z.imag >= 0 else "−"
    return f"{z.real:,.{d}f} {sign} j{abs(z.imag):,.{d}f} = {abs(z):,.{d}f}∠{np.degrees(np.angle(z)):.4f}° {unit}"


def _payback(days: float) -> str:
    return "no se recupera" if not np.isfinite(days) else format_number(days, 1)


def _step_by_step_hour(b: AnalysisBundle, hour: int) -> str:
    """Tabla del desarrollo numérico de una hora: Fase 1 vs. Fase 2 (Q_C = 0) vs. Fase 2 con el banco fijo."""
    t = hour - 1
    d, prm = b.demand, b.params
    phase = "Fase 2" if b.name == CASE_2 else "Fase 2.1"
    cases = (
        ("Fase 1 (red directa)", b.problem1),
        (f"{phase}, Q_C = 0", b.no_capacitor.circuit),
        (f"{phase}, Q_C = {b.economic.q_c_design_kvar:g} kvar", b.economic.result.circuit),
    )
    s_load = complex(d.s_total_kva[t])

    def col(c: object) -> list[str]:
        s_net = complex(c.s_load_kva[t])  # type: ignore[attr-defined]
        s_gen = c.v_gen[t] * np.conj(c.i_gen[t]) / 1000  # type: ignore[attr-defined]
        return [
            f"{c.q_c_kvar[t]:.4f} kvar",  # type: ignore[attr-defined]
            _cplx(s_net, "kVA"),
            pf_label(s_net)[0],
            _cplx(c.i_load[t], "A"),  # type: ignore[attr-defined]
            _cplx(c.i_line[t], "A", 6),  # type: ignore[attr-defined]
            _cplx(c.i_gen[t], "A"),  # type: ignore[attr-defined]
            _cplx(c.v_line_send[t], "V", 3),  # type: ignore[attr-defined]
            _cplx(c.v_t1_primary[t], "V", 3) if c is not b.problem1 else "— (sin T1)",  # type: ignore[attr-defined]
            _cplx(c.v_gen[t], "V", 3),  # type: ignore[attr-defined]
            f"{c.p_loss_line_kw[t]:,.6f} kW",  # type: ignore[attr-defined]
            f"{c.p_loss_gen_kw[t]:,.6f} kW",  # type: ignore[attr-defined]
            f"{c.p_loss_kw[t]:,.6f} kW",  # type: ignore[attr-defined]
            _cplx(s_gen, "kVA"),
            f"{power_balance_error(c, prm)[t]:.1e}",  # type: ignore[arg-type]
        ]

    rows = [
        ("Q_C", "banco en la barra de 120 V"),
        ("S_neto", "P_tot + j(Q_tot − Q_C)"),
        ("fp_neto", r"P / \|S_neto\|"),
        ("I_load", "(S_neto·1000 / 120∠0°)*"),
        ("I_line", f"Fase 1: I_load · {phase}: I_load / a₂ ({prm.a2:g})"),
        ("I_gen", f"Fase 1: I_line · {phase}: n₁·I_line ({prm.n1:g})"),
        ("V_line,envío", "V_recv + I_line·(80 + j900)"),
        ("V_T1,prim", "V_line,envío / n₁"),
        ("V_gen", "V_T1,prim + 0.5·I_gen"),
        ("P_loss,line", r"\|I_line\|²·80 / 1000"),
        ("P_loss,gen", r"\|I_gen\|²·0.5 / 1000"),
        ("P_loss,total", rf"suma ({phase}: \|I_line\|²·{prm.r_eq_line_side:g}/1000)"),
        ("S_gen = V_gen·I_gen*", "debe igualar S_neto + S_loss,line + S_loss,gen"),
        ("Error relativo de conservación", r"\|S_gen − Σ\| / \|S_gen\|"),
    ]
    values = [col(c) for _, c in cases]
    df = pd.DataFrame(
        {
            "Magnitud": [r[0] for r in rows],
            "Expresión": [r[1] for r in rows],
            **{name: vals for (name, _), vals in zip(cases, values, strict=True)},
        }
    )
    header = (
        f"**Datos de la hora {hour}:** P₁ = {d.p1_kw[t]:g} kW (fp {d.pf1[t]:.2f} en atraso) → "
        f"Q₁ = {d.p1_kw[t]:g}·tan(cos⁻¹ {d.pf1[t]:.2f}) = {d.q1_kvar[t]:.4f} kvar; "
        f"P₂ = {d.p2_kw[t]:g} kW (fp {d.pf2[t]:.2f} en atraso) → Q₂ = {d.q2_kvar[t]:.4f} kvar.  \n"
        f"S_carga = {_cplx(s_load, 'kVA')} · fp carga {pf_label(s_load)[0]}."
    )
    return header + "\n\n" + _md_table(df)


def _hourly_profile(b: AnalysisBundle) -> pd.DataFrame:
    """Perfil de las 24 horas con el banco fijo adoptado (para el reporte)."""
    r = b.economic.result
    c = r.circuit
    return pd.DataFrame(
        {
            "Hora": c.hours,
            "P [kW]": [f"{x:g}" for x in c.s_load_kva.real],
            "Q_carga [kvar]": [f"{x:.3f}" for x in b.demand.q_total_kvar],
            "Q_neto [kvar]": [f"{x:.3f}" for x in r.q_net_kvar],
            "fp_neto": [
                f"{x:.4f} {'ad.' if lead else 'at.'}" for x, lead in zip(r.pf_net, c.leading_mask, strict=True)
            ],
            "I_load [A]": [f"{abs(x):,.2f}" for x in c.i_load],
            "I_line [A]": [f"{abs(x):.4f}" for x in c.i_line],
            "I_gen [A]": [f"{abs(x):.3f}" for x in c.i_gen],
            "V_gen [V]": [f"{x:,.3f}" for x in r.v_gen_mag],
            "En banda": ["sí" if v <= 1e-6 else "**no**" for v in r.violation_v],
            "P_loss línea [kW]": [f"{x:.3f}" for x in c.p_loss_line_kw],
            "P_loss gen. [kW]": [f"{x:.3f}" for x in c.p_loss_gen_kw],
            "P_loss [kW]": [f"{x:.3f}" for x in c.p_loss_kw],
            "Q_loss [kvar]": [f"{x:.3f}" for x in c.q_loss_kvar],
            "S_gen [kVA]": [f"{abs(x):.3f}" for x in c.s_gen_kva],
        }
    )


def _esc(text: str) -> str:
    """Escapa las barras verticales para que no rompan las tablas ni el énfasis de Markdown."""
    return text.replace("|", chr(92) + "|")


def _strategy_rows(b: AnalysisBundle) -> pd.DataFrame:
    rows = []
    for s in b.strategies.values():
        ec = s.economics
        rows.append(
            {
                "Estrategia": s.label,
                "Q_C inst. [kvar]": f"{s.q_c_installed_kvar:.3f}",
                "I_line máx [A]": f"{np.abs(s.circuit.i_line).max():.4f}",
                "E_loss [kWh/día]": f"{ec.daily_loss_kwh:.3f}",
                "CAPEX": format_cop(ec.capex_cop),
                "OPEX anual": format_cop(ec.annual_loss_cost_cop),
                "J anual": format_cop(ec.total_annual_cost_cop),
                "Ahorro anual": format_cop(ec.annual_savings_cop),
                "Payback [días]": _payback(ec.payback_days),
                "V_gen mín–máx [V]": f"{s.v_gen_mag.min():.1f}–{s.v_gen_mag.max():.1f}",
                "Horas fuera": s.hours_out_of_band,
                "Viol. máx [V]": f"{s.max_violation_v:.2f}",
                "fp_neto mín–máx": f"{s.pf_net.min():.3f}–{s.pf_net.max():.3f}",
                "Estado fp (24 h)": s.pf_status,
            }
        )
    return pd.DataFrame(rows)


def _z(z: complex, d: int = 4) -> str:
    return f"{z.real:.{d}f} + j{z.imag:.{d}f} Ω"


def _section_21(b21: AnalysisBundle, b2: AnalysisBundle, charts21: list[tuple[ChartSpec, Path]]) -> str:
    """Sección del reporte dedicada al Problema 2.1, con su «Análisis» y la «Comparación» con el Problema 2."""
    p21, p2 = b21.params, b2.params
    eco, nc = b21.economic, b21.no_capacitor
    r, free = eco.result, eco.free
    ee, e0 = r.economics, nc.economics
    qc = eco.q_c_design_kvar
    vg = r"\|V_gen\|"
    days = p21.days_per_year
    i_nc, i_ec = np.abs(nc.circuit.i_line), np.abs(r.circuit.i_line)
    hours = r.circuit.hours
    out0 = ", ".join(str(int(h)) for h in hours[nc.violation_v > 1e-6]) or "ninguna"
    balance = max(float(power_balance_error(nc.circuit, p21).max()), float(power_balance_error(r.circuit, p21).max()))
    kappa21, kappa2 = (x.r_eq_line_side * 1000 / abs(x.v_line_receiving) ** 2 for x in (p21, p2))
    ratios = pd.DataFrame(
        {
            "Magnitud": [
                "T1 (elevador)",
                "T2 (reductor)",
                "n₁ = V_línea / 1 kV",
                "a₂ = V_línea / 120 V",
                "V₀ referida a la línea (V₀·a₂)",
                "V₀ referida al generador (V₀·a₂/n₁)",
                "I_line para una I_load dada",
                "I_gen para una I_load dada",
                "Z_line reflejada al generador (Z_line/n₁²)",
                "Z total vista por el generador (R_gen + Z_line/n₁²)",
                "R_gen referida a la línea (R_gen·n₁²)",
                "R_eq referida a la línea (80 + R_gen·n₁²)",
                "κ = R_eq·1000 / V_línea²  [kW/kVA²]",
            ],
            b2.name: [
                p2.t1_label,
                p2.t2_label,
                f"{p2.n1:g}",
                f"{p2.a2:g}",
                f"{abs(p2.v_line_receiving):,.0f} V",
                f"{abs(p2.v_load_gen_side):,.0f} V",
                f"I_load / {p2.a2:g}",
                f"I_load / {p2.a2 / p2.n1:.4f}",
                _z(p2.z_line / p2.n1**2),
                _z(p2.z_gen_side),
                f"{p2.r_gen_line_side:,.2f} Ω",
                f"{p2.r_eq_line_side:,.2f} Ω",
                f"{kappa2:.6e}",
            ],
            b21.name: [
                p21.t1_label,
                p21.t2_label,
                f"{p21.n1:g}",
                f"{p21.a2:g}",
                f"{abs(p21.v_line_receiving):,.0f} V",
                f"{abs(p21.v_load_gen_side):,.0f} V",
                f"I_load / {p21.a2:g}",
                f"I_load / {p21.a2 / p21.n1:.4f}",
                _z(p21.z_line / p21.n1**2),
                _z(p21.z_gen_side),
                f"{p21.r_gen_line_side:,.2f} Ω",
                f"{p21.r_eq_line_side:,.2f} Ω",
                f"{kappa21:.6e}",
            ],
        }
    )
    feas_rows = pd.DataFrame(
        {"Hora": b21.feasibility.hours, "Q_C factible [kvar]": [format_set(s) for s in b21.feasibility.hourly_sets]}
    )
    analysis = problem21_analysis(b21, b2)
    analysis_md = NL.join(f"**{_esc(title)}**{NL}{NL}{_bullets(lines)}{NL}" for title, lines in analysis.items())
    comparison_md = _md_table(format_comparison(comparison_table(b2, b21)))
    charts_md = (NL + NL).join(
        f"#### Fig. {16 + i}. {spec.title}{NL}{NL}![{spec.title}]({path.name}){NL}{NL}"
        f"**Comentario técnico:** {_esc(spec.comment)}"
        for i, (spec, path) in enumerate(charts21, 1)
    )
    return f"""## 7. Problema 2.1 — Red con T1 = 1 kV : 66 kV y T2 = 66 kV : 120 V

Clon del Problema 2 en el que cambian **solo** las relaciones de transformación. Se mantienen V₀ = 120∠0° V,
R_gen = 0.5 Ω, Z_line = 80 + j900 Ω, el perfil de 24 h de L1 y L2, la tarifa (960 COP/kWh, 365 días/año), el costo del
banco (100 000 COP/kvar) y la banda {vg} ∈ [950, 1100] V. Todo lo demás se recalcula con el mismo solucionador y se
contrasta con la auditoría independiente (`auditoria_p21.txt`).

### 7.1 Relaciones de transformación y reflejo de impedancias, tensiones y corrientes

{_md_table(ratios)}

- La tensión que ve el generador sin caídas sigue siendo 1 000 V, y la corriente del generador para una carga dada
  no cambia. Lo que cambia es la corriente de **línea** (÷{p21.a2 / p2.a2:g}) y la impedancia de la línea vista desde el
  generador (÷{(p21.n1 / p2.n1) ** 2:g}).

### 7.2 Sin capacitor (Q_C = 0)

- \\|I_line\\| ∈ [{i_nc.min():.4f}, {i_nc.max():.4f}] A (promedio {i_nc.mean():.4f} A).
- {vg} ∈ [{nc.v_gen_mag.min():.2f}, {nc.v_gen_mag.max():.2f}] V → **{nc.hours_out_of_band}/24 h fuera de banda**
  (horas {out0}; violación máxima {nc.max_violation_v:.2f} V).
- Pérdidas: **{e0.daily_loss_kwh:,.4f} kWh/día** = {e0.daily_loss_kwh * days:,.1f} kWh/año →
  {format_cop(e0.daily_loss_kwh * p21.energy_price_cop_per_kwh)}/día → **{format_cop(e0.annual_loss_cost_cop)}/año**.
- fp neto ∈ [{nc.pf_net.min():.3f}, {nc.pf_net.max():.3f}], {nc.pf_status}.

### 7.3 Factibilidad y dimensionamiento del banco

{_md_table(feas_rows)}

- **Intersección de las 24 h: {format_set(b21.feasibility.global_set)} kvar → {"FACTIBLE" if b21.feasibility.is_feasible else "INFACTIBLE"}.**
  Pares de horas en conflicto: {", ".join(str(x) for x in b21.feasibility.conflicting_pairs) or "ninguno"}.
- Mínimo libre de J: Q_C = mean(Q) − c_cap/(2·c_e·κ·24) = **{eco.q_c_free_kvar:.6f} kvar**
  (`minimize_scalar`: {eco.q_c_free_numeric_kvar:.6f} kvar), J = {format_cop(free.economics.total_annual_cost_cop)}/año,
  {24 - free.hours_out_of_band}/24 h en banda (violación {free.max_violation_v:.4f} V).
- Queda fuera de la ventana; como J es convexa, el de menor costo que cumple es el extremo inferior,
  **{eco.q_c_band_optimum_kvar:.6f} kvar**, que se adopta como **Q_C = {qc:g} kvar**
  (dJ/dQ_C = {eco.derivative_at_design:,.0f} COP/kvar en ese punto).

### 7.4 Resultados con Q_C = {qc:g} kvar

{_md_table(_strategy_rows(b21))}

- {vg} ∈ [{r.v_gen_mag.min():.3f}, {r.v_gen_mag.max():.4f}] V · **{24 - r.hours_out_of_band}/24 h en banda**.
- \\|I_line\\| ∈ [{i_ec.min():.4f}, {i_ec.max():.4f}] A (promedio {i_ec.mean():.4f} A) ·
  fp neto ∈ [{r.pf_net.min():.4f}, {r.pf_net.max():.4f}] → **{r.pf_status}**.
- Pérdidas: **{ee.daily_loss_kwh:,.4f} kWh/día** ({r.circuit.p_loss_line_kw.sum():,.4f} en la línea +
  {r.circuit.p_loss_gen_kw.sum():,.4f} en el generador) = **{ee.daily_loss_kwh * days:,.1f} kWh/año**.
- Costo de pérdidas: {format_cop(ee.daily_loss_kwh * p21.energy_price_cop_per_kwh)}/día → OPEX **{format_cop(ee.annual_loss_cost_cop)}/año**.
- CAPEX = {qc:g} × 100 000 = **{format_cop(ee.capex_cop)}** · J = OPEX + CAPEX = **{format_cop(ee.total_annual_cost_cop)}/año**.
- Ahorro frente a Q_C = 0: **{format_cop(ee.annual_savings_cop)}/año** · Payback: **{_payback(ee.payback_days)} días**
  ({ee.payback_months:.2f} meses) · ROI 1/3/5 años = {" / ".join(format_number(v, 1) + " %" for v in ee.roi_table.values())}.
- Conservación de potencia compleja en las 24 h (V_gen·I_gen* frente a S_neto + S_pérdidas): error relativo
  máximo **{balance:.1e}** (con Q_C = 0 y con Q_C = {qc:g} kvar).

### 7.5 Perfil de las 24 horas con Q_C = {qc:g} kvar

{_md_table(_hourly_profile(b21))}

### 7.6 Desarrollo paso a paso — hora 12 (la que fija el banco)

{_step_by_step_hour(b21, 12)}

### 7.7 Análisis

{analysis_md}
### 7.8 Comparación — Problema 2 vs. Problema 2.1

Cada caso con su banco fijo: {b2.name} ({p2.t1_label} / {p2.t2_label}) con {b2.economic.q_c_design_kvar:g} kvar y
{b21.name} ({p21.t1_label} / {p21.t2_label}) con {qc:g} kvar. La última columna es el valor de 2.1 dividido por el de 2.

{comparison_md}

**Síntesis técnica**

{_bullets(comparison_synthesis(b2, b21))}

### 7.9 Gráficas del Problema 2.1 y de la comparación

{charts_md}

"""


def build_markdown_report(
    b: AnalysisBundle,
    charts: list[tuple[ChartSpec, Path]],
    b21: AnalysisBundle | None = None,
    charts21: list[tuple[ChartSpec, Path]] | None = None,
) -> str:
    """Reporte de sustentación. Con ``b21`` incluye el Problema 2.1 y su comparación con el Problema 2."""
    section_21 = _section_21(b21, b, charts21 or []) if b21 is not None else ""
    n = 1 if b21 is not None else 0  # corrimiento de la numeración de las secciones siguientes
    p1, nc, eco, f, prm = b.problem1, b.no_capacitor, b.economic, b.feasibility, b.params
    r, free = eco.result, eco.free
    ee, e0, ef = r.economics, nc.economics, free.economics
    qc = eco.q_c_design_kvar
    sens = b.sensitivity
    vg = r"\|V_gen\|"
    out_txt = ", ".join(map(str, eco.hours_out)) or "ninguna"
    in_band = 24 - r.hours_out_of_band
    margin = float(np.min(np.where(r.violation_v <= 1e-6, r.v_gen_mag - prm.v_gen_min, np.inf)))
    analysis = problem2_analysis(b)
    cmp_rows = []
    for s in b.strategies.values():
        ec = s.economics
        cmp_rows.append(
            {
                "Estrategia": s.label,
                "Q_C inst. [kvar]": f"{s.q_c_installed_kvar:.3f}",
                "I_line máx [A]": f"{np.abs(s.circuit.i_line).max():.3f}",
                "E_loss [kWh/día]": f"{ec.daily_loss_kwh:.3f}",
                "CAPEX": format_cop(ec.capex_cop),
                "OPEX anual": format_cop(ec.annual_loss_cost_cop),
                "J anual": format_cop(ec.total_annual_cost_cop),
                "Ahorro anual": format_cop(ec.annual_savings_cop),
                "Payback [días]": _payback(ec.payback_days),
                "V_gen mín–máx [V]": f"{s.v_gen_mag.min():.1f}–{s.v_gen_mag.max():.1f}",
                "Horas fuera": s.hours_out_of_band,
                "Viol. máx [V]": f"{s.max_violation_v:.2f}",
                "fp_neto mín–máx": f"{s.pf_net.min():.3f}–{s.pf_net.max():.3f}",
                "Estado fp (24 h)": s.pf_status,
            }
        )
    p1_daily_cost = p1.daily_energy_loss_kwh * prm.energy_price_cop_per_kwh
    feas_rows = pd.DataFrame({"Hora": f.hours, "Q_C factible [kvar]": [format_set(s) for s in f.hourly_sets]})
    i_nc, i_ec = np.abs(nc.circuit.i_line), np.abs(r.circuit.i_line)
    v_unity = affine_voltage_model(b.demand, prm).magnitude(b.demand.q_total_kvar)
    k_unity = int(np.argmax(v_unity))

    charts_md = "\n\n".join(
        f"### {i}. {spec.title}\n\n![{spec.title}]({path.name})\n\n"
        f"**Comentario técnico:** {spec.comment.replace('|', chr(92) + '|')}"
        for i, (spec, path) in enumerate(charts, 1)
    )

    sens_txt = (
        f"- Rangos de X_line con banco **fijo** factible las 24 h: **{format_set(sens.feasible_ranges)} Ω**.\n"
        f"- X_line crítica (al reducir desde 900 Ω): **{sens.x_critical_upper:.4f} Ω**. Con la reactancia real "
        f"(900 Ω) ningún banco fijo cumple las 24 h; por eso el banco adoptado cumple {in_band}/24."
        if sens and sens.x_critical_upper
        else "- (sin sensibilidad)"
    )

    return f"""# Resumen de sustentación — Análisis fasorial y optimización de bancos de capacitores

> Generado automáticamente por `scripts/run_full_analysis.py`. Todos los valores provienen del solucionador
> verificado por `pytest` (Golden Test hora 1 y conservación exacta de potencia compleja) y contrastado con la
> auditoría independiente `scripts/auditoria_independiente.py` (`auditoria_qc_fijo.txt`).

## 1. Datos del sistema

- V₀ = 120∠0° V · R_gen = 0.5 Ω · Z_line = 80 + j900 Ω · T1 = 1:13.2 · T2 = 110:1
- Tarifa = 960 COP/kWh · 365 días/año · Banco = 100 000 COP/kvar · Banda {vg} ∈ [950, 1100] V
- Energía diaria demandada: **{b.demand.p_total_kw.sum():,.0f} kWh** · Demanda reactiva media: **{b.demand.q_total_kvar.mean():.4f} kvar**
- Todas las cargas de la Tabla 1 se modelan en atraso: Q_k = +P_k·tan(arccos(pf_k)).
- Estrategias del Problema 2: **Sin capacitor (Q_C = 0)** y **Banco fijo — óptimo económico (Q_C = {qc:g} kvar)**.
{f"- Problema 2.1 (§7): la misma red con T1 = {b21.params.t1_label} y T2 = {b21.params.t2_label}; banco fijo de {b21.economic.q_c_design_kvar:g} kvar." if b21 is not None else ""}

**Transformadores del Problema 2**

- **T1 — Transformador Elevador (1 kV : 13.2 kV, n₁ = 13.2):** ubicado a la salida del generador; eleva la tensión
  para transportar la potencia con menor corriente y reducir las pérdidas I²R en la línea.
- **T2 — Transformador Reductor (13.2 kV : 120 V, a₂ = 110):** ubicado junto a la barra de carga; reduce la tensión
  de 13.2 kV a V₀ = 120∠0° V para alimentar L1 (residencial) y L2 (industrial).

## 2. Problema 1 — Red directa a 120 V

| Magnitud (hora 1) | Valor |
|---|---:|
| \\|I_line(1)\\| | {abs(p1.i_line[0]):.7f} A ∠ {np.degrees(np.angle(p1.i_line[0])):.8f}° |
| P_loss(1) | {p1.p_loss_kw[0]:,.5f} kW |
| Q_loss(1) | {p1.q_loss_kvar[0]:,.4f} kvar |
| \\|S_gen(1)\\| | {abs(p1.s_gen_kva[0]):,.4f} kVA |

- **Problema 1 (b) — costo de las pérdidas:** {p1.daily_energy_loss_kwh:,.4f} kWh/día × {prm.energy_price_cop_per_kwh:g} COP/kWh =
  **{format_cop(p1_daily_cost)}/día** (exacto: {p1_daily_cost:,.2f} COP; con E_loss redondeada a
  {round(p1.daily_energy_loss_kwh):,} kWh: {format_cop(round(p1.daily_energy_loss_kwh) * prm.energy_price_cop_per_kwh)}/día) → **{format_cop(p1_daily_cost * prm.days_per_year)}/año**.

### Análisis

{_bullets(problem1_analysis(b))}

## 3. Problema 2 — Red con transformadores

### 3.1 Sin capacitor (Q_C = 0)

- R_eq referida al lado de 13.2 kV = 80 + 0.5·13.2² = **{prm.r_eq_line_side:.2f} Ω** (verificado).
- Corriente de línea máxima: **{i_nc.max():.4f} A** (reducción ×{np.abs(p1.i_line).max() / i_nc.max():.0f}).
- Pérdidas diarias: **{e0.daily_loss_kwh:.4f} kWh** → OPEX anual **{format_cop(e0.annual_loss_cost_cop)}**.
- {vg} ∈ [{nc.v_gen_mag.min():.1f}, {nc.v_gen_mag.max():.1f}] V → **{nc.hours_out_of_band}/24 h fuera de banda**.

### 3.2 Respuesta directa a los literales (a)–(e) del Problema 2

**(a) Metodología y criterios.** T1 (elevador 1 kV : 13.2 kV, n₁ = 13.2) a la salida del generador y T2 (reductor
13.2 kV : 120 V, a₂ = 110) junto a la barra de carga. Se resuelve el flujo fasorial hora a hora
(I_load = conj(S_neto/V₀), I_line = I_load/a₂, I_gen = n₁·I_line, V_gen = (V₀·a₂ + I_line·Z_line)/n₁ + R_gen·I_gen).
Criterios: (1) restricción de tensión 950 ≤ {vg} ≤ 1100 V, evaluada con el análisis cuadrático exacto de cada
hora; (2) costo total anual J = OPEX de pérdidas (960 COP/kWh × 365 d) + CAPEX (100 000 COP/kvar). Como ningún
banco fijo cumple (1) las 24 h (§4), se adopta el banco fijo de menor J entre los que mantienen la banda el
máximo de horas posible.

**(b) Costo final del banco.** Q_C = **{qc:g} kvar** → CAPEX = {qc:g} × 100 000 = **{format_cop(ee.capex_cop)}**.

| Alternativa | Q_C instalado | Costo del banco (CAPEX) | OPEX anual de pérdidas | J anual | Cumple [950, 1100] V | fp neto |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(f"| {s.label} | {s.q_c_installed_kvar:.2f} kvar | {format_cop(s.economics.capex_cop)} | {format_cop(s.economics.annual_loss_cost_cop)} | {format_cop(s.economics.total_annual_cost_cop)} | {24 - s.hours_out_of_band}/24 h | {s.pf_status} |" for s in b.strategies.values())}

**(c) \\|I_line(t)\\| (Fig. 15).** Q_C = 0: {i_nc.min():.4f}–{i_nc.max():.4f} A; Q_C = {qc:g} kvar:
{i_ec.min():.4f}–{i_ec.max():.4f} A (×{np.abs(p1.i_line).max() / i_ec.max():.1f} menor que el máximo del Problema 1,
{np.abs(p1.i_line).max():,.2f} A).

**(d) {vg}(t) con banda (Fig. 6, 9 y 10).** Q_C = {qc:g} kvar: {vg} ∈ [{r.v_gen_mag.min():.2f},
{r.v_gen_mag.max():.2f}] V, **{in_band}/24 h en banda**; fuera: hora {out_txt} (violación máxima
{r.max_violation_v:.2f} V).

**(e) P_loss(t) (Fig. 7).** Q_C = {qc:g} kvar: **{ee.daily_loss_kwh:,.4f} kWh/día**
({r.circuit.p_loss_line_kw.sum():,.4f} kWh en R_line = 47.87 %, {r.circuit.p_loss_gen_kw.sum():,.4f} kWh en R_gen = 52.13 %),
costo anual **{format_cop(ee.annual_loss_cost_cop)}** (Q_C = 0: {e0.daily_loss_kwh:,.4f} kWh/día → {format_cop(e0.annual_loss_cost_cop)}/año).

## 4. Diagnóstico exacto de factibilidad (banco fijo)

{vg}² = a·Q_C² + b(t)·Q_C + c(t) es una parábola convexa ⇒ cada hora admite 1 o 2 intervalos
cerrados (rama inductiva y rama sobrecompensada). Solución analítica verificada numéricamente
(malla de 40 001 puntos + `brentq`): desviación máxima **{f.max_numeric_deviation_kvar:.2e} kvar**.

{_md_table(feas_rows)}

- **Intersección global 24 h: {format_set(f.global_set)} → {"FACTIBLE" if f.is_feasible else "INFACTIBLE"}.**
- Pares de horas en conflicto: {", ".join(str(p) for p in f.conflicting_pairs)} (par crítico {f.critical_pair}).
{_critical_pair_text(b)}
- Máximo de horas en banda con un banco fijo: **{eco.band.hours_in_band}/24**, para Q_C ∈ **{format_set(eco.band.window)} kvar**.

## 5. Banco fijo — óptimo económico (Q_C = {qc:g} kvar)

{_md_table(pd.DataFrame(cmp_rows))}

### 5.1 De dónde sale {qc:g} kvar

- En la ventana {format_set(eco.band.window)} kvar ({eco.band.hours_in_band}/24 h en banda) J crece con Q_C
  (dJ/dQ_C = {eco.derivative_at_design:,.0f} COP/kvar), luego el de menor costo es el extremo inferior:
  **{eco.q_c_band_optimum_kvar:.6f} kvar**, que se adopta como **{qc:g} kvar** (resolución de 0.01 kvar hacia el
  interior de la ventana).
- Ese extremo lo fija la hora valle con menor margen: allí {vg} = 950 V. Con {qc:g} kvar el margen mínimo
  dentro de la banda es de **{margin:.4f} V**.

### 5.2 Resultados con Q_C = {qc:g} kvar

- {vg} ∈ [{r.v_gen_mag.min():.3f}, {r.v_gen_mag.max():.3f}] V · **{in_band}/24 h en banda** · fuera: hora {out_txt} ({r.max_violation_v:.3f} V).
- \\|I_line\\| ∈ [{i_ec.min():.4f}, {i_ec.max():.4f}] A · fp neto ∈ [{r.pf_net.min():.4f}, {r.pf_net.max():.4f}] → **{r.pf_status}**.
- Pérdidas: **{ee.daily_loss_kwh:,.4f} kWh/día** → {format_cop(ee.daily_loss_kwh * prm.energy_price_cop_per_kwh)}/día → OPEX **{format_cop(ee.annual_loss_cost_cop)}/año**.
- CAPEX **{format_cop(ee.capex_cop)}** · J = OPEX + CAPEX = **{format_cop(ee.total_annual_cost_cop)}/año**.
- Ahorro anual frente a Q_C = 0: **{format_cop(ee.annual_savings_cop)}** · Payback: **{_payback(ee.payback_days)}** ·
  ROI 1/3/5 años = {" / ".join(format_number(v, 1) + " %" for v in ee.roi_table.values())}.

### 5.3 Perfil de las 24 horas con Q_C = {qc:g} kvar

{_md_table(_hourly_profile(b))}

### 5.4 Observaciones matemáticas

1. **{qc:g} kvar no es el mínimo de J(Q_C).** El mínimo libre está en Q_C = mean(Q) − c_cap/(2·c_e·κ·24) =
   **{eco.q_c_free_kvar:.6f} kvar** (`minimize_scalar`: {eco.q_c_free_numeric_kvar:.6f} kvar; dJ/dQ_C = {eco.derivative_at_free:.2e}),
   con J = {format_cop(ef.total_annual_cost_cop)}/año y payback de {ef.payback_days:.1f} días, pero deja
   {free.hours_out_of_band} h fuera de banda. «Óptimo económico» se entiende aquí como el de menor costo
   **sujeto a la banda de tensión** (máximo de horas dentro).
2. **El costo anual sube.** J({qc:g}) = {format_cop(ee.total_annual_cost_cop)} es
   {ee.total_annual_cost_cop / ef.total_annual_cost_cop:.2f} veces el mínimo libre y
   {ee.total_annual_cost_cop / e0.total_annual_cost_cop:.2f} veces el costo sin capacitor. La causa es física: el banco
   entrega {qc:g} kvar y la carga pide como máximo {b.demand.q_total_kvar.max():.2f} kvar, así que el excedente
   capacitivo circula por la línea las {r.hours_leading} horas y las pérdidas κ·(P² + (Q − Q_C)²) pasan de
   {e0.daily_loss_kwh:,.2f} a {ee.daily_loss_kwh:,.2f} kWh/día (×{ee.daily_loss_kwh / e0.daily_loss_kwh:.2f}).
3. **El ahorro frente a Q_C = 0 es negativo** ({format_cop(ee.annual_savings_cop)}/año): el payback no existe y el
   ROI es negativo en cualquier horizonte. El banco se justifica por regulación de tensión, no por energía.
4. **El factor de potencia neto queda en adelanto las {r.hours_leading} horas** ({r.pf_net.min():.3f}–{r.pf_net.max():.3f}).
   Es inherente a la banda: incluso compensando exactamente la reactiva (Q_neto = 0, fp = 1) la hora {k_unity + 1}
   tendría {vg} = {v_unity[k_unity]:,.2f} V > 1100 V, porque la caída en j900 Ω se suma en cuadratura a la tensión de la carga.
5. **Una hora queda fuera de banda.** Hora {out_txt}: {vg} = {r.v_gen_mag.min():.3f} V. Subir Q_C para recuperarla
   saca de la banda a las horas pico de la tarde; ningún Q_C fijo cumple las 24 h (§4).
6. **El diseño está en el borde de la banda.** El margen mínimo es {margin:.4f} V; una tolerancia de fabricación
   del banco o una variación pequeña de la carga saca de la banda a las horas valle.

## 6. Análisis de las gráficas — banco fijo de {qc:g} kvar frente a Q_C = 0

{chr(10).join(f"**{title.replace('|', chr(92) + '|')}**{chr(10)}{chr(10)}{_bullets(lines)}{chr(10)}" for title, lines in analysis.items())}
{section_21}## {7 + n}. Desarrollo Matemático Paso a Paso — Fase 2 (Problema 2)

Cadena de cálculo de la Fase 2 (T1, línea, T2 y banco Q_C) contrastada con la Fase 1 (red directa). Relaciones:
I_line = I_load / a₂, I_gen = n₁·I_line, V_line,recv = 120·110 = 13 200∠0° V, V_T1,prim = V_line,envío / n₁ y
R_eq referida al lado de 13.2 kV = 80 + 0.5·13.2² = **{prm.r_eq_line_side:.2f} Ω**. La conservación de potencia
compleja se verifica de forma independiente (V_gen·I_gen* frente a S_neto + S_loss,line + S_loss,gen).
La tabla horaria completa de las 24 h está en `fase2_paso_a_paso_24h_qc0.csv`,
`fase2_paso_a_paso_24h_fijo_economico.csv` y `fase1_paso_a_paso_24h.csv`.

### {7 + n}.1 Hora 1 (contraste con el cálculo manual de la Fase 1)

{_step_by_step_hour(b, 1)}

### {7 + n}.2 Hora 8 (fuera de banda con el banco fijo)

{_step_by_step_hour(b, 8)}

### {7 + n}.3 Hora 12 (hora pico)

{_step_by_step_hour(b, 12)}

## {8 + n}. Auditoría independiente

`scripts/auditoria_independiente.py` recalcula las 24 horas con Q_C = {qc:g} kvar sin importar `src/` (solo la
biblioteca estándar) por dos caminos —tramo a tramo y con la impedancia reflejada al generador— y comprueba la
conservación de potencia compleja, la invariancia de potencia en T1 y T2, la fórmula de pérdidas, las cuentas
económicas, el mínimo libre de J y la ventana de máximo cumplimiento de tensión; al final contrasta sus valores con
`p2_sin_capacitor_horario.csv` y `p2_fijo_economico_horario.csv`. El resultado queda en `auditoria_qc_fijo.txt` y
`auditoria_qc_fijo_24h.csv`. El mismo programa audita el Problema 2.1 (línea a 66 kV) y **deduce por su cuenta el
banco de cada caso** a partir de la ventana de máximo cumplimiento de tensión y del mínimo de J dentro de ella
(`auditoria_p21.txt`, `auditoria_p21_24h.csv`).

## {9 + n}. Sensibilidad (X_line)

{sens_txt}

## {10 + n}. Gráficas y comentarios técnicos

{charts_md}

## {11 + n}. Guion de exposición (10 minutos)

| Tiempo | Bloque | Mensaje clave | Apoyo |
|---|---|---|---|
| 0:00–1:00 | Contexto | Red de 24 h con carga residencial + industrial, 80 + j900 Ω de línea y restricción de tensión en el generador. | Fig. 4 |
| 1:00–2:30 | Problema 1 | Golden test hora 1: {abs(p1.i_line[0]):.2f} A, {p1.p_loss_kw[0]:,.0f} kW de pérdidas para servir 70 kW. Pérdidas ×{p1.daily_energy_loss_kwh / p1.daily_energy_served_kwh:,.0f} la energía útil. | Fig. 1–3 |
| 2:30–3:30 | Transformadores | Elevar a 13.2 kV divide I por 110 y las pérdidas por 12 100. R_gen referida = 87.12 Ω ⇒ R_eq = 167.12 Ω. | Fig. 5 |
| 3:30–4:30 | Problema de tensión | Sin capacitor {vg} llega a {nc.v_gen_mag.max():,.0f} V: la caída jI·X en 900 Ω eleva la tensión de envío. | Fig. 6, 12 |
| 4:30–6:00 | Factibilidad | Análisis cuadrático exacto: ventanas horarias disjuntas (par {f.critical_pair}) ⇒ ningún banco fijo cumple las 24 h; el máximo es {eco.band.hours_in_band}/24. | Fig. 9, 10 |
| 6:00–7:30 | Banco fijo | Q_C = {qc:g} kvar: {in_band}/24 h en banda, {vg} ∈ [{r.v_gen_mag.min():.0f}, {r.v_gen_mag.max():.0f}] V; fuera la hora {out_txt}. | Fig. 6, 15 |
| 7:30–8:45 | Costo | CAPEX {format_cop(ee.capex_cop)}; pérdidas {ee.daily_loss_kwh:,.0f} kWh/día (×{ee.daily_loss_kwh / e0.daily_loss_kwh:.2f}); J = {format_cop(ee.total_annual_cost_cop)}/año. El mínimo libre de J ({eco.q_c_free_kvar:.2f} kvar) no regula tensión. | Fig. 7, 8, 13 |
| 8:45–9:30 | fp neto | El banco sobrecompensa: fp en adelanto {r.pf_net.min():.3f}–{r.pf_net.max():.3f} las {r.hours_leading} h. Regular tensión con esta línea exige adelanto. | Fig. 11, 16 |
| 9:30–10:00 | Cierre | Sensibilidad: con X ≤ {sens.x_critical_upper if sens and sens.x_critical_upper else float("nan"):.1f} Ω un banco fijo cumpliría las 24 h. Demo del dashboard. | Fig. 14, demo |
"""


def export_markdown(
    b: AnalysisBundle,
    charts: list[tuple[ChartSpec, Path]],
    out_path: Path,
    b21: AnalysisBundle | None = None,
    charts21: list[tuple[ChartSpec, Path]] | None = None,
) -> Path:
    out_path.write_text(build_markdown_report(b, charts, b21, charts21), encoding="utf-8")
    return out_path


def export_all(b: AnalysisBundle, out_dir: Path, b21: AnalysisBundle | None = None) -> dict[str, list[Path]]:
    """Exporta figuras, tablas y reporte. Con ``b21`` agrega el Problema 2.1 y la comparación 2 vs. 2.1."""
    charts = export_charts(b, out_dir)
    tables = export_tables(b, out_dir)
    charts21: list[tuple[ChartSpec, Path]] = []
    if b21 is not None:
        charts21 = export_charts(b21, out_dir, chart_catalog_21(b21, b))
        tables += export_tables_21(b21, b, out_dir)
    md = export_markdown(b, charts, out_dir / "resumen_sustentacion.md", b21, charts21)
    return {"charts": [p for _, p in charts + charts21], "tables": tables, "report": [md]}


__all__ = [
    "DPI",
    "Strategy",
    "chart_catalog",
    "chart_catalog_21",
    "export_all",
    "export_charts",
    "export_markdown",
    "export_tables",
    "export_tables_21",
]
