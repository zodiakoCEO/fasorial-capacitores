"""Constructores de figuras Plotly (puros: reciben resultados, devuelven ``go.Figure``).

Usados por el dashboard Streamlit. Sin dependencias de UI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

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


def fig_band_hours(scan: pd.DataFrame, q_design: float, hours_at_design: int) -> go.Figure:
    """Horas del día con |V_gen| dentro de la banda en función del Q_C fijo instalado."""
    fig = go.Figure(
        go.Scatter(
            x=scan["Q_C_kvar"],
            y=scan["Horas_en_banda"],
            mode="lines",
            name="Horas en banda",
            line={"color": T.SERIES[0], "width": 2, "shape": "hv"},
            fill="tozeroy",
            fillcolor="rgba(42,120,214,0.12)",
            hovertemplate="Q_C=%{x:.2f} kvar<br>%{y} h en banda<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[q_design],
            y=[hours_at_design],
            mode="markers+text",
            name="Banco fijo adoptado",
            text=[f"{q_design:g} kvar → {hours_at_design}/24 h"],
            textposition="top left",
            textfont={"size": 11},
            marker={"size": 11, "color": T.SERIES[1], "line": {"width": 2, "color": T.SURFACE}},
            hovertemplate=f"Q_C={q_design:g} kvar<br>{hours_at_design} h en banda<extra></extra>",
        )
    )
    _base(
        fig,
        "Horas dentro de [950, 1100] V según el Q_C fijo instalado",
        "Horas en banda (de 24)",
        hovermode="closest",
        showlegend=False,
    )
    fig.update_xaxes(title="Q_C [kvar]")
    fig.update_yaxes(range=[0, 25.5], dtick=4)
    return fig


def fig_compare_vgen(cases: Mapping[str, tuple[StrategyResult, str, str]], params: NetworkParameters) -> go.Figure:
    """|V_gen(t)| de varios casos sobre la banda admisible. cases: nombre → (resultado, color, trazo)."""
    fig = go.Figure()
    fig.add_hrect(
        y0=params.v_gen_min,
        y1=params.v_gen_max,
        fillcolor=T.BAND_FILL,
        line_width=0,
        annotation_text=f"Banda admisible [{params.v_gen_min:g}, {params.v_gen_max:g}] V",
        annotation_position="bottom right",
        annotation_font={"color": T.GOOD, "size": 11},
    )
    for lim in (params.v_gen_min, params.v_gen_max):
        fig.add_hline(y=lim, line={"color": T.GOOD, "width": 1, "dash": "dot"})
    for name, (r, color, dash) in cases.items():
        hours = r.circuit.hours
        fig.add_trace(_line(hours, r.v_gen_mag, name, color, dash, "V", ",.1f"))
        out = r.violation_v > 1e-6
        if out.any():
            fig.add_trace(
                go.Scatter(
                    x=hours[out],
                    y=r.v_gen_mag[out],
                    mode="markers",
                    name=f"Fuera de banda — {name}",
                    marker={"symbol": "x-thin-open", "size": 11, "color": T.CRITICAL, "line": {"width": 2.5}},
                    customdata=r.violation_v[out],
                    showlegend=False,
                    hovertemplate="fuera de banda por %{customdata:.1f} V<extra></extra>",
                )
            )
    _base(fig, "Tensión del generador |V_gen(t)| con banco fijo", "|V_gen| [V]", height=400, xaxis=HOURS_AXIS)
    return fig


def fig_compare_daily_losses(cases: Mapping[str, CircuitResult]) -> go.Figure:
    """Energía perdida al día por caso, apilada en línea y generador. cases: nombre → circuito."""
    names = list(cases)
    fig = go.Figure()
    parts = (
        ("Línea (80 Ω)", [float(c.p_loss_line_kw.sum()) for c in cases.values()]),
        ("Generador (0.5 Ω)", [float(c.p_loss_gen_kw.sum()) for c in cases.values()]),
    )
    for label, vals in parts:
        fig.add_trace(
            go.Bar(
                x=names,
                y=vals,
                name=label,
                marker={"color": T.LOSS_COLOR[label], "line": {"width": 1, "color": T.SURFACE}},
                hovertemplate="%{y:,.2f} kWh/día<extra>" + label + "</extra>",
            )
        )
    totals = [float(c.p_loss_kw.sum()) for c in cases.values()]
    fig.add_trace(
        go.Scatter(
            x=names,
            y=totals,
            mode="text",
            text=[f"{v:,.1f}" for v in totals],
            textposition="top center",
            showlegend=False,
            hoverinfo="skip",
        )
    )
    _base(
        fig, "Pérdidas diarias por caso (línea + generador)", "Energía perdida [kWh/día]", height=400, barmode="stack"
    )
    fig.update_layout(hovermode="closest", bargap=0.35)
    fig.update_yaxes(range=[0, max(totals) * 1.15])
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
# Las dos figuras usan ejes a escala 1:1 para que los ángulos se lean de verdad. Con ``constrain="domain"`` el
# recuadro se ajusta a los rangos pedidos (calculados con los datos) en lugar de estirar los ejes hasta llenar
# el ancho disponible, que en una gráfica a pantalla completa dejaba el diagrama diminuto en medio de un eje
# de −4000 a 6000 V.
PHASOR_HEIGHT = 520
PHASOR_ZOOM_HEIGHT = 680  # cuando se agrega el panel de detalle ampliado
ANIMATION_EXTRA_HEIGHT = 150  # botones, deslizador y más alto: a pantalla completa el alto limita el diagrama
ZOOM_THRESHOLD = 0.35  # si la caída máxima es menor que esta fracción de |V₀ referida|, se agrega el detalle
_TITLE_BAND_PX = 40  # franja superior reservada al título


def _legend_under_title(height: int) -> dict[str, object]:
    """Leyenda horizontal anclada al contenedor, justo debajo del título.

    Al estar referida al contenedor (``yref="container"``) crece hacia abajo cuando se parte en más renglones
    —en columnas angostas— y Plotly reserva ese espacio en el margen superior, así que nunca tapa el título ni
    la gráfica, sea cual sea el ancho.
    """
    return {
        "orientation": "h",
        "yref": "container",
        "y": 1.0 - _TITLE_BAND_PX / height,
        "yanchor": "top",
        "xref": "paper",
        "x": 0.5,
        "xanchor": "center",
    }


def _equal_axes(fig: go.Figure, suffix: str, x_range: Sequence[float], y_range: Sequence[float], x_title: str) -> None:
    """Ejes a escala 1:1 con rangos fijos; el recuadro se pega arriba y se centra en horizontal."""
    fig.update_layout(
        **{
            f"xaxis{suffix}": {
                "title": {"text": x_title},
                "range": list(x_range),
                "constrain": "domain",
                "zeroline": True,
                "zerolinecolor": T.AXIS,
            },
            f"yaxis{suffix}": {
                "range": list(y_range),
                "scaleanchor": f"x{suffix}",
                "scaleratio": 1,
                "constrain": "domain",
                "constraintoward": "top",
                "zeroline": True,
                "zerolinecolor": T.AXIS,
            },
        }
    )


def _bounding_box(
    points: Sequence[complex], pad: float, min_ratio: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Caja que contiene ``points`` con margen ``pad``; ningún lado mide menos de ``min_ratio`` veces el otro."""
    xs, ys = [z.real for z in points], [z.imag for z in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    margin = pad * max(x1 - x0, y1 - y0, 1e-9)
    x0, x1, y0, y1 = x0 - margin, x1 + margin, y0 - margin, y1 + margin
    width, height = x1 - x0, y1 - y0
    if height < min_ratio * width:
        extra = (min_ratio * width - height) / 2
        y0, y1 = y0 - extra, y1 + extra
    elif width < min_ratio * height:
        extra = (min_ratio * height - width) / 2
        x0, x1 = x0 - extra, x1 + extra
    return (float(x0), float(x1)), (float(y0), float(y1))


def fig_power_triangle(
    p_kw: float,
    q_l_kvar: float,
    q_c_kvar: float,
    height: int = PHASOR_HEIGHT,
    p_day: Sequence[float] | None = None,
    q_day: Sequence[float] | None = None,
) -> go.Figure:
    """Triángulo de potencias antes y después del banco, a escala 1:1.

    Con ``p_day`` y ``q_day`` (P y Q de la carga en las 24 h) los ejes quedan fijos para todo el día: al cambiar
    de hora el triángulo crece o se encoge, pero la escala no cambia.
    """
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
        f"S antes = {s_before:.2f} kVA (fp {pf_b:.3f} at.)",
        T.MUTED,
        "dash",
        label=f"S antes = {s_before:.2f} kVA, fp = {pf_b:.3f} en atraso",
    )
    x_qc = 1.04 * p_kw  # el tramo −Q_C se dibuja apenas a la derecha de Q_L para que no se tapen
    if q_c_kvar:
        seg(
            x_qc,
            q_l_kvar,
            x_qc,
            q_net,
            f"−Q_C = −{q_c_kvar:.2f} kvar",
            T.SERIES[2],
            label=f"−Q_C = −{q_c_kvar:.2f} kvar",
        )
    state = "unit." if abs(q_net) < 1e-9 else "ad." if q_net < 0 else "at."
    seg(
        0,
        0,
        p_kw,
        q_net,
        f"S después = {s_after:.2f} kVA (fp {pf_a:.3f} {state})",
        T.SERIES[6],
        label=f"S después = {s_after:.2f} kVA, Q_net = {q_net:.2f} kvar, fp = {pf_a:.3f}",
    )

    p_ref = float(np.max(p_day)) if p_day is not None else p_kw
    q_all = np.asarray(q_day, dtype=float) if q_day is not None else np.array([q_l_kvar], dtype=float)
    y_lo, y_hi = min(0.0, float(q_all.min()) - q_c_kvar), max(0.0, float(q_all.max()))
    x_hi = 1.04 * p_ref
    y_hi = max(y_hi, y_lo + 0.5 * x_hi)  # triángulo muy plano: se abre el eje Q
    pad = 0.07 * max(x_hi, y_hi - y_lo)
    # triángulo muy alto: el recuadro se ensancha (centrado) para que no quede como una franja
    side = max(0.0, 0.62 * (y_hi - y_lo) - x_hi) / 2
    x_range, y_range = (-pad - side, x_hi + pad + side), (y_lo - pad, y_hi + pad)
    _base(
        fig,
        "Triángulo de potencias (antes y después del banco)",
        "Q [kvar]",
        height=height,
        hovermode="closest",
        legend=_legend_under_title(height),
        margin={"l": 60, "r": 20, "t": 70, "b": 52},
    )
    _equal_axes(fig, "", x_range, y_range, "P [kW]")
    return fig


def phasor_components(
    circuit: CircuitResult, params: NetworkParameters, t_index: int, demand: DemandProfile
) -> dict[str, complex]:
    """Fasores referidos al lado del generador (1 kV) para la hora ``t_index`` (0-based).

    V_gen = V_0·a2/n1 + I_line·(R_eq + jX)/n1, con R_eq = R_line + R_gen·n1² (todo visto desde el generador).
    """
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


def _day_phasors(circuit: CircuitResult, params: NetworkParameters, demand: DemandProfile) -> list[dict[str, complex]]:
    return [phasor_components(circuit, params, t, demand) for t in range(demand.n_hours)]


def _day_current_scale(all_ph: Sequence[Mapping[str, complex]]) -> float:
    return nice_current_scale(max(max(abs(p["I_gen"]), abs(p["I_load_sin_QC"])) for p in all_ph))


@dataclass(frozen=True, slots=True)
class PhasorView:
    """Rangos de los ejes del diagrama fasorial, comunes a las 24 horas de un mismo caso.

    ``zoom_x`` / ``zoom_y`` son el detalle ampliado de la punta de V₀; solo existen cuando las caídas son
    pequeñas frente a V₀ referida (línea a 66 kV), porque a escala completa no se distinguen.
    """

    x: tuple[float, float]
    y: tuple[float, float]
    zoom_x: tuple[float, float] | None = None
    zoom_y: tuple[float, float] | None = None

    @property
    def has_zoom(self) -> bool:
        return self.zoom_x is not None


def phasor_view(all_ph: Sequence[Mapping[str, complex]], i_scale: float, params: NetworkParameters) -> PhasorView:
    """Vista del diagrama: caja que contiene todos los fasores del día y, si hace falta, el detalle ampliado."""
    points: list[complex] = []
    for ph in all_ph:
        v0 = ph["V0_ref"]
        points += [0j, v0, v0 + ph["drop_R"], ph["V_gen"], ph["I_gen"] * i_scale, ph["I_load_sin_QC"] * i_scale]
    x, y = _bounding_box(points, pad=0.07, min_ratio=0.45)
    v_ref = max(abs(ph["V0_ref"]) for ph in all_ph)
    if max(abs(ph["drop"]) for ph in all_ph) >= ZOOM_THRESHOLD * v_ref:
        return PhasorView(x, y)
    tips: list[complex] = []
    for ph in all_ph:
        v0, v_gen = ph["V0_ref"], ph["V_gen"]
        tips += [v0, v0 + ph["drop_R"], v_gen]
        direction = v_gen / abs(v_gen)
        # límites de la banda sobre la dirección de V_gen, si quedan cerca de la punta
        tips += [
            lim * direction for lim in (params.v_gen_min, params.v_gen_max) if abs(lim - abs(v_gen)) <= 0.25 * v_ref
        ]
    zoom_x, zoom_y = _bounding_box(tips, pad=0.10, min_ratio=0.62)
    return PhasorView(x, y, zoom_x, zoom_y)


def _phasor_traces(
    ph: Mapping[str, complex], i_scale: float, axis: str = "", showlegend: bool = True
) -> list[go.Scatter]:
    """Los siete fasores de una hora. ``axis="2"`` los dibuja en el panel de detalle (sin repetir la leyenda)."""

    def arrow(
        z0: complex, z1: complex, name: str, color: str, dash: str = "solid", width: float = 3, hover: str = ""
    ) -> go.Scatter:
        z0, z1 = complex(z0), complex(z1)
        return go.Scatter(
            x=[z0.real, z1.real],
            y=[z0.imag, z1.imag],
            mode="lines+markers",
            name=name,
            legendgroup=name,
            showlegend=showlegend,
            xaxis=f"x{axis}",
            yaxis=f"y{axis}",
            line={"color": color, "width": width, "dash": dash},
            marker={"symbol": ["circle", "arrow"], "angleref": "previous", "size": [3, 15], "color": color},
            hovertemplate=hover + "<extra></extra>",
        )

    def polar(z: complex, unit: str) -> str:
        return f"{abs(z):,.2f} {unit} ∠ {np.degrees(np.angle(z)):.2f}°"

    v_ref, drop, v_gen = ph["V0_ref"], ph["drop"], ph["V_gen"]
    tip_r = v_ref + ph["drop_R"]
    return [
        arrow(
            0,
            v_ref,
            f"V₀ referida ({abs(v_ref):,.0f}∠0° V)".replace(",", ""),
            T.SERIES[0],
            hover=f"V₀·a₂/n₁ = {polar(v_ref, 'V')}",
        ),
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


def _phasor_hour_traces(ph: Mapping[str, complex], i_scale: float, with_zoom: bool) -> list[go.Scatter]:
    traces = _phasor_traces(ph, i_scale)
    if with_zoom:
        traces += _phasor_traces(ph, i_scale, axis="2", showlegend=False)
    return traces


def _band_traces(params: NetworkParameters, axis: str = "", showlegend: bool = True) -> list[go.Scatter]:
    """Círculos |V| = V_mín y |V| = V_máx (completos: V_gen puede quedar por debajo del eje real)."""
    theta = np.linspace(0.0, 2.0 * np.pi, 361)
    name = f"Banda |V| = {params.v_gen_min:g} y {params.v_gen_max:g} V"
    return [
        go.Scatter(
            x=r * np.cos(theta),
            y=r * np.sin(theta),
            mode="lines",
            name=name,
            legendgroup="banda",
            showlegend=showlegend and k == 0,
            xaxis=f"x{axis}",
            yaxis=f"y{axis}",
            line={"color": T.GOOD, "width": 1.2, "dash": "dot"},
            hoverinfo="skip",
        )
        for k, r in enumerate((params.v_gen_min, params.v_gen_max))
    ]


def _phasor_figure(
    all_ph: Sequence[Mapping[str, complex]],
    t_index: int,
    params: NetworkParameters,
    i_scale: float,
    title: str,
    animated: bool,
) -> tuple[go.Figure, PhasorView, int]:
    """Figura base del diagrama fasorial. Devuelve (figura, vista, número de trazas que cambian con la hora)."""
    view = phasor_view(all_ph, i_scale, params)
    dynamic = _phasor_hour_traces(all_ph[t_index], i_scale, view.has_zoom)
    fig = go.Figure(dynamic)
    fig.add_traces(_band_traces(params))
    height = PHASOR_HEIGHT
    if view.has_zoom:
        height = PHASOR_ZOOM_HEIGHT
        fig.add_traces(_band_traces(params, axis="2", showlegend=False))
        fig.update_layout(
            xaxis={"anchor": "y", "domain": [0.0, 1.0]},
            yaxis={"anchor": "x", "domain": [0.63, 1.0]},
            xaxis2={"anchor": "y2", "domain": [0.0, 1.0]},
            yaxis2={"anchor": "x2", "domain": [0.0, 0.44]},
        )
    if animated:
        height += ANIMATION_EXTRA_HEIGHT
    _base(
        fig,
        title,
        "Im [V]",
        height=height,
        hovermode="closest",
        legend=_legend_under_title(height),
        margin={"l": 60, "r": 20, "t": 70, "b": 128 if animated else 52},
    )
    # con panel de detalle, el título «Re [V]» va solo en el eje inferior para no chocar con su rótulo
    _equal_axes(fig, "", view.x, view.y, "" if view.has_zoom else "Re [V]")
    if view.has_zoom:
        _equal_axes(fig, "2", view.zoom_x, view.zoom_y, "Re [V]")  # type: ignore[arg-type]
        (zx0, zx1), (zy0, zy1) = view.zoom_x, view.zoom_y  # type: ignore[misc]
        fig.add_shape(
            type="rect",
            xref="x",
            yref="y",
            x0=zx0,
            x1=zx1,
            y0=zy0,
            y1=zy1,
            line={"color": T.MUTED, "width": 1, "dash": "dot"},
        )
        fig.add_annotation(
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.44,
            yanchor="bottom",
            yshift=8,
            showarrow=False,
            text="Detalle ampliado del recuadro: punta de V₀ y caídas",
            font={"size": 12},
        )
        y_label = zy1 - 0.07 * (zy1 - zy0)
        for limit in (params.v_gen_min, params.v_gen_max):  # en el detalle los círculos parecen rectas
            if abs(y_label) < limit and zx0 < (x_label := float(np.sqrt(limit**2 - y_label**2))) < zx1:
                right = x_label > 0.5 * (zx0 + zx1)  # el rótulo va hacia el interior del panel
                fig.add_annotation(
                    xref="x2",
                    yref="y2",
                    x=x_label,
                    y=y_label,
                    xanchor="right" if right else "left",
                    xshift=-4 if right else 4,
                    showarrow=False,
                    text=f"|V| = {limit:g} V",
                    font={"size": 11, "color": T.GOOD},
                )
    return fig, view, len(dynamic)


def fig_phasor_diagram(
    circuit: CircuitResult, params: NetworkParameters, demand: DemandProfile, t_index: int, i_scale: float | None = None
) -> go.Figure:
    """Diagrama fasorial de la hora ``t_index`` (0-based), referido al generador.

    Los ejes y la escala de las corrientes son los del día completo, así que al cambiar de hora solo se mueven
    los fasores. Si las caídas son pequeñas frente a V₀ referida se agrega un panel con el detalle ampliado.
    """
    all_ph = _day_phasors(circuit, params, demand)
    scale = i_scale if i_scale is not None else _day_current_scale(all_ph)
    title = f"Diagrama fasorial referido al generador — hora {t_index + 1}"
    return _phasor_figure(all_ph, t_index, params, scale, title, animated=False)[0]


def _animation_title(hour: int, v_gen: complex) -> str:
    return f"Diagrama fasorial — hora {hour}  |  |V_gen| = {abs(v_gen):,.1f} V"


def fig_phasor_animation(
    circuits_by_hour: CircuitResult, params: NetworkParameters, demand: DemandProfile, i_scale: float | None = None
) -> go.Figure:
    """Diagrama fasorial animado de 24 horas (botones Reproducir / Pausa y deslizador)."""
    n = demand.n_hours
    all_ph = _day_phasors(circuits_by_hour, params, demand)
    scale = i_scale if i_scale is not None else _day_current_scale(all_ph)
    fig, view, n_dyn = _phasor_figure(all_ph, 0, params, scale, _animation_title(1, all_ph[0]["V_gen"]), animated=True)
    fig.frames = [
        go.Frame(
            data=_phasor_hour_traces(all_ph[t], scale, view.has_zoom),
            traces=list(range(n_dyn)),
            name=str(t + 1),
            layout={"title": {"text": _animation_title(t + 1, all_ph[t]["V_gen"])}},
        )
        for t in range(n)
    ]
    fig.update_layout(
        updatemenus=[
            {
                "type": "buttons",
                "direction": "left",
                "x": 0,
                "xanchor": "left",
                "y": 0,
                "yanchor": "top",
                # Botón claro con texto oscuro: Plotly pinta el botón activo y el :hover con un fondo
                # claro fijo (#F4FAFF), así que un texto claro quedaría invisible en tema oscuro.
                "showactive": False,
                "bgcolor": T.BUTTON_BG,
                "bordercolor": T.BUTTON_BORDER,
                "borderwidth": 1,
                "font": {"color": T.BUTTON_INK, "size": 13},
                # la separación va en píxeles para que no dependa del alto de la figura
                "pad": {"t": 78, "b": 4},
                "buttons": [
                    {
                        "label": "Reproducir",
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
                        "label": "Pausa",
                        "method": "animate",
                        "args": [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}],
                    },
                ],
            }
        ],
        sliders=[
            {
                "x": 0,
                "len": 1.0,
                "y": 0,
                "yanchor": "top",
                "pad": {"l": 170, "t": 52},
                "currentvalue": {"prefix": "Hora: ", "xanchor": "right"},
                "bgcolor": T.BUTTON_BORDER,
                "activebgcolor": T.BUTTON_BG,
                "bordercolor": T.BUTTON_BORDER,
                "tickcolor": T.BUTTON_BORDER,
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
# Diagrama de circuito (SVG) — fiel a la Figura 2 del enunciado
# ==================================================================================
# Tarjeta oscura propia: trazo y texto #E2E8F0 sobre #0F172A (contraste 13:1), visible en ambos temas.
_SVG_CARD = "#0F172A"
_SVG_BORDER = "#334155"
_SVG_WIRE = "#E2E8F0"
_SVG_MUTED = "#A8B5C7"
_SVG_VALUE = "#F8FAFC"
_SVG_ACCENT = "#38BDF8"  # flechas y valores de corriente
_SVG_OK = "#4ADE80"
_SVG_BAD = "#F87171"
_SVG_WARN = "#FBBF24"  # fp en adelanto (sobrecompensado)
_SVG_OFF = "#64748B"  # rama del banco cuando Q_C = 0

_SVG_W, _SVG_H = 1080, 408
_Y_TOP, _Y_BOT = 112, 252  # conductor superior y conductor de retorno
_LBL, _VAL, _SMALL = 15, 14, 13  # tamaños de texto (unidades del viewBox)
_STROKE = 'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" fill="none"'


def _sub(base: str, sub: str) -> str:
    """Texto con subíndice SVG (desplazamiento ``dy``, compatible con todos los navegadores)."""
    return f'{base}<tspan dy="4" font-size="0.74em">{sub}</tspan><tspan dy="-4">&#8203;</tspan>'


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


def _wire(x1: float, y1: float, x2: float, y2: float, color: str = _SVG_WIRE, width: float = 1.9) -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" '
        'stroke-linecap="round"/>'
    )


def _path(d: str, color: str = _SVG_WIRE) -> str:
    return f'<path d="{d}" stroke="{color}" {_STROKE}/>'


def _node(x: float, y: float, color: str = _SVG_WIRE) -> str:
    return f'<circle cx="{x}" cy="{y}" r="3" fill="{color}"/>'


def _current_arrow(x: float, y: float) -> str:
    """Punta de flecha sobre el conductor (sentido de la corriente), como en la Figura 2."""
    return f'<path d="M{x - 9},{y - 6} L{x + 6},{y} L{x - 9},{y + 6} Z" fill="{_SVG_ACCENT}"/>'


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


def _inductor_h(x0: float, x1: float, y: float, n: int = 4) -> str:
    """Inductor en espiras (semicírculos) horizontal."""
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


def _voltage_source(x: float, r: float = 22) -> str:
    """Fuente V_gen: círculo con + arriba y − abajo, entre el conductor superior y el de retorno."""
    cy = (_Y_TOP + _Y_BOT) / 2
    return (
        _wire(x, _Y_TOP, x, cy - r)
        + f'<circle cx="{x}" cy="{cy}" r="{r}" stroke="{_SVG_WIRE}" {_STROKE}/>'
        + _svg_text(x, cy - 3, "+", color=_SVG_VALUE, size=17, weight=600)
        + _svg_text(x, cy + 16, "−", color=_SVG_VALUE, size=17, weight=600)
        + _wire(x, cy + r, x, _Y_BOT)
    )


def _transformer(cx: float) -> str:
    """Transformador de la Figura 2: dos devanados en espiras, núcleo de dos líneas y puntos de polaridad."""
    xp, xs = cx - 30, cx + 30
    y0, y1 = _Y_TOP + 30, _Y_BOT - 30
    dot = f'r="3.4" fill="{_SVG_WIRE}"'
    return "".join(
        [
            _wire(xp, _Y_TOP, xp, y0),
            _coil_v(xp, y0, y1, bulge_right=True),
            _wire(xp, y1, xp, _Y_BOT),
            _wire(cx - 3.5, y0, cx - 3.5, y1, width=2.2),
            _wire(cx + 3.5, y0, cx + 3.5, y1, width=2.2),
            _wire(xs, _Y_TOP, xs, y0),
            _coil_v(xs, y0, y1, bulge_right=False),
            _wire(xs, y1, xs, _Y_BOT),
            f'<circle cx="{cx - 13}" cy="{y0 - 5}" {dot}/>',
            f'<circle cx="{cx + 13}" cy="{y0 - 5}" {dot}/>',
        ]
    )


def _load_branch(x: float, label: str) -> str:
    """Rama de carga en derivación (bloque de impedancia) con su etiqueta a la derecha."""
    ya, yb = _Y_TOP + 38, _Y_BOT - 38
    return (
        _wire(x, _Y_TOP, x, ya)
        + f'<rect x="{x - 9}" y="{ya}" width="18" height="{yb - ya}" stroke="{_SVG_WIRE}" {_STROKE}/>'
        + _wire(x, yb, x, _Y_BOT)
        + _svg_text(x + 17, (ya + yb) / 2 + 5, label, color=_SVG_VALUE, anchor="start", weight=600)
    )


def _capacitor_branch(x: float, active: bool) -> str:
    """Rama del banco Q_C; atenuada y con trazo discontinuo cuando Q_C = 0."""
    color = _SVG_WIRE if active else _SVG_OFF
    mid = (_Y_TOP + _Y_BOT) / 2
    dash = "" if active else ' stroke-dasharray="5 5"'
    lead = (
        f'<line x1="{x}" y1="{_Y_TOP}" x2="{x}" y2="{mid - 5}" stroke="{color}" stroke-width="1.9"{dash}/>'
        f'<line x1="{x}" y1="{mid + 5}" x2="{x}" y2="{_Y_BOT}" stroke="{color}" stroke-width="1.9"{dash}/>'
    )
    plates = _wire(x - 15, mid - 5, x + 15, mid - 5, color, 2.6) + _wire(x - 15, mid + 5, x + 15, mid + 5, color, 2.6)
    label = _svg_text(
        x + 22, mid + 5, _sub("Q", "C"), color=_SVG_VALUE if active else _SVG_MUTED, anchor="start", weight=600
    )
    return lead + plates + label


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


def _pf_short(s: complex, tol: float = 1e-9) -> tuple[str, bool]:
    pf = abs(s.real) / max(abs(s), 1e-12)
    if s.imag < -tol:
        return f"{pf:.3f} (adelanto)", False
    return f"{pf:.3f} ({'unitario' if abs(s.imag) <= tol else 'atraso'})", True


def _readout(x: float, title: str, rows: Sequence[tuple[str, str]]) -> str:
    """Columna de lecturas bajo el esquema: título y hasta tres renglones (texto, color)."""
    out = [_svg_text(x, 316, title, color=_SVG_VALUE, size=_SMALL, weight=600, anchor="start")]
    for k, (body, color) in enumerate(rows):
        out.append(_svg_text(x, 340 + 22 * k, body, color=color, size=_SMALL, anchor="start"))
    return "".join(out)


def circuit_svg(
    params: NetworkParameters,
    circuit: CircuitResult,
    t_index: int,
    problem2: bool = True,
    font_css: str = "",
    demand: DemandProfile | None = None,
    title: str | None = None,
) -> str:
    """Esquemático SVG autónomo, fiel a la Figura 2 del enunciado («Distribution system with two loads»).

    Fuente V_gen (+/−) en serie con la resistencia en zigzag de 0.5 Ω; transformador T1 (1kV:13.2kV, o
    1kV:66kV en el Problema 2.1, según ``params``); línea con resistencia en zigzag de 80 Ω en serie con el
    inductor j900 Ω y la flecha I_line; transformador T2 (13.2kV:120V o 66kV:120V);
    lado de carga con V_0 (+/−), la flecha I_load y las ramas en derivación L1, L2 y Q_C cerradas por el
    conductor de retorno. Con ``problem2=False`` se dibuja la red directa (sin transformadores ni banco).
    Bajo el esquema van las lecturas de la hora ``t_index``. Se devuelve un ``<svg>`` completo para
    mostrarlo como imagen (``st.image``); ``font_css`` permite incrustar ``@font-face``.
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
    ok = params.v_gen_min <= v_g <= params.v_gen_max
    v_col = (_SVG_OK if ok else _SVG_BAD) if problem2 else _SVG_VALUE
    active = problem2 and qc > 1e-9

    y, yb, y_lbl = _Y_TOP, _Y_BOT, _Y_TOP - 26
    x_src, x_t1, x_t2 = 84, 276, 626
    rg0, rg1 = 136, 206  # resistencia de 0.5 Ω
    rl0, rl1 = 352, 422  # resistencia de 80 Ω
    x_arrow = 447  # flecha I_line
    xl0, xl1 = 472, 552  # inductor j900 Ω
    x_iload, x_l1, x_l2, x_qc = 712, 800, 890, 985
    x_end = x_qc if problem2 else x_l2
    mid = (y + yb) / 2

    if title is None:
        title = "Figura 2 — Sistema de distribución con dos cargas" if problem2 else "Problema 1 — Red directa a 120 V"
    title = f"{title} · hora {t + 1}"
    parts = [
        f'<rect x="1" y="1" width="{_SVG_W - 2}" height="{_SVG_H - 2}" rx="10" fill="{_SVG_CARD}" '
        f'stroke="{_SVG_BORDER}"/>',
        _svg_text(24, 34, title, color=_SVG_MUTED, size=_SMALL, anchor="start"),
        # Fuente V_gen y resistencia de 0.5 Ω
        _voltage_source(x_src),
        _svg_text(x_src - 30, mid + 5, _sub("V", "gen"), color=_SVG_VALUE, anchor="end", weight=600),
        _wire(x_src, y, rg0, y),
        _resistor_h(rg0, rg1, y),
        _svg_text((rg0 + rg1) / 2, y_lbl, "0.5 Ω", color=_SVG_VALUE),
        # Línea: 80 Ω en zigzag + flecha I_line + inductor j900 Ω
        _resistor_h(rl0, rl1, y),
        _svg_text((rl0 + rl1) / 2, y_lbl, "80 Ω", color=_SVG_VALUE),
        _wire(rl1, y, xl0, y),
        _current_arrow(x_arrow, y),
        _svg_text(x_arrow, y_lbl, _sub("I", "line"), color=_SVG_ACCENT, weight=600),
        _inductor_h(xl0, xl1, y),
        _svg_text((xl0 + xl1) / 2, y_lbl, "j900 Ω", color=_SVG_VALUE),
        # Lado de carga: I_load, V_0 (+/−) y ramas en derivación
        _current_arrow(x_iload, y),
        _svg_text(x_iload, y_lbl, _sub("I", "load"), color=_SVG_ACCENT, weight=600),
        _svg_text(x_iload + 6, y + 30, "+", color=_SVG_BAD, size=17, weight=600),
        _svg_text(x_iload + 6, mid + 6, _sub("V", "0"), color=_SVG_VALUE, size=16, weight=600),
        _svg_text(x_iload + 6, yb - 14, "−", color=_SVG_VALUE, size=17, weight=600),
        _load_branch(x_l1, _sub("L", "1")),
        _load_branch(x_l2, _sub("L", "2")),
        _wire(20, 290, _SVG_W - 20, 290, _SVG_BORDER, 1),
    ]
    l1_txt = _sub("L", "1") + f" = {_fmt(s1.real, 1)} + j{_fmt(s1.imag, 2)} kVA (fp {demand.pf1[t]:.2f})"
    l2_txt = _sub("L", "2") + (
        f" = {_fmt(s2.real, 1)} + j{_fmt(s2.imag, 2)} kVA (fp {demand.pf2[t]:.2f})"
        if s2.real > 0
        else " = 0 kVA (fuera de servicio)"
    )
    load_readout = _readout(
        548,
        "Carga · " + _sub("V", "0") + " = 120∠0° V",
        [(_sub("I", "load") + f" = {_fmt(i_ld, 2)} A", _SVG_ACCENT), (l1_txt, _SVG_MUTED), (l2_txt, _SVG_MUTED)],
    )
    if problem2:
        pf_txt, lagging = _pf_short(s_net)
        parts += [
            # Malla 1: fuente — 0.5 Ω — primario de T1
            _wire(rg1, y, x_t1 - 30, y),
            _wire(x_src, yb, x_t1 - 30, yb),
            _transformer(x_t1),
            _svg_text(x_t1, y_lbl, params.t1_label, color=_SVG_VALUE),
            # Malla 2: secundario de T1 — línea — primario de T2
            _wire(x_t1 + 30, y, rl0, y),
            _wire(xl1, y, x_t2 - 30, y),
            _wire(x_t1 + 30, yb, x_t2 - 30, yb),
            _transformer(x_t2),
            _svg_text(x_t2, y_lbl, params.t2_label, color=_SVG_VALUE),
            # Malla 3: secundario de T2 — L1 ‖ L2 ‖ Q_C
            _wire(x_t2 + 30, y, x_l2, y),
            _wire(x_t2 + 30, yb, x_l2, yb),
            _wire(x_l2, y, x_end, y, _SVG_WIRE if active else _SVG_OFF),
            _wire(x_l2, yb, x_end, yb, _SVG_WIRE if active else _SVG_OFF),
            _capacitor_branch(x_qc, active),
            _node(x_l1, y),
            _node(x_l1, yb),
            _node(x_l2, y),
            _node(x_l2, yb),
            _readout(
                24,
                f"Generador ({params.t1_primary_v / 1000:g} kV)",
                [
                    ("|" + _sub("V", "gen") + f"| = {_fmt(v_g, 2)} V", v_col),
                    (_sub("I", "gen") + f" = {_fmt(i_g, 3)} A", _SVG_ACCENT),
                    (_sub("P", "loss") + f" en 0.5 Ω = {_fmt(pg, 3)} kW", _SVG_MUTED),
                ],
            ),
            _readout(
                292,
                f"Línea ({params.line_kv:g} kV)",
                [
                    (_sub("I", "line") + f" = {_fmt(i_l, 4)} A", _SVG_ACCENT),
                    (_sub("P", "loss") + f" en 80 Ω = {_fmt(pl, 3)} kW", _SVG_MUTED),
                    (_sub("Q", "loss") + f" en j900 Ω = {_fmt(ql, 2)} kvar", _SVG_MUTED),
                ],
            ),
            load_readout,
            _readout(
                818,
                "Banco " + _sub("Q", "C") + " y flujo neto",
                [
                    (
                        _sub("Q", "C") + f" = {_fmt(qc, 2)} kvar" + ("" if active else " (inactivo)"),
                        _SVG_VALUE if active else _SVG_MUTED,
                    ),
                    (_sub("S", "neto") + " = " + _complex_kva(s_net), _SVG_MUTED),
                    ("fp neto = " + pf_txt, _SVG_OK if lagging else _SVG_WARN),
                ],
            ),
        ]
    else:
        s_load = s1 + s2
        parts += [
            # Una sola malla: fuente — 0.5 Ω — 80 Ω — j900 Ω — L1 ‖ L2
            _wire(rg1, y, rl0, y),
            _wire(xl1, y, x_end, y),
            _wire(x_src, yb, x_end, yb),
            _node(x_l1, y),
            _node(x_l1, yb),
            _readout(
                24,
                "Generador",
                [
                    ("|" + _sub("V", "gen") + f"| = {_fmt(v_g, 1)} V", v_col),
                    (_sub("I", "gen") + " = " + _sub("I", "line") + f" = {_fmt(i_g, 3)} A", _SVG_ACCENT),
                    (_sub("P", "loss") + f" en 0.5 Ω = {_fmt(pg, 3)} kW", _SVG_MUTED),
                ],
            ),
            _readout(
                292,
                "Línea (120 V)",
                [
                    (_sub("I", "line") + f" = {_fmt(i_l, 3)} A", _SVG_ACCENT),
                    (_sub("P", "loss") + f" en 80 Ω = {_fmt(pl, 1)} kW", _SVG_MUTED),
                    (_sub("Q", "loss") + f" en j900 Ω = {_fmt(ql, 0)} kvar", _SVG_MUTED),
                ],
            ),
            load_readout,
            _readout(
                818,
                "Sin transformadores ni banco",
                [
                    (_sub("S", "carga") + " = " + _complex_kva(s_load), _SVG_MUTED),
                    ("fp = " + _pf_short(s_load)[0], _SVG_OK),
                ],
            ),
        ]
    body = "".join(parts)
    defs = f"<defs><style>{font_css}</style></defs>" if font_css else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_SVG_W}" height="{_SVG_H}" '
        f'viewBox="0 0 {_SVG_W} {_SVG_H}" role="img" aria-label="Esquema del circuito">{defs}{body}</svg>'
    )
