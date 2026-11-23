"""Laboratorio educativo interactivo — Streamlit + Plotly.

Ejecutar:  streamlit run app/dashboard.py
"""

from __future__ import annotations

import base64
import re
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from src.domain.models import DemandProfile, NetworkParameters, Strategy  # noqa: E402
from src.optimization.capacitor_optimizer import (  # noqa: E402
    ReactanceSensitivity,
    StrategyResult,
    evaluate_strategy,
    feasibility_analysis,
    fixed_economic_optimum,
    format_set,
    line_reactance_sensitivity,
    switched_capacitor_bank,
    total_annual_cost_fixed,
)
from src.optimization.economics import format_cop, format_number  # noqa: E402
from src.optimization.pipeline import AnalysisBundle, run_full_analysis  # noqa: E402
from src.reporting import charts as CH  # noqa: E402
from src.reporting import theme as T  # noqa: E402

st.set_page_config(
    page_title="Laboratorio fasorial — Bancos de capacitores", page_icon=":material/bolt:", layout="wide"
)

# Estilos solicitados explícitamente: cifras en IBM Plex Mono con dígitos tabulares, tarjetas KPI
# de igual altura y presentación limpia sin el botón Deploy.
st.html(
    f"""
<style>
 [data-testid="stAppDeployButton"] {{ display: none; }}
 [data-testid="stMetric"] {{ height: 100%; }}
 [data-testid="stMetricValue"], [data-testid="stMetricDelta"] {{
   font-family: {T.FONT_MONO}; font-variant-numeric: tabular-nums; letter-spacing: -0.01em;
 }}
 [data-testid="stMetricValue"] {{ font-size: 1.15rem; font-weight: 500; }}
 [data-testid="stMetricValue"] * {{
   white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
 }}
 [data-testid="stMetricLabel"] *, [data-testid="stMetricDelta"] * {{
   white-space: normal !important; overflow: visible !important; text-overflow: clip !important;
 }}
 [data-testid="stDataFrame"], [data-testid="stTable"], .katex {{ font-variant-numeric: tabular-nums; }}
 [data-testid="stTable"] td {{ font-family: {T.FONT_MONO}; }}
</style>
"""
)

KVA = r"\text{kVA}"
PLOT_CFG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 3}}

STRATEGY_UI: dict[Strategy, str] = {
    Strategy.NO_CAPACITOR: "Sin capacitor (Qc = 0)",
    Strategy.FIXED_ECONOMIC: "Banco fijo — óptimo económico",
    Strategy.FIXED_MIN_VIOLATION: "Banco fijo — mínima violación de tensión",
    Strategy.SWITCHED: "Banco automático por pasos (100 % factible)",
    Strategy.FIXED_LAGGING: "Banco fijo — 100 % en atraso",
    Strategy.SWITCHED_LAGGING: "Banco automático por pasos — 100 % en atraso",
    Strategy.MANUAL: "Manual (Qc ajustable)",
}

# Símbolos con subíndice: "V_gen" → "V<sub>gen</sub>" (Plotly) o "Vgen" (texto plano de widgets).
_SUBSCRIPT = re.compile(r"(?<![A-Za-z0-9])([A-Z])_\{?([A-Za-z0-9]+)\}?")
# Glifos decorativos que las figuras compartidas con el reporte traen y que la UI omite
# (escritos como escapes: check, warning, play, pause).
_CHECK, _WARN, _PLAY, _PAUSE = chr(0x2713), chr(0x26A0), chr(0x25B6), chr(0x23F8)
_GLYPHS = {
    f"{_CHECK} ": "",
    f"{_WARN} ": "",
    f"{_PLAY} Play": "Reproducir",
    f"{_PAUSE} Pausa": "Pausa",
    _CHECK: "",
    _WARN: "",
}


def plain(text: str) -> str:
    """Texto visible sin guiones bajos literales (Q_C → Qc, V_gen → Vgen)."""
    return _SUBSCRIPT.sub(lambda m: m.group(1) + (m.group(2).lower() if m.group(2) == "C" else m.group(2)), text)


def _rich(text: str | None) -> str | None:
    if not isinstance(text, str):
        return text
    for old, new in _GLYPHS.items():
        text = text.replace(old, new)
    return _SUBSCRIPT.sub(r"\1<sub>\2</sub>", text)


def tidy(fig: go.Figure) -> go.Figure:
    """Pulido tipográfico de una figura: subíndices HTML y sin glifos decorativos."""

    def fix_traces(traces: tuple) -> None:
        for tr in traces:
            for attr in ("name", "hovertemplate"):
                if isinstance(getattr(tr, attr, None), str):
                    setattr(tr, attr, _rich(getattr(tr, attr)))
            txt = getattr(tr, "text", None)
            if isinstance(txt, str):
                tr.text = _rich(txt)
            elif txt is not None and len(txt) and isinstance(txt[0], str):
                tr.text = [_rich(x) for x in txt]

    fix_traces(fig.data)
    lay = fig.layout
    if lay.title and lay.title.text:
        lay.title.text = _rich(lay.title.text)
    for key in list(lay.to_plotly_json()):
        if key.startswith(("xaxis", "yaxis")) and lay[key].title and lay[key].title.text:
            lay[key].title.text = _rich(lay[key].title.text)
    for ann in lay.annotations or ():
        ann.text = _rich(ann.text)
    for menu in lay.updatemenus or ():
        for btn in menu.buttons:
            btn.label = _rich(btn.label)
    for frame in fig.frames or ():
        fix_traces(frame.data)
        if frame.layout and frame.layout.title and frame.layout.title.text:
            frame.layout.title.text = _rich(frame.layout.title.text)
    return fig


def plot(target: object, fig: go.Figure) -> None:
    target.plotly_chart(tidy(fig), width="stretch", config=PLOT_CFG)  # type: ignore[attr-defined]


def ui_result(r: StrategyResult) -> StrategyResult:
    """Copia de presentación con etiqueta sin guiones bajos (no altera ningún cálculo)."""
    label = STRATEGY_UI[r.strategy] if r.strategy is Strategy.NO_CAPACITOR else plain(r.label)
    return replace(r, label=label)


# ==================================================================================
# Datos y caché
# ==================================================================================
@st.cache_resource(show_spinner="Resolviendo flujos de potencia y optimizaciones…")
def load_bundle(step: float) -> AnalysisBundle:
    csv = ROOT / "data" / "demand_profile_24h.csv"
    demand = DemandProfile.from_csv(csv) if csv.exists() else DemandProfile.default()
    return run_full_analysis(demand, switched_step_kvar=step, include_sensitivity=False)


@st.cache_resource(show_spinner="Barriendo la reactancia de línea…")
def load_sensitivity(r_line: float, r_gen: float) -> ReactanceSensitivity:
    params = NetworkParameters(r_gen=r_gen, z_line=complex(r_line, 900.0))
    return line_reactance_sensitivity(DemandProfile.default(), params, x_max=1200.0, scan_step=5.0)


@st.cache_data
def svg_font_css() -> str:
    """@font-face de IBM Plex Mono incrustado (data URI) para los diagramas SVG mostrados como imagen."""
    fonts = ROOT / "app" / "assets" / "fonts"
    rules = []
    for weight, name in ((400, "IBMPlexMono-Regular-latin.woff2"), (600, "IBMPlexMono-SemiBold-latin.woff2")):
        path = fonts / name
        if path.exists():
            b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            rules.append(
                f"@font-face{{font-family:'IBM Plex Mono';font-weight:{weight};"
                f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
            )
    return "".join(rules)


def one_line_diagram(circuit_label: str, circuit: object, t_index: int, problem2: bool) -> None:
    svg = CH.circuit_svg(P, circuit, t_index, problem2=problem2, font_css=svg_font_css(), demand=D)  # type: ignore[arg-type]
    st.image(svg, width="stretch", alt=f"Esquema del circuito — {circuit_label}, hora {t_index + 1}")


T1_T2_TEXT = (
    "**T1 — Transformador elevador (1 kV : 13.2 kV, n₁ = 13.2).** Ubicado a la salida del generador; eleva la "
    "tensión para transportar la potencia con menor corriente y reducir las pérdidas I²R en la línea.\n\n"
    "**T2 — Transformador reductor (13.2 kV : 120 V, a₂ = 110).** Ubicado junto a la barra de carga; reduce la "
    "tensión de 13.2 kV a V₀ = 120∠0° V para alimentar L1 (residencial) y L2 (industrial)."
)


def cop_millions(value: float) -> str:
    """Valor COP compacto para tarjetas KPI (el valor exacto va en el tooltip)."""
    return f"$ {format_number(value / 1e6, 2)} M"


def fc(z: complex, d: int = 4, unit: str = "") -> str:
    """Complejo en forma rectangular y polar para LaTeX."""
    sign = "+" if z.imag >= 0 else "-"
    return (
        rf"{z.real:,.{d}f} {sign} j{abs(z.imag):,.{d}f}\;{unit} \\ = "
        rf"{abs(z):,.{d}f}\angle{np.degrees(np.angle(z)):.4f}^\circ\;{unit}"
    ).replace(",", r"\,")


def pf_badge(r: StrategyResult) -> None:
    if r.is_always_lagging:
        st.badge(f"fp neto {r.pf_status}", icon=":material/check_circle:", color="green")
    else:
        st.badge(f"fp neto: {r.pf_status} (sobrecompensado)", icon=":material/warning:", color="orange")


def band_badge(r: StrategyResult) -> None:
    if r.is_voltage_feasible:
        st.badge("24/24 h dentro de [950, 1100] V", icon=":material/check_circle:", color="green")
    else:
        st.badge(
            f"{r.hours_out_of_band}/24 h fuera de banda · máx {r.max_violation_v:,.1f} V",
            icon=":material/warning:",
            color="red",
        )


NEUTRAL = {"delta_color": "off", "delta_arrow": "off"}

# ==================================================================================
# Sidebar
# ==================================================================================
with st.sidebar:
    st.header("Laboratorio fasorial", icon=":material/bolt:")
    st.caption("Red de distribución de 24 h · Optimización técnico-económica de Qc")
    step = st.select_slider("Paso del banco automático [kvar]", options=[5.0, 10.0, 12.5, 20.0, 25.0, 50.0], value=25.0)
    st.divider()
    st.markdown(
        r"""
**Parámetros (enunciado)**
- $V_0 = 120\angle 0^\circ$ V
- $R_{gen}=0.5\,\Omega$, $Z_{line}=80+j900\,\Omega$
- **T1 — Elevador** (1 kV : 13.2 kV, $n_1 = 13.2$): a la salida del generador; eleva la tensión para
  transportar con menor corriente y reducir las pérdidas $I^2R$ de la línea.
- **T2 — Reductor** (13.2 kV : 120 V, $a_2 = 110$): junto a la barra de carga; baja 13.2 kV a
  $V_0 = 120\angle 0^\circ$ V para alimentar L1 (residencial) y L2 (industrial).
- 960 COP/kWh · 365 d · 100 000 COP/kvar
- $950 \le |V_{gen}| \le 1100$ V
"""
    )

B = load_bundle(step)
P = B.params
D = B.demand
STRATS = {k: ui_result(v) for k, v in B.strategies.items()}
rec = STRATS[Strategy.SWITCHED]
NO_CAP = STRATS[Strategy.NO_CAPACITOR]
LAG = B.lagging_limit
P1_DAILY_COST = B.problem1.daily_energy_loss_kwh * P.energy_price_cop_per_kwh


def comparison_frame() -> pd.DataFrame:
    """Tabla comparativa (incluye fp neto mín–máx y estado del fp en las 24 h)."""
    table = B.comparison_table()
    return pd.DataFrame(
        {
            "Estrategia": [plain(x) for x in table["Estrategia"]],
            "Qc instalado [kvar]": table["Q_C_instalado_kvar"].round(3),
            "Pérdidas [kWh/día]": table["E_loss_kWh_dia"].round(3),
            "CAPEX": table["CAPEX_COP"].map(format_cop),
            "Costo total anual": table["Costo_total_anual_COP"].map(format_cop),
            "Ahorro anual": table["Ahorro_anual_COP"].map(format_cop),
            "Payback [días]": table["Payback_dias"].map(lambda x: format_number(x, 1)),
            "|Vgen| mín–máx [V]": [
                f"{a:,.1f} – {b:,.1f}" for a, b in zip(table["V_gen_min_V"], table["V_gen_max_V"], strict=True)
            ],
            "Horas fuera de banda": table["Horas_fuera_banda"],
            "fp neto mín–máx": [
                f"{a:.3f} – {b:.3f}" for a, b in zip(table["fp_neto_min"], table["fp_neto_max"], strict=True)
            ],
            "Estado fp (24 h)": table["Estado_fp_24h"],
        }
    )


st.title("Análisis fasorial y optimización de bancos de capacitores")
st.caption("Análisis de Circuitos AC · Red de distribución de 24 horas")

tabs = st.tabs(
    [
        ":material/monitoring: Resumen ejecutivo",
        ":material/electrical_services: Problema 1 — 120 V",
        ":material/tune: Problema 2 — Optimización de Qc",
        ":material/school: Modo docente",
        ":material/sliders: Simulador what-if",
    ]
)

# ==================================================================================
# 1. Resumen ejecutivo
# ==================================================================================
with tabs[0]:
    p1 = B.problem1
    e = rec.economics
    st.subheader("Impacto de la solución recomendada: transformadores + banco automático por pasos")
    c = st.columns(6)
    c[0].metric(
        "Corriente de línea máx.",
        f"{np.abs(rec.circuit.i_line).max():.2f} A",
        f"-{100 * (1 - np.abs(rec.circuit.i_line).max() / np.abs(p1.i_line).max()):.3f} % vs P1",
        delta_color="inverse",
        border=True,
        height="stretch",
    )
    c[1].metric(
        "Pérdidas diarias P1 → P2",
        f"{e.daily_loss_kwh:,.1f} kWh",
        f"-{p1.daily_energy_loss_kwh - e.daily_loss_kwh:,.0f} kWh/día",
        delta_color="inverse",
        border=True,
        height="stretch",
    )
    c[2].metric(
        "Ahorro anual vs Qc = 0",
        cop_millions(e.annual_savings_cop),
        f"-{e.loss_reduction_pct:.1f} % pérdidas",
        help="Valor exacto: " + format_cop(e.annual_savings_cop),
        delta_color="inverse",
        border=True,
        height="stretch",
    )
    c[3].metric(
        "CAPEX del banco",
        cop_millions(e.capex_cop),
        f"{B.switched.n_steps} × {B.switched.step_kvar:g} kvar",
        help="Valor exacto: " + format_cop(e.capex_cop),
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[4].metric(
        "Beneficio neto año 1",
        cop_millions(e.net_first_year_benefit_cop),
        "Año 1 neto",
        help="Valor exacto: " + format_cop(e.net_first_year_benefit_cop),
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[5].metric(
        "Payback",
        f"{e.payback_days:,.0f} días",
        f"{e.payback_months:.1f} meses",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    band_badge(rec)
    st.caption(
        f"Problema 1 (b): {format_number(p1.daily_energy_loss_kwh, 2)} kWh/día de pérdidas × "
        f"{P.energy_price_cop_per_kwh:g} COP/kWh = **{format_cop(P1_DAILY_COST)} por día** "
        f"({format_cop(P1_DAILY_COST * P.days_per_year)} por año)."
    )
    with st.container(border=True):
        st.markdown(T1_T2_TEXT)

    st.markdown("#### Diagrama del circuito interactivo")
    h = st.slider("Hora", 1, 24, 12, key="sum_hour")
    st.markdown("**Problema 1 — red directa a 120 V**")
    one_line_diagram("Problema 1", p1, h - 1, problem2=False)
    share = p1.p_loss_gen_kw[h - 1] / p1.p_loss_kw[h - 1]
    st.caption(
        f"Pérdidas: {p1.p_loss_kw[h - 1]:,.1f} kW ({100 * share:.2f} % en Rgen, "
        f"{100 * (1 - share):.2f} % en Rline) para servir {D.p_total_kw[h - 1]:.0f} kW."
    )
    diag_options = [s.value for s in Strategy if s is not Strategy.MANUAL]
    diag_choice = Strategy(
        st.selectbox(
            "Estrategia visualizada en el circuito del Problema 2",
            diag_options,
            index=diag_options.index(Strategy.SWITCHED_LAGGING.value),
            format_func=lambda v: STRATEGY_UI[Strategy(v)],
            key="diag_strategy",
        )
    )
    diag = STRATS[diag_choice]
    st.markdown(f"**Problema 2 — {diag.label}**")
    one_line_diagram("Problema 2", diag.circuit, h - 1, problem2=True)
    c2 = diag.circuit
    share2 = c2.p_loss_gen_kw[h - 1] / c2.p_loss_kw[h - 1]
    st.caption(
        f"Pérdidas: {c2.p_loss_kw[h - 1]:,.3f} kW ({100 * share2:.1f} % en Rgen referida "
        f"= 87.12 Ω, {100 * (1 - share2):.1f} % en Rline = 80 Ω)."
    )
    b1, b2 = st.columns(2)
    with b1:
        band_badge(diag)
    with b2:
        pf_badge(diag)

    st.markdown("#### Comparativa de estrategias (Problema 2)")
    st.dataframe(comparison_frame(), hide_index=True, width="stretch")
    st.info(
        f"**Hallazgo central:** no existe un Qc fijo que mantenga |Vgen| en [950, 1100] V las 24 h "
        f"(intersección {format_set(B.feasibility.global_set)}; par crítico de horas {B.feasibility.critical_pair}). "
        f"El óptimo económico fijo ({B.economic.q_c_closed_form_kvar:.2f} kvar) es el más barato pero viola la banda "
        f"en {B.economic.result.hours_out_of_band} h; el banco automático cumple el 100 % de las horas.",
        icon=":material/info:",
    )
    st.warning(
        f"**Factor de potencia en atraso vs. regulación de tensión:** con fp neto en atraso (Qneto ≥ 0) la "
        f"menor |Vgen| alcanzable en la hora {LAG.worst_hour} es {LAG.max_floor_v:,.2f} V (Qneto = 0, fp = 1.0), "
        f"mayor que 1100 V. Con Xline = 900 Ω solo {LAG.hours_band_reachable_lagging}/24 h pueden quedar dentro "
        "de [950, 1100] V sin sobrecompensar: cumplir la banda las 24 h exige inyección capacitiva en adelanto.",
        icon=":material/balance:",
    )

# ==================================================================================
# 2. Problema 1
# ==================================================================================
with tabs[1]:
    p1 = B.problem1
    st.subheader("Problema 1 — Red directa a 120 V: diagnóstico de pérdidas absurdas")
    c = st.columns(4)
    c[0].metric(
        "|Iline(1)|",
        f"{abs(p1.i_line[0]):.7f} A",
        f"∠ {np.degrees(np.angle(p1.i_line[0])):.8f}°",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[1].metric("Ploss(1)", f"{p1.p_loss_kw[0]:,.5f} kW", "Hora 1", border=True, height="stretch", **NEUTRAL)
    c[2].metric("Qloss(1)", f"{p1.q_loss_kvar[0]:,.4f} kvar", "Hora 1", border=True, height="stretch", **NEUTRAL)
    c[3].metric("|Sgen(1)|", f"{abs(p1.s_gen_kva[0]):,.4f} kVA", "Hora 1", border=True, height="stretch", **NEUTRAL)
    k = st.columns(2)
    k[0].metric(
        "Pérdidas diarias P1 (b)",
        f"{p1.daily_energy_loss_kwh:,.2f} kWh",
        "Energía perdida en 24 h",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    k[1].metric(
        "Costo diario de pérdidas P1 (b)",
        cop_millions(P1_DAILY_COST),
        f"× {P.energy_price_cop_per_kwh:g} COP/kWh",
        help="Valor exacto: " + format_cop(P1_DAILY_COST),
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    st.caption(
        ":material/check_circle: Golden Test de la hora 1 verificado por `tests/test_physics_golden.py` "
        "(tolerancia < 1e-4)."
    )

    g1, g2 = st.columns(2)
    plot(
        g1,
        CH.fig_hourly_metric(
            p1.hours,
            {"|I_line|": (np.abs(p1.i_line), T.SERIES[0], "solid")},
            "Corriente de línea |I_line(t)|",
            "|I_line| [A]",
            "A",
        ),
    )
    plot(
        g2,
        CH.fig_hourly_metric(
            p1.hours,
            {
                "P_loss": (p1.p_loss_kw, T.SERIES[0], "solid"),
                "P carga útil": (p1.s_load_kva.real, T.SERIES[1], "solid"),
            },
            "Pérdidas activas vs. potencia útil (log)",
            "Potencia [kW]",
            "kW",
            log_y=True,
        ),
    )
    g3, g4 = st.columns(2)
    plot(
        g3,
        CH.fig_hourly_metric(
            p1.hours,
            {"|S_gen|": (np.abs(p1.s_gen_kva), T.SERIES[0], "solid")},
            "Potencia aparente del generador |S_gen(t)|",
            "|S_gen| [kVA]",
            "kVA",
            fmt=",.0f",
        ),
    )
    plot(g4, CH.fig_load_breakdown(D))

    ratio = p1.daily_energy_loss_kwh / p1.daily_energy_served_kwh
    imax = int(np.argmax(np.abs(p1.i_line)))
    st.markdown("#### :material/insights: Hallazgos físicos automáticos")
    st.markdown(
        f"""
- La corriente máxima es **{np.abs(p1.i_line).max():,.1f} A** (hora {imax + 1}); transportar ~{D.p_total_kw[imax]:.0f} kW a
  120 V exige cientos de amperios.
- Las pérdidas diarias son **{p1.daily_energy_loss_kwh:,.0f} kWh** frente a **{p1.daily_energy_served_kwh:,.0f} kWh** útiles:
  **{ratio:,.0f} veces** la energía entregada (eficiencia ≈ {100 / (1 + ratio):.3f} %).
- El generador debe producir hasta **{np.abs(p1.s_gen_kva).max() / 1e3:,.0f} MVA**, dominados por $Q_{{loss}}=|I|^2\\cdot 900$:
  la línea consume {p1.q_loss_kvar.sum() / max(p1.p_loss_kw.sum(), 1e-9):.2f} kvar por cada kW perdido ($X/R = 900/80.5$).
- Costo diario de pérdidas: {p1.daily_energy_loss_kwh:,.2f} kWh × {P.energy_price_cop_per_kwh:g} COP/kWh =
  **{format_cop(P1_DAILY_COST)}/día**; costo anual: **{format_cop(P1_DAILY_COST * P.days_per_year)}**.
  Conclusión: es imprescindible elevar la tensión de distribución (Problema 2).
"""
    )

# ==================================================================================
# 3. Problema 2
# ==================================================================================
with tabs[2]:
    st.subheader("Problema 2 — Red con transformadores ideales y optimización de Qc")
    options = [s.value for s in Strategy]
    choice = Strategy(
        st.radio("Estrategia", options, index=3, horizontal=True, format_func=lambda v: STRATEGY_UI[Strategy(v)])
    )
    if choice is Strategy.MANUAL:
        q_manual = st.slider("Qc fijo manual [kvar]", 0.0, 500.0, 91.0, 0.5)
        sel = evaluate_strategy(
            D,
            P,
            q_manual,
            Strategy.MANUAL,
            label=f"Manual Qc = {q_manual:.1f} kvar",
            baseline_daily_loss_kwh=B.no_capacitor.economics.daily_loss_kwh,
        )
    else:
        sel = STRATS[choice]
    e = sel.economics
    c = st.columns(6)
    c[0].metric(
        "Qc instalado",
        f"{sel.q_c_installed_kvar:,.2f} kvar",
        "Fijo" if np.ptp(sel.q_c_profile_kvar) == 0 else "Variable por hora",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[1].metric(
        "|Iline| máx",
        f"{np.abs(sel.circuit.i_line).max():.3f} A",
        "Lado de 13.2 kV",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[2].metric(
        "Pérdidas diarias",
        f"{e.daily_loss_kwh:,.2f} kWh",
        f"{-e.daily_loss_reduction_kwh:+,.1f} kWh vs Qc = 0",
        delta_color="inverse",
        border=True,
        height="stretch",
    )
    c[3].metric(
        "Costo total anual J",
        cop_millions(e.total_annual_cost_cop),
        "OPEX + CAPEX",
        help="Valor exacto: " + format_cop(e.total_annual_cost_cop),
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[4].metric(
        "Ahorro anual",
        cop_millions(e.annual_savings_cop),
        "vs Qc = 0",
        help="Valor exacto: " + format_cop(e.annual_savings_cop),
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[5].metric(
        "Payback",
        f"{format_number(e.payback_days, 1)} días",
        f"{format_number(e.payback_months, 1)} meses",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    b1, b2 = st.columns(2)
    with b1:
        band_badge(sel)
    with b2:
        pf_badge(sel)

    compare = st.checkbox("Superponer 'Sin capacitor' como referencia", value=True)
    vlist = [NO_CAP, sel] if compare and sel.strategy is not Strategy.NO_CAPACITOR else [sel]
    col1, col2 = st.columns(2)
    plot(col1, CH.fig_vgen_band(vlist, P))
    series = {r.label: (np.abs(r.circuit.i_line), *CH.strategy_style(r.strategy)) for r in vlist}
    plot(
        col2,
        CH.fig_hourly_metric(
            D.hours, series, "Corriente de línea |I_line(t)| (13.2 kV)", "|I_line| [A]", "A", fmt=".3f", height=400
        ),
    )
    col3, col4 = st.columns(2)
    plot(col3, CH.fig_losses_stacked(sel.circuit, f"P_loss(t) apilada — {sel.label}"))
    markers = {
        "Óptimo económico": (
            B.economic.result.q_c_installed_kvar,
            B.economic.result.economics.total_annual_cost_cop,
            T.SERIES[1],
        ),
        "Mín. violación": (
            B.pareto.minimax.q_c_installed_kvar,
            B.pareto.minimax.economics.total_annual_cost_cop,
            T.SERIES[4],
        ),
    }
    if choice is Strategy.MANUAL:
        markers["Manual"] = (
            sel.q_c_installed_kvar,
            float(total_annual_cost_fixed(sel.q_c_installed_kvar, D, P)),
            T.SERIES[6],
        )
    plot(col4, CH.fig_cost_curve(B.pareto.grid, markers))

    overlays = {sel.label: (sel.q_c_profile_kvar, *CH.strategy_style(sel.strategy))}
    plot(st, CH.fig_feasibility_map(B.feasibility, overlays))
    with st.expander("Detalle del diagnóstico de factibilidad y frontera de Pareto", icon=":material/functions:"):
        st.markdown(
            rf"""
$|V_{{gen}}(t,Q_C)|^2 = a\,Q_C^2 + b(t)\,Q_C + c(t)$ (parábola convexa) ⇒ cada hora tiene 1 o 2 intervalos factibles,
resueltos en forma cerrada y verificados con malla + `brentq` (desviación máx.
{B.feasibility.max_numeric_deviation_kvar:.2e} kvar). Intersección de las 24 h: **{format_set(B.feasibility.global_set)}**.
Pares en conflicto: {", ".join(map(str, B.feasibility.conflicting_pairs))}.
"""
        )
        st.dataframe(
            B.feasibility.to_dataframe()[["hour", "conjunto_analitico", "conjunto_numerico"]].rename(
                columns={
                    "hour": "Hora",
                    "conjunto_analitico": "Conjunto analítico [kvar]",
                    "conjunto_numerico": "Verificación numérica [kvar]",
                }
            ),
            hide_index=True,
            width="stretch",
        )
        hl = {
            "Óptimo económico": (
                B.economic.result.max_violation_v,
                B.economic.result.economics.total_annual_cost_cop,
                T.SERIES[1],
            ),
            "Minimax": (
                B.pareto.minimax.max_violation_v,
                B.pareto.minimax.economics.total_annual_cost_cop,
                T.SERIES[4],
            ),
        }
        plot(st, CH.fig_pareto(B.pareto.grid, B.pareto.front, hl))
    if sel.strategy is Strategy.SWITCHED_LAGGING:
        with st.expander("Programa horario del banco en atraso", expanded=True, icon=":material/schedule:"):
            st.dataframe(
                B.switched_lagging.schedule.round(4).rename(
                    columns={
                        "hour": "Hora",
                        "Q_load_kvar": "Qcarga [kvar]",
                        "pasos_activos": "Pasos activos",
                        "Q_C_kvar": "Qc [kvar]",
                        "Q_net_kvar": "Qneto [kvar]",
                        "pf_net": "fp neto",
                        "V_gen_V": "|Vgen| [V]",
                        "P_loss_kW": "Pérdidas [kW]",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
    if sel.strategy is Strategy.FIXED_LAGGING:
        fl = B.fixed_lagging
        st.caption(
            f"Qc* libre = {fl.q_c_unconstrained_kvar:.4f} kvar > cota de atraso min Q(t) = "
            f"{fl.q_c_upper_bound_kvar:.4f} kvar (hora {fl.binding_hour}) ⇒ restricción activa; "
            f"verificación numérica acotada: {fl.q_c_numeric_kvar:.6f} kvar."
        )

    st.markdown("#### :material/balance: Requisito de fp en atraso vs. regulación estricta [950, 1100] V")
    st.markdown(
        rf"""
**Teorema.** $|V_{{gen}}(t,Q_C)|^2 = a\,Q_C^2 + b(t)\,Q_C + c(t)$ es convexa; su mínimo en el
intervalo de atraso $0 \le Q_C \le Q(t)$ está en $Q_C = Q(t)$ para las 24 h ($Q_{{neto}} = 0$, fp = 1.0). En la hora
{LAG.worst_hour}: $\min |V_{{gen}}| = {LAG.max_floor_v:.2f}\ \text{{V}} > 1100\ \text{{V}}$. Por tanto, con
$X_{{line}} = 900\ \Omega$ **ningún** banco (fijo o automático, continuo o discreto) puede cumplir la banda en
horas pico manteniendo el fp en atraso: la caída $jI\cdot X$ con corriente en fase o en atraso siempre eleva
$|V_{{gen}}|$ por encima del límite. Solo {LAG.hours_band_reachable_lagging}/24 h admiten la banda sin adelanto.
"""
    )
    lag_cmp = pd.DataFrame(
        [
            {
                "Diseño": STRATEGY_UI[r.strategy],
                "Qc instalado [kvar]": round(r.q_c_installed_kvar, 3),
                "Costo total anual": format_cop(r.economics.total_annual_cost_cop),
                "Payback [días]": format_number(r.economics.payback_days, 1),
                "|Vgen| máx [V]": round(float(r.v_gen_mag.max()), 2),
                "Horas fuera de banda": r.hours_out_of_band,
                "fp neto mín–máx": f"{r.pf_net.min():.3f} – {r.pf_net.max():.3f}",
                "Estado fp (24 h)": r.pf_status,
            }
            for r in (
                STRATS[Strategy.FIXED_LAGGING],
                STRATS[Strategy.SWITCHED_LAGGING],
                STRATS[Strategy.SWITCHED],
            )
        ]
    )
    st.dataframe(lag_cmp, hide_index=True, width="stretch")
    with st.expander("Cota de |Vgen| alcanzable en atraso, hora por hora", icon=":material/table:"):
        st.dataframe(
            LAG.to_dataframe()
            .round(3)
            .rename(
                columns={
                    "hour": "Hora",
                    "Q_load_kvar": "Qcarga [kvar]",
                    "V_gen_QC0_V": "|Vgen| con Qc = 0 [V]",
                    "V_gen_fp1_V": "|Vgen| con fp = 1 [V]",
                    "V_gen_min_en_atraso_V": "Mín. |Vgen| en atraso [V]",
                    "Q_C_en_minimo_kvar": "Qc en el mínimo [kvar]",
                    "banda_alcanzable_en_atraso": "Banda alcanzable en atraso",
                    "Q_C_min_banda_kvar": "Qc mín. para la banda [kvar]",
                    "Q_net_requerido_banda_kvar": "Qneto requerido [kvar]",
                    "fp_requerido_banda": "fp requerido",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    if sel.strategy is Strategy.SWITCHED:
        with st.expander("Programa horario del banco automático", expanded=True, icon=":material/schedule:"):
            st.dataframe(
                B.switched.schedule.round(3).rename(
                    columns={
                        "hour": "Hora",
                        "Q_C_kvar": "Qc [kvar]",
                        "pasos_activos": "Pasos activos",
                        "V_gen_V": "|Vgen| [V]",
                        "P_loss_kW": "Pérdidas [kW]",
                    }
                ),
                hide_index=True,
                width="stretch",
            )

# ==================================================================================
# 4. Modo docente
# ==================================================================================
with tabs[3]:
    st.subheader("Laboratorio fasorial paso a paso")
    cA, cB = st.columns([1, 2])
    with cA:
        hour = st.slider("Hora t", 1, 24, 12, key="teach_hour")
        teach_options = [s.value for s in Strategy if s is not Strategy.MANUAL]
        teach_choice = Strategy(
            st.selectbox("Estrategia de Qc", teach_options, index=3, format_func=lambda v: STRATEGY_UI[Strategy(v)])
        )
        teach = STRATS[teach_choice]
    t = hour - 1
    qc_t = float(teach.q_c_profile_kvar[t])
    with cB:
        st.markdown(
            f"**Hora {hour}:** P₁ = {D.p1_kw[t]:g} kW (fp {D.pf1[t]:.2f}), P₂ = {D.p2_kw[t]:g} kW (fp {D.pf2[t]:.2f}) · "
            f"Qc(t) = **{qc_t:.2f} kvar** · |Vgen| = **{teach.v_gen_mag[t]:,.2f} V**"
        )
        if teach.violation_v[t] == 0:
            st.badge("Dentro de banda", icon=":material/check_circle:", color="green")
        else:
            st.badge(f"Fuera de banda por {teach.violation_v[t]:,.1f} V", icon=":material/warning:", color="red")
    g1, g2 = st.columns(2)
    plot(g1, CH.fig_power_triangle(float(D.p_total_kw[t]), float(D.q_total_kvar[t]), qc_t))
    plot(g2, CH.fig_phasor_diagram(teach.circuit, P, D, t))
    st.caption(
        "Las corrientes se dibujan escaladas (V/A indicado en la leyenda). Arcos verdes: |V| = 950 V y 1100 V. "
        "Con corriente en atraso, la caída jI·X (900 Ω) suma en fase con V₀ y eleva |Vgen|; con corriente en "
        "adelanto (sobrecompensación) la caída gira y |Vgen| regresa a la banda."
    )
    with st.expander("Animación de las 24 horas (reproducir / pausa)", icon=":material/play_circle:"):
        plot(st, CH.fig_phasor_animation(teach.circuit, P, D))

    st.markdown("#### :material/calculate: Cálculo algebraico paso a paso (método de clase)")
    phase = st.radio(
        "Desarrollo",
        ["Fase 1 — Problema 1 (red directa)", "Fase 2 — Problema 2 (T1, T2 y banco Qc)"],
        index=1,
        horizontal=True,
        key="teach_phase",
    )
    phase2 = phase.startswith("Fase 2")
    c = teach.circuit if phase2 else B.problem1
    q1, q2 = D.q1_kvar[t], D.q2_kvar[t]
    s_load = complex(D.s_total_kva[t])
    s_net = complex(c.s_load_kva[t])
    qc_eq = qc_t if phase2 else 0.0
    pf_txt, pf_lag = CH.pf_label(s_net)
    s_gen_vi = c.v_gen[t] * np.conj(c.i_gen[t]) / 1000
    s_sum = s_net + abs(c.i_line[t]) ** 2 * P.z_line / 1000 + abs(c.i_gen[t]) ** 2 * P.r_gen / 1000
    bal_err = abs(s_gen_vi - s_sum) / abs(s_gen_vi)
    head = [
        (
            r"1. Potencias reactivas de la Tabla 1 (cargas en atraso)",
            rf"Q_1 = P_1\tan(\cos^{{-1}}{D.pf1[t]:.2f}) = {D.p1_kw[t]:g}\cdot{np.tan(np.arccos(D.pf1[t])):.6f}"
            rf" = {q1:.4f}\ \text{{kvar}},\quad Q_2 = {D.p2_kw[t]:g}\cdot{np.tan(np.arccos(D.pf2[t])):.6f} = {q2:.4f}"
            r"\ \text{kvar}",
        ),
        (
            r"2. Potencia de la carga (L1 + L2)",
            rf"S_{{carga}} = ({D.p1_kw[t]:g} + {D.p2_kw[t]:g}) + j({q1:.4f} + {q2:.4f}) = {fc(s_load, 4, KVA)}",
        ),
        (
            r"3. Flujo neto en la barra de 120 V",
            rf"S_{{neto}} = P_{{tot}} + j(Q_{{tot}} - Q_C) = {D.p_total_kw[t]:g} + j({q1 + q2:.4f} - {qc_eq:.4f})"
            rf" = {fc(s_net, 4, KVA)}",
        ),
        (
            r"4. Factor de potencia neto",
            rf"fp_{{neto}} = \frac{{P}}{{|S_{{neto}}|}} = \frac{{{s_net.real:.4f}}}{{{abs(s_net):.4f}}} = "
            rf"{abs(s_net.real) / abs(s_net):.6f}\ \text{{{'(atraso)' if pf_lag else '(adelanto)'}}}",
        ),
        (
            r"5. Corriente de carga (120 V)",
            rf"I_{{load}} = \left(\frac{{S_{{neto}}\cdot 1000}}{{120\angle 0^\circ}}\right)^* = {fc(c.i_load[t], 4, 'A')}",
        ),
    ]
    if phase2:
        body = [
            (
                r"6. Corriente de línea (T2 reductor, a₂ = 110)",
                rf"I_{{line}} = \frac{{I_{{load}}}}{{110}} = {fc(c.i_line[t], 6, 'A')}",
            ),
            (
                r"7. Corriente del generador (T1 elevador, n₁ = 13.2)",
                rf"I_{{gen}} = 13.2\,I_{{line}} = {fc(c.i_gen[t], 4, 'A')}",
            ),
            (
                r"8. Tensión de envío de la línea",
                rf"V_{{envío}} = 120\cdot110\angle0^\circ + I_{{line}}(80+j900) = {fc(c.v_line_send[t], 3, 'V')}",
            ),
            (r"9. Primario de T1", rf"V_{{T1,prim}} = \frac{{V_{{envío}}}}{{13.2}} = {fc(c.v_t1_primary[t], 3, 'V')}"),
            (r"10. Tensión del generador", rf"V_{{gen}} = V_{{T1,prim}} + 0.5\,I_{{gen}} = {fc(c.v_gen[t], 3, 'V')}"),
            (
                r"11. Pérdidas en la línea y en el generador",
                rf"P_{{loss,line}} = \frac{{|I_{{line}}|^2\cdot 80}}{{1000}} = {c.p_loss_line_kw[t]:.6f}\ \text{{kW}},\quad"
                rf" P_{{loss,gen}} = \frac{{|I_{{gen}}|^2\cdot 0.5}}{{1000}} = {c.p_loss_gen_kw[t]:.6f}\ \text{{kW}}",
            ),
            (
                r"12. Pérdidas totales (R_eq = 80 + 0.5·13.2² = 167.12 Ω)",
                rf"P_{{loss,total}} = {c.p_loss_line_kw[t]:.6f} + {c.p_loss_gen_kw[t]:.6f} = {c.p_loss_kw[t]:.6f}\ "
                rf"\text{{kW}} = \frac{{|I_{{line}}|^2\cdot 167.12}}{{1000}}",
            ),
        ]
    else:
        body = [
            (r"6. Sin transformadores", rf"I_{{line}} = I_{{gen}} = I_{{load}} = {fc(c.i_line[t], 4, 'A')}"),
            (
                r"7. Tensión de envío de la línea",
                rf"V_{{envío}} = 120\angle0^\circ + I_{{line}}(80+j900) = {fc(c.v_line_send[t], 3, 'V')}",
            ),
            (r"8. Tensión del generador", rf"V_{{gen}} = V_{{envío}} + 0.5\,I_{{gen}} = {fc(c.v_gen[t], 3, 'V')}"),
            (
                r"9. Pérdidas en la línea y en el generador",
                rf"P_{{loss,line}} = \frac{{|I|^2\cdot 80}}{{1000}} = {c.p_loss_line_kw[t]:.4f}\ \text{{kW}},\quad"
                rf" P_{{loss,gen}} = \frac{{|I|^2\cdot 0.5}}{{1000}} = {c.p_loss_gen_kw[t]:.4f}\ \text{{kW}}",
            ),
            (
                r"10. Pérdidas totales",
                rf"P_{{loss,total}} = {c.p_loss_kw[t]:.4f}\ \text{{kW}},\quad Q_{{loss}} = \frac{{|I|^2\cdot 900}}{{1000}}"
                rf" = {c.q_loss_kvar[t]:.4f}\ \text{{kvar}}",
            ),
        ]
    tail = [
        (
            f"{len(head) + len(body) + 1}. Verificación de conservación de potencia compleja",
            rf"V_{{gen}}I_{{gen}}^* = {fc(s_gen_vi, 4, KVA)}\;=\;S_{{neto}} + S_{{loss,line}} + S_{{loss,gen}}"
            rf"\quad(\varepsilon_{{rel}} = {bal_err:.1e})",
        ),
    ]
    for title, eq in [*head, *body, *tail]:
        st.markdown(f"**{title}**")
        st.latex(r"\begin{gathered}" + eq + r"\end{gathered}")
    if phase2:
        ok = teach.violation_v[t] == 0
        st.markdown(f"**Verificación:** $950 \\le |V_{{gen}}| = {abs(c.v_gen[t]):,.3f} \\le 1100$")
        if ok:
            st.badge("Cumple la restricción de tensión", icon=":material/check_circle:", color="green")
        else:
            st.badge("No cumple la restricción de tensión", icon=":material/warning:", color="red")
        if pf_lag:
            st.badge(f"fp neto {pf_txt}", icon=":material/check_circle:", color="green")
        else:
            st.badge(f"fp neto {pf_txt}", icon=":material/warning:", color="orange")
    else:
        st.markdown(
            f"**Problema 1 (b) — costo diario:** {B.problem1.daily_energy_loss_kwh:,.2f} kWh/día × "
            f"{P.energy_price_cop_per_kwh:g} COP/kWh = **{format_cop(P1_DAILY_COST)}/día**."
        )

# ==================================================================================
# 5. Simulador What-If
# ==================================================================================
with tabs[4]:
    st.subheader("Simulador de presupuesto y sensibilidad")
    s = st.columns(5)
    budget = s[0].number_input("Presupuesto máximo [COP]", 0.0, 200_000_000.0, 30_000_000.0, 1_000_000.0, format="%.0f")
    tariff = s[1].slider("Tarifa [COP/kWh]", 300.0, 2000.0, float(P.energy_price_cop_per_kwh), 10.0)
    cpk = s[2].slider("Costo banco [COP/kvar]", 20_000.0, 400_000.0, float(P.capacitor_cost_cop_per_kvar), 5_000.0)
    x_line = s[3].slider("Reactancia de línea Xline [Ω]", 0.0, 1200.0, float(P.x_line), 5.0, key="x_line")
    horizon = s[4].slider("Horizonte [años]", 1, 10, 5)

    Pw = NetworkParameters(
        z_line=complex(P.r_line, x_line), energy_price_cop_per_kwh=tariff, capacitor_cost_cop_per_kvar=cpk
    )
    feas_w = feasibility_analysis(D, Pw, verify_numerically=False)
    econ_w = fixed_economic_optimum(D, Pw).result
    base_w = econ_w.economics.baseline_daily_loss_kwh
    q_budget = budget / cpk
    q_fixed_budget = min(econ_w.q_c_installed_kvar, q_budget)
    fixed_budget = evaluate_strategy(
        D,
        Pw,
        q_fixed_budget,
        Strategy.FIXED_ECONOMIC,
        label="Fijo económico (limitado por presupuesto)",
        baseline_daily_loss_kwh=base_w,
    )
    try:
        sw_w = ui_result(switched_capacitor_bank(D, Pw, step_kvar=step, feasibility=feas_w).result)
    except (ValueError, RuntimeError):
        sw_w = None

    c = st.columns(4)
    c[0].metric(
        "Banco fijo factible 24 h",
        "Sí" if feas_w.is_feasible else "No",
        f"Ventana {format_set(feas_w.global_set)}" if feas_w.is_feasible else f"Par crítico {feas_w.critical_pair}",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[1].metric(
        "Qc* económico",
        f"{econ_w.q_c_installed_kvar:.2f} kvar",
        f"Presupuesto permite {q_budget:,.1f} kvar",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    if sw_w is not None:
        c[2].metric(
            "Banco automático",
            f"{sw_w.q_c_installed_kvar:g} kvar",
            "Dentro del presupuesto" if sw_w.economics.capex_cop <= budget else "Excede el presupuesto",
            border=True,
            height="stretch",
            **NEUTRAL,
        )
        c[3].metric(
            "Payback banco automático",
            f"{format_number(sw_w.economics.payback_days, 0)} días",
            f"{format_number(sw_w.economics.payback_months, 1)} meses",
            border=True,
            height="stretch",
            **NEUTRAL,
        )
    else:
        c[2].metric(
            "Banco automático", "Infactible", "Alguna hora sin Qc válido", border=True, height="stretch", **NEUTRAL
        )
        c[3].metric("Payback banco automático", "—", "No aplica", border=True, height="stretch", **NEUTRAL)

    if feas_w.is_feasible:
        q_unc = econ_w.q_c_installed_kvar
        q_feas = min(
            (iv.clip(q_unc) for iv in feas_w.global_set), key=lambda q: float(total_annual_cost_fixed(q, D, Pw))
        )
        st.success(
            f"Con Xline = {x_line:g} Ω un banco **fijo** de {q_feas:.2f} kvar cumple la banda las 24 h "
            f"(ventana común {format_set(feas_w.global_set)}).",
            icon=":material/check_circle:",
        )
    else:
        st.warning(
            f"Con Xline = {x_line:g} Ω no existe Qc fijo que cumpla [950, 1100] V las 24 h.",
            icon=":material/warning:",
        )

    summaries = {fixed_budget.label: (fixed_budget.economics, T.SERIES[1])}
    if sw_w is not None:
        summaries[sw_w.label] = (sw_w.economics, T.SERIES[2])
    plot(st, CH.fig_cash_flow(summaries, horizon, budget))

    rows = []
    for name, (summ, _) in summaries.items():
        rows.append(
            {
                "Estrategia": name,
                "CAPEX": format_cop(summ.capex_cop),
                "Ahorro anual": format_cop(summ.annual_savings_cop),
                "Payback [días]": format_number(summ.payback_days, 1),
                f"Flujo neto a {horizon} años": format_cop(summ.annual_savings_cop * horizon - summ.capex_cop),
                f"ROI {horizon} años": f"{format_number(summ.roi_pct(horizon), 1)} %",
                "¿Cabe en presupuesto?": "Sí" if summ.capex_cop <= budget else "No",
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    sens = load_sensitivity(P.r_line, P.r_gen)
    plot(st, CH.fig_reactance_scan(sens.scan, x_line, sens.x_critical_upper))
    st.caption(
        f"Rangos de Xline con banco fijo factible: {format_set(sens.feasible_ranges)} Ω "
        "(barrido cada 5 Ω + bisección exacta de las transiciones)."
    )
