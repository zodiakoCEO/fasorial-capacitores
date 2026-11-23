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
from src.optimization.economics import cumulative_cash_flow, format_cop, format_number
from src.optimization.pipeline import AnalysisBundle
from src.physics.step_by_step import hourly_step_table, power_balance_error
from src.reporting import theme as T
from src.reporting.charts import nice_current_scale, pf_label, phasor_components

DPI = 300
TEACHING_HOUR = 12  # hora pico usada en las figuras docentes

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
    ax.set_title("Problema 2 — |V_gen(t)| por estrategia (× rojo = fuera de banda)")
    ax.set_ylabel("|V_gen| [V]")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), fontsize=7.5, ncols=2)
    _hours_axis(ax)
    return fig


def _losses_stacked(b: AnalysisBundle) -> Figure:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True, constrained_layout=True)
    for ax, r in zip(axes, (b.no_capacitor, b.switched.result), strict=True):
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
    fig.suptitle("Problema 2 — Pérdidas activas apiladas (línea vs. generador)", x=0.01, ha="left", fontweight="bold")
    return fig


def _cost_curve(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    g = b.pareto.grid[b.pareto.grid["Q_C_kvar"] <= 480]
    ax.plot(g["Q_C_kvar"], g["Costo_total_anual_COP"] / 1e6, color=T.SERIES[0], lw=2, label="J(Q_C)")
    for r, name in ((b.economic.result, "Óptimo económico"), (b.pareto.minimax, "Mínima violación")):
        ax.scatter(
            [r.q_c_installed_kvar],
            [r.economics.total_annual_cost_cop / 1e6],
            s=60,
            zorder=5,
            color=T.STRATEGY_COLOR[r.strategy],
            edgecolor=T.SURFACE,
            lw=1.5,
        )
        ax.annotate(
            f"{name}\nQ_C={r.q_c_installed_kvar:.2f} kvar\nJ={r.economics.total_annual_cost_cop / 1e6:,.2f} M",
            (r.q_c_installed_kvar, r.economics.total_annual_cost_cop / 1e6),
            textcoords="offset points",
            xytext=(10, 10) if name == "Óptimo económico" else (-14, 6),
            ha="left" if name == "Óptimo económico" else "right",
            fontsize=8.5,
            color=T.INK_SECONDARY,
        )
    ax.set_title("Costo total anual J(Q_C) = OPEX pérdidas + CAPEX (banco fijo)")
    ax.set_xlabel("Q_C [kvar]")
    ax.set_ylabel("J [millones COP/año]")
    return fig


def _feasibility_map(b: AnalysisBundle) -> Figure:
    fig, ax = _new((9, 4.8))
    f = b.feasibility
    for h, s in zip(f.hours, f.hourly_sets, strict=True):
        for k, iv in enumerate(s):
            ax.bar(h, iv.width, bottom=iv.lo, width=0.6, color=T.GOOD, alpha=0.85 if k == 0 else 0.4, lw=0)
    ax.axhline(
        b.economic.result.q_c_installed_kvar,
        color=T.SERIES[1],
        lw=2,
        label=f"Fijo económico ({b.economic.result.q_c_installed_kvar:.1f} kvar)",
    )
    ax.axhline(
        b.pareto.minimax.q_c_installed_kvar,
        color=T.SERIES[4],
        lw=2,
        ls="--",
        label=f"Fijo mínima violación ({b.pareto.minimax.q_c_installed_kvar:.1f} kvar)",
    )
    ax.step(
        f.hours,
        b.switched.result.q_c_profile_kvar,
        where="mid",
        color=T.SERIES[2],
        lw=2.2,
        label=f"Banco por pasos ({b.switched.n_steps}×{b.switched.step_kvar:g} kvar)",
    )
    ax.set_ylim(0, 480)
    ax.set_title("Mapa de factibilidad horaria: Q_C con 950 ≤ |V_gen| ≤ 1100 V (verde)")
    ax.set_ylabel("Q_C [kvar]")
    ax.legend(loc="upper left", fontsize=8)
    _hours_axis(ax)
    return fig


def _pareto(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    g, fr = b.pareto.grid, b.pareto.front
    ax.scatter(
        g["Violacion_max_V"], g["Costo_total_anual_COP"] / 1e6, s=3, color=T.MUTED, alpha=0.3, label="Q_C evaluados"
    )
    ax.plot(
        fr["Violacion_max_V"], fr["Costo_total_anual_COP"] / 1e6, color=T.SERIES[0], lw=2, label="Frontera de Pareto"
    )
    for r, name in ((b.economic.result, "Óptimo económico"), (b.pareto.minimax, "Minimax tensión")):
        ax.scatter(
            [r.max_violation_v],
            [r.economics.total_annual_cost_cop / 1e6],
            s=70,
            zorder=5,
            color=T.STRATEGY_COLOR[r.strategy],
            edgecolor=T.SURFACE,
            lw=1.5,
        )
        ax.annotate(
            name,
            (r.max_violation_v, r.economics.total_annual_cost_cop / 1e6),
            textcoords="offset points",
            xytext=(8, 6),
            fontsize=9,
        )
    ax.set_title("Pareto banco fijo: costo anual vs. violación máxima de tensión")
    ax.set_xlabel("Violación máxima fuera de [950, 1100] V [V]")
    ax.set_ylabel("J [millones COP/año]")
    ax.legend(loc="upper right")
    return fig


def _triangle(b: AnalysisBundle) -> Figure:
    t = TEACHING_HOUR - 1
    p, ql = b.demand.p_total_kw[t], b.demand.q_total_kvar[t]
    qc = b.switched.result.q_c_profile_kvar[t]
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
    ax.text(p * 1.08, (ql + qn) / 2, f"−Q_C = −{qc:.0f} kvar", color=T.INK)
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
    ax.set_title(f"Triángulo de potencias — hora {TEACHING_HOUR} (banco por pasos)")
    return fig


def _phasor(b: AnalysisBundle) -> Figure:
    t = TEACHING_HOUR - 1
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.4), constrained_layout=True)
    lim, i_max = 0.0, 0.0
    for r in (b.no_capacitor, b.switched.result):
        ph = phasor_components(r.circuit, b.params, t, b.demand)
        lim = max(lim, abs(ph["V_gen"]), abs(ph["V0_ref"] + ph["drop"]))
        i_max = max(i_max, abs(ph["I_gen"]))
    scale = nice_current_scale(i_max)
    lim *= 1.08
    for ax, r in zip(axes, (b.no_capacitor, b.switched.result), strict=True):
        ph = phasor_components(r.circuit, b.params, t, b.demand)
        ax.grid(False)
        th = np.linspace(0, np.pi / 2, 100)
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
            vg.real * 0.45,
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
        ax.set_xlim(-0.35 * lim, 1.05 * lim)
        ax.set_ylim(-0.45 * lim, 0.85 * lim)
        ax.set_aspect("equal")
        ax.axhline(0, color="#c3c2b7", lw=0.8)
        ax.axvline(0, color="#c3c2b7", lw=0.8)
        ax.set_title(f"{r.label} — Q_C = {r.q_c_profile_kvar[t]:.0f} kvar", fontsize=10)
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
    for r in (b.economic.result, b.switched.result):
        cf = cumulative_cash_flow(r.economics, 5, 24)
        color = T.STRATEGY_COLOR[r.strategy]
        ax.plot(cf["mes"], cf["flujo_acumulado_COP"] / 1e6, color=color, lw=2, label=r.label)
        pb = r.economics.payback_months
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
    ax.set_title("Flujo de caja acumulado (5 años, sin descuento)")
    ax.set_xlabel("Meses desde la inversión")
    ax.set_ylabel("Flujo acumulado [millones COP]")
    ax.legend(loc="upper left")
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


def _schedule(b: AnalysisBundle) -> Figure:
    fig, ax = _new()
    sw = b.switched
    ax.bar(
        sw.result.circuit.hours,
        sw.result.q_c_profile_kvar,
        color=T.SERIES[2],
        width=0.72,
        edgecolor=T.SURFACE,
        lw=1,
        label="Q_C(t) despachado",
    )
    ax.plot(
        b.demand.hours,
        b.demand.q_total_kvar,
        color=T.SERIES[1],
        lw=2,
        marker="o",
        ms=4,
        label="Q_L(t) demanda reactiva",
    )
    ax.axhline(sw.q_c_max_kvar, color=T.MUTED, ls="--", lw=1)
    ax.text(
        0.7, sw.q_c_max_kvar + 6, f"Q_C,max instalado = {sw.q_c_max_kvar:g} kvar", color=T.INK_SECONDARY, fontsize=8.5
    )
    ax.set_title(f"Banco automático: {sw.n_steps} pasos × {sw.step_kvar:g} kvar — programa horario")
    ax.set_ylabel("kvar")
    ax.legend(loc="upper left")
    _hours_axis(ax)
    return fig


def _p2_current(b: AnalysisBundle) -> Figure:
    fig, ax = _new((9, 4.6))
    for r in (b.no_capacitor, b.switched.result, b.switched_lagging.result):
        i_mag = np.abs(r.circuit.i_line)
        _plot_line(ax, r.circuit.hours, i_mag, r.label, T.STRATEGY_COLOR[r.strategy], T.STRATEGY_DASH[r.strategy])
    rec = np.abs(b.switched.result.circuit.i_line)
    k_max, k_min = int(np.argmax(rec)), int(np.argmin(rec))
    arrow = {"arrowstyle": "-", "color": T.MUTED, "lw": 0.8}
    ax.annotate(
        f"Banco recomendado: máx {rec[k_max]:.3f} A (h{k_max + 1})",
        (k_max + 1, rec[k_max]),
        xytext=(2.0, 15.0),
        fontsize=8.5,
        color=T.INK,
        arrowprops=arrow,
    )
    ax.annotate(
        f"mín {rec[k_min]:.3f} A (h{k_min + 1})",
        (k_min + 1, rec[k_min]),
        xytext=(5.5, 1.5),
        fontsize=8.5,
        color=T.INK,
        arrowprops=arrow,
    )
    ax.set_ylim(0, None)
    ax.set_title("Problema 2 — Corriente de línea |I_line(t)| en 13.2 kV")
    ax.set_ylabel("|I_line| [A]")
    ax.legend(loc="lower right", fontsize=8)
    _hours_axis(ax)
    return fig


def _lagging_limit(b: AnalysisBundle) -> Figure:
    fig, ax = _new((9, 4.8))
    p, lag = b.params, b.lagging_limit
    ax.axhspan(p.v_gen_min, p.v_gen_max, color=T.GOOD, alpha=0.12, lw=0)
    for lim in (p.v_gen_min, p.v_gen_max):
        ax.axhline(lim, color=T.GOOD, lw=1, ls=":")
    ax.fill_between(lag.hours, lag.v_gen_floor, 2200, color=T.MUTED, alpha=0.10, lw=0, step=None)
    ax.plot(lag.hours, lag.v_gen_floor, color=T.INK_SECONDARY, lw=2, ls="--", label="Cota en atraso (fp = 1)")
    for r in (b.fixed_lagging.result, b.switched_lagging.result, b.switched.result):
        _plot_line(ax, r.circuit.hours, r.v_gen_mag, r.label, T.STRATEGY_COLOR[r.strategy], T.STRATEGY_DASH[r.strategy])
    i = lag.worst_index
    ax.annotate(
        f"h{lag.worst_hour}: {lag.max_floor_v:,.2f} V > 1100 V",
        (lag.hours[i], lag.v_gen_floor[i]),
        textcoords="offset points",
        xytext=(0, -22),
        ha="center",
        fontsize=8.5,
        color=T.INK,
    )
    ax.set_ylim(900, 2000)
    ax.set_title("fp en atraso vs. regulación de tensión — región alcanzable sin adelanto (gris)")
    ax.set_ylabel("|V_gen| [V]")
    ax.legend(loc="upper left", fontsize=8)
    _hours_axis(ax)
    return fig


# ==================================================================================
# Catálogo de figuras con comentario técnico
# ==================================================================================
def chart_catalog(b: AnalysisBundle) -> list[ChartSpec]:
    p1 = b.problem1
    e = b.economic.result
    sw = b.switched
    f = b.feasibility
    nc = b.no_capacitor
    i1_max = float(np.abs(p1.i_line).max())
    i_nc, i_sw = np.abs(nc.circuit.i_line), np.abs(sw.result.circuit.i_line)
    i_sl = np.abs(b.switched_lagging.result.circuit.i_line)
    idx = {int(h): i for i, h in enumerate(f.hours)}
    ha, hb = f.critical_pair or (8, 19)
    set_a, set_b = format_set(f.hourly_sets[idx[ha]]), format_set(f.hourly_sets[idx[hb]])

    def loss_txt(r: StrategyResult) -> str:
        c = r.circuit
        return (
            f"{r.label}: {c.daily_energy_loss_kwh:,.3f} kWh/día ({c.p_loss_line_kw.sum():,.3f} en R_line + "
            f"{c.p_loss_gen_kw.sum():,.3f} en R_gen) → {format_cop(r.economics.annual_loss_cost_cop)}/año"
        )

    return [
        ChartSpec(
            "01_p1_corriente_linea.png",
            "Problema 1 — |I_line(t)|",
            f"A 120 V la corriente alcanza {np.abs(p1.i_line).max():,.0f} A en la hora pico. Para transportar "
            "~150 kW a baja tensión se requieren corrientes de cientos de amperios; con 80 Ω de resistencia "
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
            "La potencia aparente del generador (centenares de MVA) está dominada por Q_loss = |I|²·900; "
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
            "|V_gen(t)| por estrategia",
            "Sin capacitor |V_gen| llega a {b.no_capacitor.v_gen_mag.max():,.0f} V. El óptimo económico "
            f"({e.q_c_installed_kvar:.2f} kvar) deja {e.hours_out_of_band} h fuera de banda. Solo el banco "
            f"automático mantiene las 24 h dentro de [950, 1100] V (|V_gen| ∈ [{sw.result.v_gen_mag.min():.2f}, "
            f"{sw.result.v_gen_mag.max():.2f}] V). Hora {ha} vs. hora {hb}: con carga liviana (h{ha}, "
            f"{b.demand.p_total_kw[idx[ha]]:g} kW) la banda exige Q_C ∈ {set_a} kvar; en la hora {hb} "
            f"({b.demand.p_total_kw[idx[hb]]:g} kW) exige Q_C ∈ {set_b} kvar. Los conjuntos son disjuntos: "
            "ningún banco fijo sirve a ambas horas, de ahí la necesidad del banco por pasos.",
            _vgen,
        ),
        ChartSpec(
            "07_p2_perdidas_apiladas.png",
            "Pérdidas apiladas línea vs. generador",
            "R_gen = 0.5 Ω referida al lado de 13.2 kV equivale a 0.5·13.2² = 87.12 Ω, más que los 80 Ω de "
            "la línea: el generador disipa 87.12/167.12 = 52.13 % de las pérdidas y la línea 47.87 % "
            f"(R_eq = 167.12 Ω) en todas las horas. {loss_txt(nc)}. {loss_txt(sw.result)}.",
            _losses_stacked,
        ),
        ChartSpec(
            "08_costo_total_vs_qc.png",
            "Costo total anual J(Q_C)",
            "J(Q_C) es una parábola convexa: el CAPEX lineal (100 000 COP/kvar) desplaza el mínimo de "
            "pérdidas (Q_C = media de Q(t)) ligeramente a la izquierda. El punto de mínima violación es "
            "~6 veces más costoso.",
            _cost_curve,
        ),
        ChartSpec(
            "09_mapa_factibilidad.png",
            "Mapa de factibilidad horaria",
            f"Las ventanas verdes no comparten un valor común: el par crítico es la hora {f.critical_pair}. "
            "Por eso ningún banco fijo cumple la banda, mientras el programa escalonado recorre las "
            "ventanas hora a hora.",
            _feasibility_map,
        ),
        ChartSpec(
            "10_pareto.png",
            "Frontera de Pareto (banco fijo)",
            "Reducir la violación de tensión con un banco fijo exige sobrecompensar (corriente capacitiva) "
            "y multiplica las pérdidas: no existe un punto que sea simultáneamente barato y factible.",
            _pareto,
        ),
        ChartSpec(
            "11_triangulo_potencias.png",
            f"Triángulo de potencias (h{TEACHING_HOUR})",
            "En la hora pico el banco inyecta más vars que los consumidos (fp en adelanto): es la condición "
            "necesaria para que la caída jI·X 'reste' tensión al generador.",
            _triangle,
        ),
        ChartSpec(
            "12_diagrama_fasorial.png",
            f"Diagrama fasorial (h{TEACHING_HOUR})",
            "Con corriente en atraso la caída jI·X (900 Ω) es casi paralela a V₀ y eleva |V_gen|; con "
            "corriente en adelanto gira hacia la parte imaginaria y |V_gen| vuelve a la banda.",
            _phasor,
        ),
        ChartSpec(
            "13_flujo_caja.png",
            "Flujo de caja acumulado",
            f"El banco fijo económico recupera su inversión en {e.economics.payback_days:,.0f} días; el banco "
            f"automático en {sw.result.economics.payback_days:,.0f} días y además garantiza calidad de tensión.",
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
            "15_programa_banco_pasos.png",
            "Programa del banco automático",
            f"{sw.n_steps} escalones de {sw.step_kvar:g} kvar: 2 pasos en la madrugada, hasta "
            f"{int(sw.result.q_c_profile_kvar.max() / sw.step_kvar)} en el pico industrial.",
            _schedule,
        ),
        ChartSpec(
            "16_fp_atraso_vs_regulacion.png",
            "fp en atraso vs. regulación de tensión",
            f"Con Q_net ≥ 0 la menor |V_gen| alcanzable es la curva discontinua (Q_net = 0, fp = 1); en la hora "
            f"{b.lagging_limit.worst_hour} vale {b.lagging_limit.max_floor_v:,.2f} V > 1100 V. Los diseños 100 % en "
            "atraso no pueden entrar a la banda en horas pico; solo la sobrecompensación (banco por pasos) lo logra.",
            _lagging_limit,
        ),
        ChartSpec(
            "17_p2_corriente_linea.png",
            "Problema 2 — |I_line(t)|",
            f"Con Q_C = 0 la corriente de línea va de {i_nc.min():.4f} A (h{int(np.argmin(i_nc)) + 1}) a "
            f"{i_nc.max():.4f} A (h{int(np.argmax(i_nc)) + 1}); frente al máximo del Problema 1 "
            f"({i1_max:,.2f} A) es {i1_max / i_nc.max():.0f} veces menor. Con el banco automático recomendado "
            f"va de {i_sw.min():.4f} A a {i_sw.max():.4f} A (×{i1_max / i_sw.max():.1f} menor que P1) y con el "
            f"banco 100 % en atraso de {i_sl.min():.4f} A a {i_sl.max():.4f} A: la sobrecompensación que exige "
            "la banda de tensión aumenta ligeramente la corriente en algunas horas, mientras que el banco en "
            "atraso la reduce al mínimo.",
            _p2_current,
        ),
    ]


def export_charts(b: AnalysisBundle, out_dir: Path) -> list[tuple[ChartSpec, Path]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for spec in chart_catalog(b):
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
    tables: dict[str, pd.DataFrame] = {
        "p1_horario.csv": b.problem1.to_dataframe(),
        "p2_sin_capacitor_horario.csv": b.no_capacitor.circuit.to_dataframe(),
        "p2_fijo_economico_horario.csv": b.economic.result.circuit.to_dataframe(),
        "p2_fijo_minima_violacion_horario.csv": b.pareto.minimax.circuit.to_dataframe(),
        "p2_banco_pasos_horario.csv": b.switched.result.circuit.to_dataframe(),
        "factibilidad_horaria.csv": b.feasibility.to_dataframe(),
        "comparativa_estrategias.csv": b.comparison_table(),
        "economia_estrategias.csv": pd.DataFrame(
            [{"Estrategia": r.label, **r.economics.as_dict()} for r in b.strategies.values()]
        ),
        "pareto_malla.csv": b.pareto.grid,
        "pareto_frontera.csv": b.pareto.front,
        "banco_pasos_programa.csv": b.switched.schedule,
        "banco_pasos_curva_costo.csv": b.switched.cost_curve,
        "p2_fijo_atraso_horario.csv": b.fixed_lagging.result.circuit.to_dataframe(),
        "p2_banco_pasos_atraso_horario.csv": b.switched_lagging.result.circuit.to_dataframe(),
        "banco_pasos_atraso_programa.csv": b.switched_lagging.schedule,
        "banco_pasos_atraso_curva_costo.csv": b.switched_lagging.cost_curve,
        "limite_tension_fp_atraso.csv": b.lagging_limit.to_dataframe(),
        "fase1_paso_a_paso_24h.csv": hourly_step_table(b.demand, b.problem1, b.params),
        "fase2_paso_a_paso_24h_qc0.csv": hourly_step_table(b.demand, b.no_capacitor.circuit, b.params),
        "fase2_paso_a_paso_24h_banco_atraso.csv": hourly_step_table(
            b.demand, b.switched_lagging.result.circuit, b.params
        ),
        "fase2_paso_a_paso_24h_banco_pasos.csv": hourly_step_table(b.demand, b.switched.result.circuit, b.params),
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
# Reporte Markdown
# ==================================================================================
def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---:" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


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


def _step_by_step_hour(b: AnalysisBundle, hour: int) -> str:
    """Tabla del desarrollo numérico de una hora: Fase 1 vs. Fase 2 (Q_C = 0) vs. Fase 2 con banco en atraso."""
    t = hour - 1
    d, prm = b.demand, b.params
    cases = (
        ("Fase 1 (red directa)", b.problem1),
        ("Fase 2, Q_C = 0", b.no_capacitor.circuit),
        (f"Fase 2, {b.switched_lagging.result.label}", b.switched_lagging.result.circuit),
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
        ("I_line", "Fase 1: I_load · Fase 2: I_load / a₂ (110)"),
        ("I_gen", "Fase 1: I_line · Fase 2: n₁·I_line (13.2)"),
        ("V_line,envío", "V_recv + I_line·(80 + j900)"),
        ("V_T1,prim", "V_line,envío / n₁"),
        ("V_gen", "V_T1,prim + 0.5·I_gen"),
        ("P_loss,line", r"\|I_line\|²·80 / 1000"),
        ("P_loss,gen", r"\|I_gen\|²·0.5 / 1000"),
        ("P_loss,total", r"suma (Fase 2: \|I_line\|²·167.12/1000)"),
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


def build_markdown_report(b: AnalysisBundle, charts: list[tuple[ChartSpec, Path]]) -> str:
    p1, nc, e, par, sw, f = b.problem1, b.no_capacitor, b.economic, b.pareto, b.switched, b.feasibility
    ee, se = e.result.economics, sw.result.economics
    sens = b.sensitivity
    cmp_rows = []
    for r in [*b.strategies.values(), *([sw.continuous_reference] if sw.continuous_reference else [])]:
        ec = r.economics
        cmp_rows.append(
            {
                "Estrategia": r.label,
                "Q_C inst. [kvar]": f"{r.q_c_installed_kvar:.3f}",
                "I_line máx [A]": f"{np.abs(r.circuit.i_line).max():.3f}",
                "E_loss [kWh/día]": f"{ec.daily_loss_kwh:.3f}",
                "CAPEX": format_cop(ec.capex_cop),
                "OPEX anual": format_cop(ec.annual_loss_cost_cop),
                "J anual": format_cop(ec.total_annual_cost_cop),
                "Ahorro anual": format_cop(ec.annual_savings_cop),
                "Payback [días]": format_number(ec.payback_days, 1),
                "V_gen mín–máx [V]": f"{r.v_gen_mag.min():.1f}–{r.v_gen_mag.max():.1f}",
                "Horas fuera": r.hours_out_of_band,
                "Viol. máx [V]": f"{r.max_violation_v:.2f}",
                "fp_neto mín–máx": f"{r.pf_net.min():.3f}–{r.pf_net.max():.3f}",
                "Estado fp (24 h)": r.pf_status,
            }
        )
    fl, sl, lag = b.fixed_lagging, b.switched_lagging, b.lagging_limit
    p1_daily_cost = p1.daily_energy_loss_kwh * b.params.energy_price_cop_per_kwh
    lag_df = lag.to_dataframe()
    lag_rows = pd.DataFrame(
        {
            "Hora": lag_df["hour"],
            "Q_carga [kvar]": lag_df["Q_load_kvar"].map(lambda x: f"{x:.4f}"),
            "V_gen con Q_C=0 [V]": lag_df["V_gen_QC0_V"].map(lambda x: f"{x:.2f}"),
            "V_gen mín. en atraso (fp=1) [V]": lag_df["V_gen_min_en_atraso_V"].map(lambda x: f"{x:.2f}"),
            "Banda alcanzable en atraso": lag_df["banda_alcanzable_en_atraso"].map(lambda x: "sí" if x else "no"),
            "Q_C mín. banda [kvar]": lag_df["Q_C_min_banda_kvar"].map(lambda x: f"{x:.3f}"),
            "Q_neto requerido [kvar]": lag_df["Q_net_requerido_banda_kvar"].map(lambda x: f"{x:.3f}"),
            "fp requerido": lag_df["fp_requerido_banda"],
        }
    )
    sl_sched = sl.schedule.copy()
    for col_name, fmt in (
        ("Q_load_kvar", "{:.4f}"),
        ("Q_C_kvar", "{:g}"),
        ("Q_net_kvar", "{:.4f}"),
        ("pf_net", "{:.4f}"),
        ("V_gen_V", "{:.2f}"),
        ("P_loss_kW", "{:.4f}"),
    ):
        sl_sched[col_name] = sl_sched[col_name].map(fmt.format)
    h12 = 12 - 1
    feas_rows = pd.DataFrame({"Hora": f.hours, "Q_C factible [kvar]": [format_set(s) for s in f.hourly_sets]})
    sched = sw.schedule.copy()
    sched["Q_C_kvar"] = sched["Q_C_kvar"].map(lambda x: f"{x:g}")
    sched["V_gen_V"] = sched["V_gen_V"].map(lambda x: f"{x:.2f}")
    sched["P_loss_kW"] = sched["P_loss_kW"].map(lambda x: f"{x:.3f}")

    charts_md = "\n\n".join(
        f"### {i}. {spec.title}\n\n![{spec.title}]({path.name})\n\n**Comentario técnico:** {spec.comment}"
        for i, (spec, path) in enumerate(charts, 1)
    )

    sens_txt = (
        f"- Rangos de X_line con banco **fijo** factible: **{format_set(sens.feasible_ranges)} Ω**.\n"
        f"- X_line crítica (al reducir desde 900 Ω): **{sens.x_critical_upper:.4f} Ω**. Con la reactancia real "
        f"(900 Ω) un banco fijo es infactible."
        if sens and sens.x_critical_upper
        else "- (sin sensibilidad)"
    )

    return f"""# Resumen de sustentación — Análisis fasorial y optimización de bancos de capacitores

> Generado automáticamente por `scripts/run_full_analysis.py`. Todos los valores provienen del solucionador
> verificado por `pytest` (Golden Test hora 1 y conservación exacta de potencia compleja).

## 1. Datos del sistema

- V₀ = 120∠0° V · R_gen = 0.5 Ω · Z_line = 80 + j900 Ω · T1 = 1:13.2 · T2 = 110:1
- Tarifa = 960 COP/kWh · 365 días/año · Banco = 100 000 COP/kvar · Banda |V_gen| ∈ [950, 1100] V
- Energía diaria demandada: **{b.demand.p_total_kw.sum():,.0f} kWh** · Demanda reactiva media: **{b.demand.q_total_kvar.mean():.4f} kvar**
- Todas las cargas de la Tabla 1 se modelan en atraso: Q_k = +P_k·tan(arccos(pf_k)).

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

- Corriente máxima: **{np.abs(p1.i_line).max():,.2f} A** (hora {int(np.argmax(np.abs(p1.i_line))) + 1}).
- Pérdidas diarias: **{p1.daily_energy_loss_kwh:,.2f} kWh** frente a {p1.daily_energy_served_kwh:,.0f} kWh útiles
  (×{p1.daily_energy_loss_kwh / p1.daily_energy_served_kwh:,.0f}).
- **Problema 1 (b) — costo de las pérdidas:** {p1.daily_energy_loss_kwh:,.4f} kWh/día × {b.params.energy_price_cop_per_kwh:g} COP/kWh =
  **{format_cop(p1_daily_cost)}/día** (exacto: {p1_daily_cost:,.2f} COP; con E_loss redondeada a
  {round(p1.daily_energy_loss_kwh):,} kWh: {format_cop(round(p1.daily_energy_loss_kwh) * b.params.energy_price_cop_per_kwh)}/día) → **{format_cop(p1_daily_cost * b.params.days_per_year)}/año**.
- Conclusión: distribuir a 120 V a través de 80 + j900 Ω es inviable; se requiere elevar la tensión.

## 3. Problema 2 — Red con transformadores (Q_C = 0)

- R_eq referida al lado de 13.2 kV = 80 + 0.5·13.2² = **{b.params.r_eq_line_side:.2f} Ω** (verificado).
- Corriente de línea máxima: **{np.abs(nc.circuit.i_line).max():.4f} A** (reducción ×{np.abs(p1.i_line).max() / np.abs(nc.circuit.i_line).max():.0f}).
- Pérdidas diarias: **{nc.economics.daily_loss_kwh:.4f} kWh** → OPEX anual **{format_cop(nc.economics.annual_loss_cost_cop)}**.
- \\|V_gen\\| ∈ [{nc.v_gen_mag.min():.1f}, {nc.v_gen_mag.max():.1f}] V → **{nc.hours_out_of_band}/24 h fuera de banda**.

### 3.1 Respuesta directa a los literales (a)–(e) del Problema 2

**(a) Metodología y criterios.** T1 (elevador 1 kV : 13.2 kV, n₁ = 13.2) a la salida del generador y T2 (reductor
13.2 kV : 120 V, a₂ = 110) junto a la barra de carga. Se resuelve el flujo fasorial hora a hora
(I_load = conj(S_neto/V₀), I_line = I_load/a₂, I_gen = n₁·I_line, V_gen = (V₀·a₂ + I_line·Z_line)/n₁ + R_gen·I_gen).
Criterios de decisión: (1) costo total anual J = OPEX de pérdidas (960 COP/kWh × 365 d) + CAPEX (100 000 COP/kvar);
(2) restricción dura 950 ≤ \\|V_gen\\| ≤ 1100 V las 24 h (análisis cuadrático exacto); (3) requisito operativo
de fp neto en atraso (Q_net ≥ 0), analizado aparte por ser físicamente incompatible con (2) en horas pico.

**(b) Costo final del banco y recomendación.**

| Alternativa | Q_C instalado | Costo del banco (CAPEX) | J anual | Cumple [950, 1100] V | fp neto |
|---|---:|---:|---:|---:|---:|
{chr(10).join(f"| {r.label} | {r.q_c_installed_kvar:.4f} kvar | {format_cop(r.economics.capex_cop, 2)} | {format_cop(r.economics.total_annual_cost_cop)} | {24 - r.hours_out_of_band}/24 h | {r.pf_status} |" for r in (sw.result, sl.result, fl.result, e.result))}

**Recomendación:** banco automático **{sw.n_steps} × {sw.step_kvar:g} kvar = {sw.q_c_max_kvar:g} kvar**, costo
**{format_cop(se.capex_cop)}**: es la única alternativa que cumple la restricción de tensión las 24 h, con ahorro de
{format_cop(se.annual_savings_cop)}/año y payback de {se.payback_days:.1f} días. Si el operador exige fp en atraso, la
alternativa es el banco en atraso {sl.n_steps} × {sl.step_kvar:g} kvar ({format_cop(sl.result.economics.capex_cop)}, J mínimo),
aceptando que \\|V_gen\\| ∈ [{sl.result.v_gen_mag.min():.2f}, {sl.result.v_gen_mag.max():.2f}] V queda fuera de la banda (teorema §5.4).

**(c) \\|I_line(t)\\| (Fig. 17).** Q_C = 0: {np.abs(nc.circuit.i_line).min():.4f}–{np.abs(nc.circuit.i_line).max():.4f} A;
banco recomendado: {np.abs(sw.result.circuit.i_line).min():.4f}–{np.abs(sw.result.circuit.i_line).max():.4f} A; reducción frente al máximo
del Problema 1 ({np.abs(p1.i_line).max():,.2f} A): ×{np.abs(p1.i_line).max() / np.abs(sw.result.circuit.i_line).max():.1f}.

**(d) \\|V_gen(t)\\| con banda (Fig. 6, 9 y 16).** Banco recomendado: \\|V_gen\\| ∈ [{sw.result.v_gen_mag.min():.2f},
{sw.result.v_gen_mag.max():.2f}] V, 24/24 h en banda. Ningún Q_C fijo sirve: la hora {f.critical_pair[0] if f.critical_pair else "-"} y la hora
{f.critical_pair[1] if f.critical_pair else "-"} exigen conjuntos disjuntos de Q_C (§4).

**(e) P_loss(t) (Fig. 7).** Banco recomendado: **{sw.result.circuit.daily_energy_loss_kwh:,.4f} kWh/día**
({sw.result.circuit.p_loss_line_kw.sum():,.4f} kWh en R_line = 47.87 %, {sw.result.circuit.p_loss_gen_kw.sum():,.4f} kWh en R_gen = 52.13 %),
costo anual **{format_cop(se.annual_loss_cost_cop)}** (Q_C = 0: {nc.economics.daily_loss_kwh:,.4f} kWh/día → {format_cop(nc.economics.annual_loss_cost_cop)}/año).

## 4. Diagnóstico exacto de factibilidad (banco fijo)

\\|V_gen(t,Q_C)\\|² = a·Q_C² + b(t)·Q_C + c(t) es una parábola convexa ⇒ cada hora admite 1 o 2 intervalos
cerrados (rama inductiva y rama sobrecompensada). Solución analítica verificada numéricamente
(malla de 40 001 puntos + `brentq`): desviación máxima **{f.max_numeric_deviation_kvar:.2e} kvar**.

{_md_table(feas_rows)}

- **Intersección global 24 h: {format_set(f.global_set)} → {"FACTIBLE" if f.is_feasible else "INFACTIBLE"}.**
- Pares de horas en conflicto: {", ".join(str(p) for p in f.conflicting_pairs)} (par crítico {f.critical_pair}).
{_critical_pair_text(b)}

## 5. Comparativa de estrategias

{_md_table(pd.DataFrame(cmp_rows))}

### 5.1 Óptimo económico fijo
- Q_C* (forma cerrada) = **{e.q_c_closed_form_kvar:.6f} kvar** · `minimize_scalar` = {e.q_c_numeric_kvar:.6f} kvar · dJ/dQ_C = {e.derivative_at_optimum:.2e}
- Fórmula: Q_C* = mean(Q) − c_cap / (2·c_e·κ·24), con κ = R_eq·1000/13 200² = {b.params.r_eq_line_side * 1000 / 13200**2:.6e} kW/kVA².
- CAPEX **{format_cop(ee.capex_cop)}** · OPEX **{format_cop(ee.annual_loss_cost_cop)}** · Ahorro **{format_cop(ee.annual_savings_cop)}**/año
- Payback **{ee.payback_months:.3f} meses = {ee.payback_days:.2f} días** · ROI 1/3/5 años = {" / ".join(format_number(v, 1) + " %" for v in ee.roi_table.values())}
- ⚠ Viola la banda de tensión en **{e.result.hours_out_of_band} h** (máx {e.result.max_violation_v:.1f} V).

### 5.2 Compromiso de Pareto (banco fijo)
- Q_C minimax = **{par.minimax.q_c_installed_kvar:.4f} kvar** → violación máx **{par.minimax.max_violation_v:.3f} V**, RMS {par.minimax.rms_violation_v:.3f} V, {par.minimax.hours_out_of_band} h fuera de banda.
- Costo anual {format_cop(par.minimax.economics.total_annual_cost_cop)} (≈ {par.minimax.economics.total_annual_cost_cop / ee.total_annual_cost_cop:.1f}× el óptimo económico): la sobrecompensación multiplica las pérdidas.
- {len(par.front)} puntos no dominados en la frontera de Pareto.

### 5.3 Banco automático por pasos (innovación — 100 % factible)
- Instalado: **{sw.n_steps} × {sw.step_kvar:g} kvar = {sw.q_c_max_kvar:g} kvar** (cota inferior técnica {sw.q_c_max_lower_bound_kvar:.3f} kvar, impuesta por la hora 12).
- CAPEX **{format_cop(se.capex_cop)}** · Ahorro **{format_cop(se.annual_savings_cop)}**/año · Payback **{se.payback_days:.1f} días** · ROI 5 años {format_number(se.roi_pct(5), 1)} %.
- \\|V_gen\\| ∈ [{sw.result.v_gen_mag.min():.2f}, {sw.result.v_gen_mag.max():.2f}] V → **24/24 h dentro de banda**.
- Referencia ideal de control continuo: Q_C,max = {sw.continuous_reference.q_c_installed_kvar:.3f} kvar, J = {format_cop(sw.continuous_reference.economics.total_annual_cost_cop)}.

{_md_table(sched)}

### 5.4 Requisito operativo: factor de potencia neto siempre en atraso (Q_net(t) = Q(t) − Q_C(t) ≥ 0)

**Banco Fijo — 100 % en Atraso.** min J(Q_C) s.a. 0 ≤ Q_C ≤ min_t Q(t) = **{fl.q_c_upper_bound_kvar:.4f} kvar**
(limitado por la hora {fl.binding_hour}). El óptimo libre ({fl.q_c_unconstrained_kvar:.4f} kvar) queda fuera ⇒ la
restricción es activa y, por convexidad de J, **Q_C* = {fl.q_c_closed_form_kvar:.4f} kvar** (verificación
`minimize_scalar` acotado: {fl.q_c_numeric_kvar:.6f} kvar).
- CAPEX {format_cop(fl.result.economics.capex_cop)} · Ahorro {format_cop(fl.result.economics.annual_savings_cop)}/año ·
  Payback {fl.result.economics.payback_days:.2f} días · ROI 1/3/5 años = {" / ".join(format_number(v, 1) + " %" for v in fl.result.economics.roi_table.values())}
- fp neto ∈ [{fl.result.pf_net.min():.4f}, {fl.result.pf_net.max():.4f}] → **{fl.result.pf_status}** ·
  \\|V_gen\\| ∈ [{fl.result.v_gen_mag.min():.2f}, {fl.result.v_gen_mag.max():.2f}] V → {fl.result.hours_out_of_band} h fuera de banda.

**Banco Automático por Pasos — 100 % en Atraso.** Para n pasos de {sl.step_kvar:g} kvar el despacho óptimo de cada
hora es el mayor múltiplo del paso que no excede Q(t) (pérdidas κ·(Q − Q_C)² decrecientes hacia Q); se barre n.
- Instalado **{sl.n_steps} × {sl.step_kvar:g} kvar = {sl.q_c_max_kvar:g} kvar** · J = {format_cop(sl.result.economics.total_annual_cost_cop)} ·
  Ahorro {format_cop(sl.result.economics.annual_savings_cop)}/año · Payback {sl.result.economics.payback_days:.2f} días ·
  ROI 1/3/5 años = {" / ".join(format_number(v, 1) + " %" for v in sl.result.economics.roi_table.values())}
- fp neto ∈ [{sl.result.pf_net.min():.4f}, {sl.result.pf_net.max():.4f}] → **{sl.result.pf_status}** ·
  \\|V_gen\\| ∈ [{sl.result.v_gen_mag.min():.2f}, {sl.result.v_gen_mag.max():.2f}] V → {sl.result.hours_out_of_band} h fuera de banda.

{_md_table(sl_sched)}

**Teorema.** \\|V_gen(t, Q_C)\\|² = a·Q_C² + b(t)·Q_C + c(t) es
convexa; su mínimo en el intervalo de atraso [0, Q(t)] se alcanza en Q_C = Q(t) en las 24 h (Q_net = 0, fp_neto = 1.0).
El peor caso es la **hora {lag.worst_hour}: \\|V_gen\\| = {lag.max_floor_v:,.2f} V > 1 100 V**. Con X_line = 900 Ω la
corriente en fase (o en atraso) produce una caída jI·X/n₁ que suma en cuadratura con V₀·a₂/n₁ = 1 000 V y, con la
caída resistiva, eleva la tensión del generador por encima de la banda: solo **{lag.hours_band_reachable_lagging}/24 h**
admiten la banda sin sobrecompensar. Cumplir [950, 1100] V las 24 h exige Q_net < 0 (adelanto) en las horas pico, p. ej.
en la hora {lag.worst_hour} se necesita Q_C ≥ {lag.q_c_band_min_kvar[h12]:.3f} kvar ⇒ Q_net = {lag.q_net_required_kvar[h12]:.3f} kvar.

| Diseño | Q_C inst. [kvar] | J anual | Payback [días] | V_gen máx [V] | Horas fuera | fp_neto mín–máx | Estado fp (24 h) |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(f"| {r.label} | {r.q_c_installed_kvar:.3f} | {format_cop(r.economics.total_annual_cost_cop)} | {format_number(r.economics.payback_days, 1)} | {r.v_gen_mag.max():.2f} | {r.hours_out_of_band} | {r.pf_net.min():.3f}–{r.pf_net.max():.3f} | {r.pf_status} |" for r in (fl.result, sl.result, sw.result))}

- **Diseños 100 % en atraso:** sin sobrecompensación capacitiva, más baratos (el banco por pasos en atraso tiene el
  menor J de todas las estrategias), pero violan la banda de tensión en horas pico.
- **Diseño de regulación estricta [950, 1100] V:** cumple 24/24 h, pero opera con fp neto en adelanto
  ({sw.result.pf_status}).

{_md_table(lag_rows)}

## 6. Desarrollo Matemático Paso a Paso — Fase 2 (Problema 2)

Cadena de cálculo de la Fase 2 (T1, línea, T2 y banco Q_C) contrastada con la Fase 1 (red directa). Relaciones:
I_line = I_load / a₂, I_gen = n₁·I_line, V_line,recv = 120·110 = 13 200∠0° V, V_T1,prim = V_line,envío / n₁ y
R_eq referida al lado de 13.2 kV = 80 + 0.5·13.2² = **{b.params.r_eq_line_side:.2f} Ω**. La conservación de potencia
compleja se verifica de forma independiente (V_gen·I_gen* frente a S_neto + S_loss,line + S_loss,gen).
La tabla horaria completa de las 24 h está en `fase2_paso_a_paso_24h_qc0.csv`,
`fase2_paso_a_paso_24h_banco_atraso.csv`, `fase2_paso_a_paso_24h_banco_pasos.csv` y `fase1_paso_a_paso_24h.csv`.

### 6.1 Hora 1 (contraste con el cálculo manual de la Fase 1)

{_step_by_step_hour(b, 1)}

### 6.2 Hora 12 (hora pico)

{_step_by_step_hour(b, 12)}

## 7. Sensibilidad (X_line)

{sens_txt}

## 8. Gráficas y comentarios técnicos

{charts_md}

## 9. Guion de exposición (10 minutos)

| Tiempo | Bloque | Mensaje clave | Apoyo |
|---|---|---|---|
| 0:00–1:00 | Contexto | Red de 24 h con carga residencial + industrial, 80 + j900 Ω de línea y restricción de tensión en el generador. | Fig. 4 |
| 1:00–2:30 | Problema 1 | Golden test hora 1: {abs(p1.i_line[0]):.2f} A, {p1.p_loss_kw[0]:,.0f} kW de pérdidas para servir 70 kW. Pérdidas ×{p1.daily_energy_loss_kwh / p1.daily_energy_served_kwh:,.0f} la energía útil. | Fig. 1–3 |
| 2:30–3:30 | Transformadores | Elevar a 13.2 kV divide I por 110 y las pérdidas por 12 100. R_gen referida = 87.12 Ω ⇒ R_eq = 167.12 Ω. | Fig. 5, 7 |
| 3:30–4:30 | Problema de tensión | Sin capacitor \\|V_gen\\| llega a {nc.v_gen_mag.max():,.0f} V: la caída jI·X en 900 Ω eleva la tensión de envío. | Fig. 6, 12 |
| 4:30–6:00 | Factibilidad | Análisis cuadrático exacto: ventanas horarias disjuntas (par {f.critical_pair}) ⇒ ningún banco fijo cumple. | Fig. 9 |
| 6:00–7:00 | Óptimo económico | Q_C* = {e.q_c_closed_form_kvar:.2f} kvar, payback {ee.payback_days:.0f} días, pero {e.result.hours_out_of_band} h fuera de banda. | Fig. 8 |
| 7:00–7:45 | Pareto | Minimizar violación con banco fijo cuesta {par.minimax.economics.total_annual_cost_cop / ee.total_annual_cost_cop:.1f}× más y aún viola {par.minimax.max_violation_v:.1f} V. | Fig. 10 |
| 7:45–8:30 | fp en atraso | Con Q_net ≥ 0 la mínima \\|V_gen\\| en la hora {lag.worst_hour} es {lag.max_floor_v:,.2f} V > 1100 V: el banco por pasos en atraso ({sl.n_steps}×{sl.step_kvar:g} kvar) es el más barato pero no regula; regular exige adelanto. | Fig. 16 |
| 8:30–9:15 | Propuesta | Banco automático {sw.n_steps}×{sw.step_kvar:g} kvar: 24/24 h en banda, ahorro {format_cop(se.annual_savings_cop)}/año, payback {se.payback_days:.0f} días. | Fig. 11, 13, 15 |
| 9:15–10:00 | Cierre | Sensibilidad: con X ≤ {sens.x_critical_upper if sens and sens.x_critical_upper else float("nan"):.1f} Ω un banco fijo bastaría. Recomendación: banco automático + dashboard docente. | Fig. 14, demo |
"""


def export_markdown(b: AnalysisBundle, charts: list[tuple[ChartSpec, Path]], out_path: Path) -> Path:
    out_path.write_text(build_markdown_report(b, charts), encoding="utf-8")
    return out_path


def export_all(b: AnalysisBundle, out_dir: Path) -> dict[str, list[Path]]:
    charts = export_charts(b, out_dir)
    tables = export_tables(b, out_dir)
    md = export_markdown(b, charts, out_dir / "resumen_sustentacion.md")
    return {"charts": [p for _, p in charts], "tables": tables, "report": [md]}


__all__ = ["DPI", "Strategy", "chart_catalog", "export_all", "export_charts", "export_markdown", "export_tables"]
