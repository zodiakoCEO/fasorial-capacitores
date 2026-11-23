"""Constructores de figuras Plotly (puros: reciben resultados, devuelven ``go.Figure``).

Usados por el dashboard Streamlit. Sin dependencias de UI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from src.domain.models import CircuitResult, DemandProfile, NetworkParameters, Strategy
from src.optimization.capacitor_optimizer import FeasibilityReport, StrategyResult
from src.optimization.economics import EconomicSummary, cumulative_cash_flow
from src.reporting import theme as T

HOURS_AXIS = {"title": "Hora del día t", "tickmode": "linear", "dtick": 2, "range": [0.5, 24.5]}


# ==================================================================================
# Utilidades
# ==================================================================================
def _base(fig: go.Figure, title: str, y_title: str, height: int = 360, **layout: object) -> go.Figure:
    defaults: dict[str, object] = {
        "title": {"text": title, "x": 0, "xanchor": "left", "y": 0.98, "yanchor": "top", "font": {"size": 15}},
        "font": {"family": T.FONT_FAMILY, "size": 12},
        "height": height,
        "margin": {"l": 60, "r": 20, "t": 84, "b": 48},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "hovermode": "x unified",
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0},
    }
    fig.update_layout(**{**defaults, **layout})
    fig.update_xaxes(showgrid=False, linecolor=T.AXIS, zeroline=False, ticks="outside", tickcolor=T.AXIS)
    fig.update_yaxes(title=y_title, gridcolor=T.GRID, zeroline=False, linecolor=T.AXIS)
    return fig


def _line(
    x: Sequence[float],
    y: Sequence[float],
    name: str,
    color: str,
    dash: str = "solid",
    unit: str = "",
    fmt: str = ",.2f",
    **kw: object,
) -> go.Scatter:
    return go.Scatter(
        x=x,
        y=y,
        name=name,
        mode="lines+markers",
        line={"color": color, "width": 2, "dash": dash, "shape": "linear"},
        marker={"size": 6, "color": color, "line": {"width": 1.5, "color": T.SURFACE}},
        hovertemplate=f"%{{y:{fmt}}} {unit}<extra>{name}</extra>",
        **kw,
    )


def strategy_style(strategy: Strategy) -> tuple[str, str]:
    return T.STRATEGY_COLOR[strategy], T.STRATEGY_DASH[strategy]


# ==================================================================================
# Problema 1
# ==================================================================================
def fig_hourly_metric(
    hours: Sequence[int],
    series: Mapping[str, tuple[Sequence[float], str, str]],
    title: str,
    y_title: str,
    unit: str,
    fmt: str = ",.2f",
    log_y: bool = False,
    height: int = 340,
) -> go.Figure:
    """Gráfica horaria genérica. ``series``: nombre → (valores, color, dash)."""
    fig = go.Figure()
    for name, (vals, color, dash) in series.items():
        fig.add_trace(_line(hours, vals, name, color, dash, unit, fmt))
    _base(fig, title, y_title, height=height, xaxis=HOURS_AXIS, showlegend=len(series) > 1)
    if log_y:
        fig.update_yaxes(type="log")
    return fig


def fig_load_breakdown(demand: DemandProfile) -> go.Figure:
    """Desglose residencial vs. industrial: P (barras apiladas) y Q (barras apiladas)."""
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=1, cols=2, subplot_titles=("Potencia activa P [kW]", "Potencia reactiva Q [kvar]"), horizontal_spacing=0.1
    )
    for (name, color), p, q in zip(
        T.LOAD_COLOR.items(), (demand.p1_kw, demand.p2_kw), (demand.q1_kvar, demand.q2_kvar), strict=True
    ):
        fig.add_trace(
            go.Bar(
                x=demand.hours,
                y=p,
                name=name,
                marker={"color": color, "line": {"width": 1, "color": T.SURFACE}},
                hovertemplate="%{y:.1f} kW<extra>" + name + "</extra>",
                legendgroup=name,
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Bar(
                x=demand.hours,
                y=q,
                name=name,
                marker={"color": color, "line": {"width": 1, "color": T.SURFACE}},
                hovertemplate="%{y:.1f} kvar<extra>" + name + "</extra>",
                legendgroup=name,
                showlegend=False,
            ),
            row=1,
            col=2,
        )
    _base(fig, "Perfil de demanda — desglose por carga", "", height=340, barmode="stack", bargap=0.18)
    fig.update_xaxes(tickmode="linear", dtick=2, title="Hora t")
    return fig


def fig_p1_vs_p2_current(p1: CircuitResult, p2: CircuitResult) -> go.Figure:
    fig = fig_hourly_metric(
        p1.hours,
        {
            "Problema 1 — 120 V directo": (np.abs(p1.i_line), T.SERIES[0], "solid"),
            "Problema 2 — línea 13.2 kV": (np.abs(p2.i_line), T.SERIES[1], "solid"),
        },
        "Corriente de línea |I_line(t)| — escala logarítmica",
        "|I_line| [A]",
        "A",
        log_y=True,
    )
    return fig


# ==================================================================================
# Problema 2
# ==================================================================================
def fig_vgen_band(results: Sequence[StrategyResult], params: NetworkParameters, height: int = 400) -> go.Figure:
    """|V_gen(t)| con banda verde [950, 1100] V y marcadores de alerta fuera de rango."""
    fig = go.Figure()
    hours = results[0].circuit.hours
    fig.add_hrect(
        y0=params.v_gen_min,
        y1=params.v_gen_max,
        fillcolor=T.BAND_FILL,
        line_width=0,
        annotation_text=f"✓ Banda admisible [{params.v_gen_min:g}, {params.v_gen_max:g}] V",
        annotation_position="bottom right",
        annotation_font={"color": T.GOOD, "size": 11},
    )
    for lim in (params.v_gen_min, params.v_gen_max):
        fig.add_hline(y=lim, line={"color": T.GOOD, "width": 1, "dash": "dot"})
    for r in results:
        color, dash = strategy_style(r.strategy)
        fig.add_trace(_line(hours, r.v_gen_mag, r.label, color, dash, "V", ",.1f"))
        out = r.violation_v > 1e-6
        if out.any():
            fig.add_trace(
                go.Scatter(
                    x=hours[out],
                    y=r.v_gen_mag[out],
                    mode="markers",
                    name=f"⚠ Fuera de banda — {r.label}",
                    marker={"symbol": "x-thin-open", "size": 11, "color": T.CRITICAL, "line": {"width": 2.5}},
                    customdata=r.violation_v[out],
                    showlegend=False,
                    hovertemplate="⚠ fuera de banda por %{customdata:.1f} V<extra></extra>",
                )
            )
    _base(fig, "Tensión del generador |V_gen(t)|", "|V_gen| [V]", height=height, xaxis=HOURS_AXIS)
    return fig


def fig_losses_stacked(circuit: CircuitResult, title: str = "Pérdidas activas P_loss(t) — desglose") -> go.Figure:
    fig = go.Figure()
    for (name, color), vals in zip(T.LOSS_COLOR.items(), (circuit.p_loss_line_kw, circuit.p_loss_gen_kw), strict=True):
        fig.add_trace(
            go.Bar(
                x=circuit.hours,
                y=vals,
                name=name,
                marker={"color": color, "line": {"width": 1, "color": T.SURFACE}},
                hovertemplate="%{y:,.3f} kW<extra>" + name + "</extra>",
            )
        )
    _base(fig, title, "P_loss [kW]", barmode="stack", bargap=0.18, xaxis=HOURS_AXIS)
    return fig


def fig_cost_curve(
    grid: pd.DataFrame, markers: Mapping[str, tuple[float, float, str]], q_max_view: float = 500.0
) -> go.Figure:
    """J(Q_C) del banco fijo con marcadores de las estrategias. markers: nombre → (q, J, color)."""
    g = grid[grid["Q_C_kvar"] <= q_max_view]
    fig = go.Figure(
        go.Scatter(
            x=g["Q_C_kvar"],
            y=g["Costo_total_anual_COP"] / 1e6,
            mode="lines",
            name="J(Q_C) = OPEX + CAPEX",
            line={"color": T.SERIES[0], "width": 2},
            hovertemplate="Q_C=%{x:.1f} kvar<br>J=%{y:,.2f} MCOP<extra></extra>",
        )
    )
    for name, (q, j, color) in markers.items():
        fig.add_trace(
            go.Scatter(
                x=[q],
                y=[j / 1e6],
                mode="markers+text",
                name=name,
                text=[name],
                textposition="top center",
                textfont={"size": 11},
                marker={"size": 11, "color": color, "line": {"width": 2, "color": T.SURFACE}},
                hovertemplate=f"{name}<br>Q_C=%{{x:.2f}} kvar<br>J=%{{y:,.2f}} MCOP<extra></extra>",
            )
        )
    _base(fig, "Costo total anual J(Q_C) — banco fijo", "J [millones COP/año]", hovermode="closest", showlegend=False)
    fig.update_xaxes(title="Q_C [kvar]")
    return fig


def fig_feasibility_map(
    feas: FeasibilityReport,
    overlays: Mapping[str, tuple[Sequence[float], str, str]] | None = None,
    q_view: float = 480.0,
) -> go.Figure:
    """Mapa de factibilidad horaria: intervalos [Q_min(t), Q_max(t)] por hora y rama."""
    fig = go.Figure()
    for branch, (label, color) in enumerate(
        (("Rama inductiva/baja", T.GOOD), ("Rama sobrecompensada/alta", "rgba(12,163,12,0.45)"))
    ):
        xs, base, height, cd = [], [], [], []
        for h, s in zip(feas.hours, feas.hourly_sets, strict=True):
            if len(s) > branch:
                iv = s[branch]
                xs.append(int(h))
                base.append(iv.lo)
                height.append(iv.width)
                cd.append([iv.lo, iv.hi])
        fig.add_trace(
            go.Bar(
                x=xs,
                y=height,
                base=base,
                name=f"Q_C factible — {label}",
                width=0.6,
                marker={"color": color, "line": {"width": 0}},
                customdata=cd,
                hovertemplate="[%{customdata[0]:.1f}, %{customdata[1]:.1f}] kvar<extra>" + label + "</extra>",
            )
        )
    for name, (vals, color, dash) in (overlays or {}).items():
        fig.add_trace(_line(feas.hours, vals, name, color, dash, "kvar", ".1f"))
    _base(
        fig,
        "Mapa de factibilidad horaria  950 ≤ |V_gen(t, Q_C)| ≤ 1100 V",
        "Q_C [kvar]",
        height=420,
        barmode="overlay",
        xaxis=HOURS_AXIS,
    )
    fig.update_yaxes(range=[0, q_view])
    return fig


def fig_pareto(
    grid: pd.DataFrame, front: pd.DataFrame, highlights: Mapping[str, tuple[float, float, str]]
) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=grid["Violacion_max_V"],
            y=grid["Costo_total_anual_COP"] / 1e6,
            mode="markers",
            name="Q_C evaluados",
            marker={"size": 4, "color": T.MUTED, "opacity": 0.35},
            customdata=grid["Q_C_kvar"],
            hovertemplate="Q_C=%{customdata:.1f} kvar<br>viol=%{x:.1f} V<br>J=%{y:,.1f} MCOP<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=front["Violacion_max_V"],
            y=front["Costo_total_anual_COP"] / 1e6,
            mode="lines",
            name="Frontera de Pareto",
            line={"color": T.SERIES[0], "width": 2},
            customdata=front["Q_C_kvar"],
            hovertemplate="Q_C=%{customdata:.1f} kvar<br>viol=%{x:.1f} V<br>J=%{y:,.1f} MCOP<extra>Pareto</extra>",
        )
    )
    for name, (viol, j, color) in highlights.items():
        fig.add_trace(
            go.Scatter(
                x=[viol],
                y=[j / 1e6],
                mode="markers+text",
                text=[name],
                name=name,
                textposition="middle right",
                marker={"size": 12, "color": color, "line": {"width": 2, "color": T.SURFACE}},
                hoverinfo="skip",
            )
        )
    _base(
        fig,
        "Frontera de Pareto — costo anual vs. violación máxima de tensión (banco fijo)",
        "J [millones COP/año]",
        height=420,
        hovermode="closest",
        showlegend=False,
    )
    fig.update_xaxes(title="Violación máxima de |V_gen| fuera de [950, 1100] V  [V]")
    return fig


# ==================================================================================
# Modo docente: triángulo de potencias y diagrama fasorial
# ==================================================================================
def fig_power_triangle(p_kw: float, q_l_kvar: float, q_c_kvar: float) -> go.Figure:
    q_net = q_l_kvar - q_c_kvar
    s_before = np.hypot(p_kw, q_l_kvar)
    s_after = np.hypot(p_kw, q_net)
    pf_b = p_kw / s_before if s_before else 1.0
    pf_a = p_kw / s_after if s_after else 1.0
    fig = go.Figure()

    def seg(
        x0: float, y0: float, x1: float, y1: float, name: str, color: str, dash: str = "solid", label: str = ""
    ) -> None:
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode="lines+markers",
                name=name,
                line={"color": color, "width": 3, "dash": dash},
                marker={"symbol": ["circle", "arrow"], "angleref": "previous", "size": [4, 14], "color": color},
                hovertemplate=label + "<extra></extra>",
            )
        )

    seg(0, 0, p_kw, 0, f"P = {p_kw:.2f} kW", T.SERIES[0], label=f"P = {p_kw:.2f} kW")
    seg(p_kw, 0, p_kw, q_l_kvar, f"Q_L = {q_l_kvar:.2f} kvar", T.SERIES[1], label=f"Q_L = {q_l_kvar:.2f} kvar")
    seg(
        0,
        0,
        p_kw,
        q_l_kvar,
        f"S antes = {s_before:.2f} kVA (fp {pf_b:.3f})",
        T.MUTED,
        "dash",
        label=f"S antes = {s_before:.2f} kVA, fp = {pf_b:.3f}",
    )
    if q_c_kvar:
        seg(
            p_kw + p_kw * 0.04,
            q_l_kvar,
            p_kw + p_kw * 0.04,
            q_net,
            f"−Q_C = −{q_c_kvar:.2f} kvar",
            T.SERIES[2],
            label=f"−Q_C = −{q_c_kvar:.2f} kvar",
        )
    seg(
        0,
        0,
        p_kw,
        q_net,
        f"S después = {s_after:.2f} kVA (fp {pf_a:.3f} {'ad' if q_net < 0 else 'at'}.)",
        T.SERIES[6],
        label=f"S después = {s_after:.2f} kVA, Q_net = {q_net:.2f} kvar",
    )
    lim = max(abs(q_l_kvar), abs(q_net), p_kw) * 1.15
    _base(
        fig,
        "Triángulo de potencias (antes y después del banco)",
        "Q [kvar]",
        height=420,
        hovermode="closest",
        legend={"orientation": "v", "x": 1.02, "y": 1, "xanchor": "left"},
    )
    fig.update_xaxes(title="P [kW]", range=[-0.05 * lim, lim * 1.1], zeroline=True, zerolinecolor=T.AXIS)
    fig.update_yaxes(
        range=[min(0, q_net) - 0.1 * lim, lim], zeroline=True, zerolinecolor=T.AXIS, scaleanchor="x", scaleratio=1
    )
    return fig


def phasor_components(
    circuit: CircuitResult, params: NetworkParameters, t_index: int, demand: DemandProfile
) -> dict[str, complex]:
    """Fasores referidos al lado del generador (1 kV) para la hora ``t_index`` (0-based)."""
    n1 = params.n1
    v_ref = circuit.v_line_receiving[t_index] / n1  # V_0 referida = 1000∠0°
    drop = circuit.i_line[t_index] * params.z_eq_line_side / n1  # caída I·Z_eq referida
    i_gen = circuit.i_gen[t_index]
    s_load = demand.s_total_kva[t_index]
    i_load_no_cap = np.conj(s_load * 1000 / params.v_load) / params.a2 * n1  # I sin capacitor, referida
    return {
        "V0_ref": v_ref,
        "drop": drop,
        "V_gen": circuit.v_gen[t_index],
        "I_gen": i_gen,
        "I_load_sin_QC": i_load_no_cap,
        "drop_R": circuit.i_line[t_index] * params.r_eq_line_side / n1,
        "drop_X": circuit.i_line[t_index] * 1j * params.x_line / n1,
    }


def nice_current_scale(i_max_a: float, target_v: float = 550.0) -> float:
    """Escala V/A 'redonda' (1-2-5·10^k) para que la corriente máxima mida ≈ target_v en el diagrama."""
    if i_max_a <= 0:
        return 1.0
    raw = target_v / i_max_a
    exp = np.floor(np.log10(raw))
    mant = raw / 10**exp
    nice = 1.0 if mant < 2 else 2.0 if mant < 5 else 5.0
    return float(nice * 10**exp)


def _phasor_traces(ph: Mapping[str, complex], i_scale: float) -> list[go.Scatter]:
    def arrow(
        z0: complex, z1: complex, name: str, color: str, dash: str = "solid", width: float = 3, hover: str = ""
    ) -> go.Scatter:
        return go.Scatter(
            x=[z0.real, z1.real],
            y=[z0.imag, z1.imag],
            mode="lines+markers",
            name=name,
            line={"color": color, "width": width, "dash": dash},
            marker={"symbol": ["circle", "arrow"], "angleref": "previous", "size": [3, 15], "color": color},
            hovertemplate=hover + "<extra></extra>",
        )

    def polar(z: complex, unit: str) -> str:
        return f"{abs(z):,.2f} {unit} ∠ {np.degrees(np.angle(z)):.2f}°"

    v_ref, drop, v_gen = ph["V0_ref"], ph["drop"], ph["V_gen"]
    tip_r = v_ref + ph["drop_R"]
    return [
        arrow(0, v_ref, "V₀ referida (1000∠0° V)", T.SERIES[0], hover=f"V₀·a₂/n₁ = {polar(v_ref, 'V')}"),
        arrow(
            v_ref,
            tip_r,
            "Caída resistiva I·R_eq/n₁",
            T.SERIES[1],
            "dot",
            2,
            hover=f"I·R_eq/n₁ = {polar(ph['drop_R'], 'V')}",
        ),
        arrow(
            tip_r,
            v_ref + drop,
            "Caída reactiva jI·X/n₁",
            T.SERIES[4],
            "dot",
            2,
            hover=f"jI·X/n₁ = {polar(ph['drop_X'], 'V')}",
        ),
        arrow(
            v_ref, v_ref + drop, "Caída total I·Z_eq/n₁", T.MUTED, "dash", 2, hover=f"I·Z_eq/n₁ = {polar(drop, 'V')}"
        ),
        arrow(0, v_gen, "V_gen", T.SERIES[2], hover=f"V_gen = {polar(v_gen, 'V')}"),
        arrow(
            0,
            ph["I_load_sin_QC"] * i_scale,
            f"I sin Q_C (×{i_scale:g} V/A)",
            T.MUTED,
            "dot",
            2,
            hover=f"I_gen sin capacitor = {polar(ph['I_load_sin_QC'], 'A')}",
        ),
        arrow(
            0,
            ph["I_gen"] * i_scale,
            f"I_gen con Q_C (×{i_scale:g} V/A)",
            T.SERIES[6],
            "solid",
            2.5,
            hover=f"I_gen = {polar(ph['I_gen'], 'A')}",
        ),
    ]


def _phasor_layout(fig: go.Figure, params: NetworkParameters, title: str, lim: float) -> None:
    theta = np.linspace(0, np.pi, 200)
    for r, txt in ((params.v_gen_min, f"{params.v_gen_min:g} V"), (params.v_gen_max, f"{params.v_gen_max:g} V")):
        fig.add_trace(
            go.Scatter(
                x=r * np.cos(theta),
                y=r * np.sin(theta),
                mode="lines",
                name=f"|V| = {txt}",
                line={"color": T.GOOD, "width": 1, "dash": "dot"},
                hoverinfo="skip",
                showlegend=False,
            )
        )
    _base(
        fig,
        title,
        "Im [V]",
        height=520,
        hovermode="closest",
        legend={"orientation": "v", "x": 1.02, "y": 1, "xanchor": "left"},
    )
    fig.update_xaxes(title="Re [V]", range=[-0.45 * lim, 1.05 * lim], zeroline=True, zerolinecolor=T.AXIS)
    fig.update_yaxes(range=[-0.45 * lim, 0.9 * lim], zeroline=True, zerolinecolor=T.AXIS, scaleanchor="x", scaleratio=1)


def fig_phasor_diagram(
    circuit: CircuitResult, params: NetworkParameters, demand: DemandProfile, t_index: int, i_scale: float | None = None
) -> go.Figure:
    ph = phasor_components(circuit, params, t_index, demand)
    if i_scale is None:
        i_scale = nice_current_scale(max(abs(ph["I_gen"]), abs(ph["I_load_sin_QC"])))
    fig = go.Figure(_phasor_traces(ph, i_scale))
    lim = max(abs(ph["V_gen"]), abs(ph["V0_ref"] + ph["drop"]), params.v_gen_max) * 1.08
    _phasor_layout(fig, params, f"Diagrama fasorial referido al generador — hora {t_index + 1}", lim)
    return fig


def fig_phasor_animation(
    circuits_by_hour: CircuitResult, params: NetworkParameters, demand: DemandProfile, i_scale: float | None = None
) -> go.Figure:
    """Diagrama fasorial animado de 24 horas (botones ▶ / ⏸ y deslizador)."""
    n = demand.n_hours
    all_ph = [phasor_components(circuits_by_hour, params, t, demand) for t in range(n)]
    if i_scale is None:
        i_scale = nice_current_scale(max(max(abs(p["I_gen"]), abs(p["I_load_sin_QC"])) for p in all_ph))
    lim = max(max(abs(p["V_gen"]), abs(p["V0_ref"] + p["drop"])) for p in all_ph)
    lim = max(lim, params.v_gen_max) * 1.08
    fig = go.Figure(_phasor_traces(all_ph[0], i_scale))
    n_dyn = len(fig.data)
    _phasor_layout(fig, params, "Diagrama fasorial animado (24 h) — referido al generador", lim)
    fig.frames = [
        go.Frame(
            data=_phasor_traces(all_ph[t], i_scale),
            traces=list(range(n_dyn)),
            name=str(t + 1),
            layout={
                "title": {"text": f"Diagrama fasorial — hora {t + 1}  |  |V_gen| = {abs(all_ph[t]['V_gen']):,.1f} V"}
            },
        )
        for t in range(n)
    ]
    fig.update_layout(
        updatemenus=[
            {
                "type": "buttons",
                "direction": "left",
                "x": 0,
                "y": -0.12,
                "xanchor": "left",
                "buttons": [
                    {
                        "label": "▶ Play",
                        "method": "animate",
                        "args": [
                            None,
                            {
                                "frame": {"duration": 600, "redraw": True},
                                "fromcurrent": True,
                                "transition": {"duration": 250},
                            },
                        ],
                    },
                    {
                        "label": "⏸ Pausa",
                        "method": "animate",
                        "args": [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}],
                    },
                ],
            }
        ],
        sliders=[
            {
                "x": 0.18,
                "y": -0.08,
                "len": 0.8,
                "currentvalue": {"prefix": "Hora: "},
                "steps": [
                    {
                        "label": str(t + 1),
                        "method": "animate",
                        "args": [[str(t + 1)], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}],
                    }
                    for t in range(n)
                ],
            }
        ],
        margin={"b": 110},
    )
    return fig


# ==================================================================================
# Economía
# ==================================================================================
def fig_cash_flow(
    summaries: Mapping[str, tuple[EconomicSummary, str]], horizon_years: float, budget_cop: float | None = None
) -> go.Figure:
    fig = go.Figure()
    for name, (summ, color) in summaries.items():
        cf = cumulative_cash_flow(summ, horizon_years, points_per_year=24)
        fig.add_trace(
            go.Scatter(
                x=cf["mes"],
                y=cf["flujo_acumulado_COP"] / 1e6,
                mode="lines",
                name=name,
                line={"color": color, "width": 2},
                hovertemplate="%{y:,.2f} MCOP<extra>" + name + "</extra>",
            )
        )
        if 0 < summ.payback_months <= horizon_years * 12:
            fig.add_trace(
                go.Scatter(
                    x=[summ.payback_months],
                    y=[0],
                    mode="markers+text",
                    showlegend=False,
                    text=[f"Break-even {summ.payback_days:,.0f} d"],
                    textposition="top center",
                    marker={"size": 10, "color": color, "symbol": "diamond", "line": {"width": 2, "color": T.SURFACE}},
                    hoverinfo="skip",
                )
            )
    fig.add_hline(y=0, line={"color": T.AXIS, "width": 1})
    if budget_cop is not None:
        fig.add_hline(
            y=-budget_cop / 1e6,
            line={"color": T.WARNING, "width": 1.5, "dash": "dash"},
            annotation_text="− Presupuesto disponible",
            annotation_position="bottom right",
        )
    _base(fig, "Flujo de caja acumulado (sin descuento)", "Flujo acumulado [millones COP]", height=400)
    fig.update_xaxes(title="Meses desde la inversión")
    return fig


def fig_reactance_scan(scan: pd.DataFrame, x_current: float, x_critical: float | None) -> go.Figure:
    fig = go.Figure(
        go.Scatter(
            x=scan["X_line_ohm"],
            y=scan["ancho_ventana_kvar"],
            mode="lines",
            name="Ancho de la ventana factible común",
            line={"color": T.SERIES[0], "width": 2},
            fill="tozeroy",
            fillcolor="rgba(42,120,214,0.12)",
            hovertemplate="X=%{x:.0f} Ω<br>ancho=%{y:.2f} kvar<extra></extra>",
        )
    )
    fig.add_vline(
        x=x_current,
        line={"color": T.CRITICAL, "dash": "dash"},
        annotation_text=f"X actual = {x_current:g} Ω",
        annotation_position="top",
    )
    if x_critical is not None:
        fig.add_vline(
            x=x_critical,
            line={"color": T.GOOD, "dash": "dot"},
            annotation_text=f"X crítica = {x_critical:.2f} Ω",
            annotation_position="top left",
        )
    _base(
        fig,
        "¿Para qué X_line existe un banco FIJO factible las 24 h?",
        "Ancho ∩ₜ ventanas Q_C [kvar]",
        hovermode="closest",
        showlegend=False,
    )
    fig.update_xaxes(title="Reactancia de línea X_line [Ω]")
    return fig


# ==================================================================================
# Diagrama de circuito (SVG)
# ==================================================================================
# Paleta del diagrama unifilar: tarjeta oscura propia, visible en ambos modos de la app.
_SVG_CARD = "#181A1F"
_SVG_BORDER = "#2A2E36"
_SVG_WIRE = "#E2E8F0"
_SVG_MUTED = "#94A3B8"
_SVG_VALUE = "#F1F5F9"
_SVG_ACCENT = "#60A5FA"  # flujo de corriente
_SVG_OK = "#4ADE80"
_SVG_BAD = "#F87171"


_SVG_CYAN = "#38BDF8"  # banco de capacitores
_SVG_WARN = "#FBBF24"  # fp en adelanto (sobrecompensado)

_SVG_W, _SVG_H = 1080, 440
_LBL, _VAL, _SMALL = 15, 17, 13  # tamaños de texto (unidades del viewBox) legibles a ancho completo
_STROKE = 'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"'


def _sub(base: str, sub: str) -> str:
    """Texto con subíndice SVG (sin guiones bajos literales)."""
    return f'{base}<tspan baseline-shift="sub" font-size="11">{sub}</tspan>'


def _svg_text(
    x: float,
    y: float,
    body: str,
    *,
    color: str = _SVG_MUTED,
    size: int = _LBL,
    weight: int = 400,
    anchor: str = "middle",
) -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}" '
        f"text-anchor=\"{anchor}\" font-family='{T.FONT_MONO}'>{body}</text>"
    )


def _value(x: float, y: float, body: str, *, color: str = _SVG_VALUE, anchor: str = "middle") -> str:
    return _svg_text(x, y, body, color=color, size=_VAL, weight=600, anchor=anchor)


def _small(x: float, y: float, body: str, *, color: str = _SVG_MUTED, anchor: str = "middle", weight: int = 400) -> str:
    return _svg_text(x, y, body, color=color, size=_SMALL, weight=weight, anchor=anchor)


def _wire(x1: float, y1: float, x2: float, y2: float, color: str = _SVG_WIRE, width: float = 1.8) -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" '
        'stroke-linecap="round"/>'
    )


def _path(d: str, color: str = _SVG_WIRE) -> str:
    return f'<path d="{d}" stroke="{color}" {_STROKE}/>'


def _flow_arrow(x1: float, x2: float, y: float) -> str:
    """Flecha de sentido de corriente (acento sutil)."""
    return (
        _wire(x1, y, x2 - 9, y, _SVG_ACCENT, 1.6)
        + f'<path d="M{x2 - 10},{y - 5} L{x2},{y} L{x2 - 10},{y + 5} Z" fill="{_SVG_ACCENT}"/>'
    )


# -- Símbolos IEEE/IEC ---------------------------------------------------------------
def _ground(x: float, y: float, color: str = _SVG_WIRE) -> str:
    """Tierra (tres trazos decrecientes) con el borne superior en (x, y)."""
    return (
        _wire(x - 13, y, x + 13, y, color)
        + _wire(x - 8, y + 5, x + 8, y + 5, color)
        + _wire(x - 3, y + 10, x + 3, y + 10, color)
    )


def _resistor_h(x0: float, x1: float, y: float, n: int = 6, amp: float = 8) -> str:
    """Resistencia en zigzag horizontal entre x0 y x1."""
    lead = 8
    seg = (x1 - x0 - 2 * lead) / n
    xs = x0 + lead
    pts = [f"M{x0},{y}", f"L{xs},{y}"]
    for k in range(n):
        pts += [f"L{xs + seg * (k + 0.25):.1f},{y - amp}", f"L{xs + seg * (k + 0.75):.1f},{y + amp}"]
    pts += [f"L{xs + seg * n:.1f},{y}", f"L{x1},{y}"]
    return _path(" ".join(pts))


def _resistor_v(x: float, y0: float, y1: float, n: int = 5, amp: float = 7) -> str:
    lead = 6
    seg = (y1 - y0 - 2 * lead) / n
    ys = y0 + lead
    pts = [f"M{x},{y0}", f"L{x},{ys}"]
    for k in range(n):
        pts += [f"L{x + amp},{ys + seg * (k + 0.25):.1f}", f"L{x - amp},{ys + seg * (k + 0.75):.1f}"]
    pts += [f"L{x},{ys + seg * n:.1f}", f"L{x},{y1}"]
    return _path(" ".join(pts))


def _inductor_h(x0: float, x1: float, y: float, n: int = 4) -> str:
    """Bobina (espiras semicirculares) horizontal."""
    lead = 6
    r = (x1 - x0 - 2 * lead) / (2 * n)
    arcs = " ".join(f"a{r:.2f},{r:.2f} 0 0 1 {2 * r:.2f},0" for _ in range(n))
    return _path(f"M{x0},{y} L{x0 + lead},{y} {arcs} L{x1},{y}")


def _coil_v(x: float, y0: float, y1: float, n: int = 4, bulge_right: bool = True) -> str:
    """Devanado vertical; ``bulge_right`` orienta las espiras hacia el núcleo."""
    r = (y1 - y0) / (2 * n)
    sweep = 1 if bulge_right else 0
    arcs = " ".join(f"a{r:.2f},{r:.2f} 0 0 {sweep} 0,{2 * r:.2f}" for _ in range(n))
    return _path(f"M{x},{y0} {arcs}")


def _ac_source(cx: float, cy: float, r: float = 24) -> str:
    sine = f"M{cx - 13},{cy} q6.5,-13 13,0 t13,0"
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{_SVG_WIRE}" {_STROKE}/>'
        + _path(sine)
        + _svg_text(cx - r - 10, cy - 8, "+", color=_SVG_VALUE, size=_VAL, weight=600)
        + _svg_text(cx - r - 10, cy + 20, "−", color=_SVG_VALUE, size=_VAL, weight=600)
    )


def _transformer(cx: float, y_bus: float, y0: float, y1: float, y_gnd: float) -> str:
    """Transformador: devanados en espiras, núcleo de dos barras y puntos de polaridad."""
    xp, xs = cx - 14, cx + 14
    dot = 'r="3.2" fill="' + _SVG_WIRE + '"'
    return "".join(
        [
            _wire(xp, y_bus, xp, y0),
            _coil_v(xp, y0, y1, bulge_right=True),
            _wire(xp, y1, xp, y_gnd),
            _ground(xp, y_gnd),
            _wire(cx - 3, y0 - 4, cx - 3, y1 + 4, width=2.2),
            _wire(cx + 3, y0 - 4, cx + 3, y1 + 4, width=2.2),
            _wire(xs, y_bus, xs, y0),
            _coil_v(xs, y0, y1, bulge_right=False),
            _wire(xs, y1, xs, y_gnd),
            _ground(xs, y_gnd),
            f'<circle cx="{xp - 10}" cy="{y0 + 4}" {dot}/>',
            f'<circle cx="{xs + 10}" cy="{y0 + 4}" {dot}/>',
        ]
    )


def _capacitor_v(x: float, y_top: float, y_gnd: float, active: bool) -> str:
    color = _SVG_CYAN
    op = "1" if active else "0.45"
    yp = (y_top + y_gnd) / 2 + 8
    body = (
        _wire(x, y_top, x, yp - 6, color)
        + _wire(x - 18, yp - 6, x + 18, yp - 6, color, 3)
        + _wire(x - 18, yp + 6, x + 18, yp + 6, color, 3)
        + _wire(x, yp + 6, x, y_gnd, color)
        + _ground(x, y_gnd, color)
    )
    return f'<g opacity="{op}">{body}</g>'


def _motor(x: float, y_top: float, y_gnd: float) -> str:
    cy = (y_top + y_gnd) / 2 + 6
    return (
        _wire(x, y_top, x, cy - 24)
        + f'<circle cx="{x}" cy="{cy}" r="24" stroke="{_SVG_WIRE}" {_STROKE}/>'
        + _svg_text(x, cy + 6, "M", color=_SVG_VALUE, size=_VAL, weight=600)
        + _wire(x, cy + 24, x, y_gnd)
        + _ground(x, y_gnd)
    )


def _r_parallel_l(x: float, y_top: float, y_gnd: float) -> str:
    """Carga residencial R ‖ L a tierra."""
    xl, xr = x - 20, x + 20
    ys, ye = y_top + 32, y_gnd - 30
    return "".join(
        [
            _wire(x, y_top, x, ys),
            _wire(xl, ys, xr, ys),
            _wire(xl, ys, xl, ys + 8),
            _resistor_v(xl, ys + 8, ye - 8),
            _wire(xl, ye - 8, xl, ye),
            _wire(xr, ys, xr, ys + 8),
            _coil_v(xr, ys + 8, ye - 8, n=4, bulge_right=True),
            _wire(xr, ye - 8, xr, ye),
            _wire(xl, ye, xr, ye),
            _wire(x, ye, x, y_gnd),
            _ground(x, y_gnd),
            f'<circle cx="{x}" cy="{y_top}" r="4" fill="{_SVG_WIRE}"/>',
        ]
    )


def _fmt(x: float, d: int = 2) -> str:
    return f"{x:,.{d}f}"


def _complex_kva(s: complex, d: int = 2) -> str:
    sign = "+" if s.imag >= 0 else "−"
    return f"{_fmt(s.real, d)} {sign} j{_fmt(abs(s.imag), d)} kVA"


def pf_label(s: complex, tol: float = 1e-9) -> tuple[str, bool]:
    """('0.995 (en atraso)', True) o ('0.98 (en adelanto — sobrecompensado)', False)."""
    pf = abs(s.real) / max(abs(s), 1e-12)
    if s.imag < -tol:
        return f"{pf:.3f} (en adelanto — sobrecompensado)", False
    if abs(s.imag) <= tol:
        return f"{pf:.3f} (unitario)", True
    return f"{pf:.3f} (en atraso)", True


def circuit_svg(
    params: NetworkParameters,
    circuit: CircuitResult,
    t_index: int,
    problem2: bool = True,
    font_css: str = "",
    demand: DemandProfile | None = None,
) -> str:
    """Esquemático SVG autónomo con simbología IEEE/IEC (tarjeta oscura, atributos inline).

    Fuente AC con tierra, resistencias en zigzag, inductancia de línea en espiras, T1/T2 con devanados,
    núcleo y puntos de polaridad, y barra secundaria con las ramas L1 (R‖L), L2 (motor) y Q_C a tierra.
    Se devuelve un ``<svg>`` completo para mostrarlo como imagen (``st.image``), así no pasa por el
    sanitizador HTML; ``font_css`` permite incrustar ``@font-face``.
    """
    t = t_index
    demand = demand or DemandProfile.default()
    i_g, i_l, i_ld = abs(circuit.i_gen[t]), abs(circuit.i_line[t]), abs(circuit.i_load[t])
    v_g = abs(circuit.v_gen[t])
    pg, pl = circuit.p_loss_gen_kw[t], circuit.p_loss_line_kw[t]
    ql = circuit.q_loss_kvar[t]
    s_net = complex(circuit.s_load_kva[t])
    qc = float(circuit.q_c_kvar[t])
    s1 = complex(demand.p1_kw[t], demand.q1_kvar[t])
    s2 = complex(demand.p2_kw[t], demand.q2_kvar[t])
    s_load = s1 + s2
    ok = params.v_gen_min <= v_g <= params.v_gen_max
    v_col = (_SVG_OK if ok else _SVG_BAD) if problem2 else _SVG_VALUE

    y, y_g = 130, 282  # conductor principal y cota de tierra
    x_src, x_rg, x_t1, x_z, x_t2 = 60, 132, 240, 390, 540
    x_bus0, x_l1, x_l2, x_qc = 590, 705, 865, 1005
    x_bus1 = 1052 if problem2 else 930

    parts = [
        f'<rect x="1" y="1" width="{_SVG_W - 2}" height="{_SVG_H - 2}" rx="10" fill="{_SVG_CARD}" '
        f'stroke="{_SVG_BORDER}"/>',
        # Fuente AC a tierra
        _wire(x_src, y, x_src, 181),
        _ac_source(x_src, 205),
        _wire(x_src, 229, x_src, y_g),
        _ground(x_src, y_g),
        _small(x_src, 316, "Generador"),
        _svg_text(94, 196, "|" + _sub("V", "gen") + "|", anchor="start"),
        _value(94, 220, f"{_fmt(v_g, 1)} V", color=v_col, anchor="start"),
        # Rgen en zigzag
        _wire(x_src, y, x_rg - 34, y),
        _resistor_h(x_rg - 34, x_rg + 34, y),
        _svg_text(x_rg, y - 22, _sub("R", "gen") + " = 0.5 Ω"),
        _value(x_rg, y + 34, f"{_fmt(pg, 3)} kW"),
        # Línea: R en zigzag + inductancia en espiras (en serie)
        _resistor_h(x_z - 80, x_z - 10, y),
        _inductor_h(x_z - 4, x_z + 80, y),
        _svg_text(x_z, y - 34, _sub("Z", "line") + " = 80 + j900 Ω"),
        _small(x_z - 45, y + 26, "80 Ω"),
        _small(x_z + 38, y + 26, "j900 Ω"),
        _value(x_z, y + 62, _sub("P", "loss") + f" = {_fmt(pl, 3)} kW"),
        _svg_text(x_z, y + 86, _sub("Q", "loss") + f" = {_fmt(ql, 3)} kvar"),
        _small(x_z, 316, "Línea 13.2 kV" if problem2 else "Línea a 120 V"),
        # Barra secundaria (barraje) a V0
        f'<line x1="{x_bus0}" y1="{y}" x2="{x_bus1}" y2="{y}" stroke="{_SVG_WIRE}" stroke-width="6" '
        'stroke-linecap="round"/>',
        _svg_text(
            x_bus0 + 4,
            y - 16,
            ("Barra secundaria · " if problem2 else "Barra de carga · ") + _sub("V", "0") + " = 120∠0° V",
            anchor="start",
        ),
        # Ramas L1 (R ‖ L) y L2 (motor) a tierra
        _r_parallel_l(x_l1, y, y_g),
        _svg_text(x_l1, 316, "L1 Residencial", color=_SVG_VALUE, size=_SMALL, weight=600),
        _small(x_l1, 336, f"{_fmt(s1.real, 1)} + j{_fmt(s1.imag, 2)} kVA"),
        _small(x_l1, 354, f"fp1 {demand.pf1[t]:.2f} (atraso)"),
        f'<circle cx="{x_l2}" cy="{y}" r="4" fill="{_SVG_WIRE}"/>',
        _motor(x_l2, y, y_g),
        _svg_text(x_l2, 316, "L2 Industrial", color=_SVG_VALUE, size=_SMALL, weight=600),
        _small(x_l2, 336, f"{_fmt(s2.real, 1)} + j{_fmt(s2.imag, 2)} kVA"),
        _small(x_l2, 354, f"fp2 {demand.pf2[t]:.2f} (atraso)" if s2.real > 0 else "fuera de servicio"),
        # Separador y franja inferior: potencia de carga vs. flujo neto en la barra
        _wire(20, 372, _SVG_W - 20, 372, _SVG_BORDER, 1),
        _svg_text(
            20,
            398,
            _sub("S", "carga") + " (L1 + L2) = " + _complex_kva(s_load) + f" · fp {pf_label(s_load)[0]}",
            anchor="start",
        ),
    ]
    if problem2:
        pf_txt, lagging = pf_label(s_net)
        parts += [
            # Corrientes (fila superior)
            _value(x_rg, 38, _sub("I", "gen") + f" = {_fmt(i_g, 3)} A"),
            _flow_arrow(x_rg - 60, x_rg + 60, 54),
            _value(x_z, 38, _sub("I", "line") + f" = {_fmt(i_l, 3)} A"),
            _flow_arrow(x_z - 70, x_z + 70, 54),
            _value(x_bus0 + 70, 38, _sub("I", "load") + f" = {_fmt(i_ld, 2)} A"),
            _flow_arrow(x_bus0, x_bus0 + 140, 54),
            # T1 elevador y T2 reductor
            _wire(x_rg + 34, y, x_t1 - 14, y),
            _transformer(x_t1, y, 160, 240, y_g),
            _wire(x_t1 + 14, y, x_z - 80, y),
            _svg_text(x_t1, 316, "T1 Elevador", color=_SVG_VALUE, size=_SMALL, weight=600),
            _small(x_t1, 336, "1 kV : 13.2 kV"),
            _small(x_t1, 354, _sub("n", "1") + " = 13.2"),
            _wire(x_z + 80, y, x_t2 - 14, y),
            _transformer(x_t2, y, 160, 240, y_g),
            _wire(x_t2 + 14, y, x_bus0, y),
            _svg_text(x_t2, 316, "T2 Reductor", color=_SVG_VALUE, size=_SMALL, weight=600),
            _small(x_t2, 336, "13.2 kV : 120 V"),
            _small(x_t2, 354, _sub("a", "2") + " = 110"),
            # Banco de capacitores (cian) a tierra
            f'<circle cx="{x_qc}" cy="{y}" r="4" fill="{_SVG_CYAN}"/>',
            _capacitor_v(x_qc, y, y_g, active=qc > 1e-9),
            _svg_text(x_qc - 26, 216, _sub("Q", "C"), color=_SVG_CYAN, anchor="end", weight=600),
            _svg_text(x_qc, 316, "Banco " + _sub("Q", "C"), color=_SVG_CYAN, size=_SMALL, weight=600),
            _small(x_qc, 336, f"{_fmt(qc, 2)} kvar", color=_SVG_VALUE),
            _small(x_qc, 354, "activo" if qc > 1e-9 else "0 kvar (desconectado)"),
            _svg_text(
                20,
                424,
                _sub("S", "neto") + " (barra) = " + _complex_kva(s_net) + " · fp neto = "
                f'<tspan fill="{_SVG_OK if lagging else _SVG_WARN}" font-weight="600">{pf_txt}</tspan>',
                anchor="start",
            ),
        ]
    else:
        parts += [
            _value(x_z, 38, "I = " + _sub("I", "line") + f" = {_fmt(i_l, 3)} A"),
            _flow_arrow(x_z - 90, x_z + 90, 54),
            _wire(x_rg + 34, y, x_z - 80, y),
            _wire(x_z + 80, y, x_bus0, y),
            _svg_text(
                20,
                424,
                "Sin transformadores ni banco: " + _sub("S", "neto") + " = " + _sub("S", "carga"),
                anchor="start",
            ),
        ]
    body = "".join(parts)
    defs = f"<defs><style>{font_css}</style></defs>" if font_css else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_SVG_W}" height="{_SVG_H}" '
        f'viewBox="0 0 {_SVG_W} {_SVG_H}" role="img" aria-label="Esquema del circuito">{defs}{body}</svg>'
    )
