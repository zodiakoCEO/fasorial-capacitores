"""Laboratorio educativo interactivo — Streamlit + Plotly.

Ejecutar:  streamlit run app/dashboard.py
"""

from __future__ import annotations

import base64
import re
import sys
from dataclasses import dataclass, replace
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
    FixedEconomicResult,
    ReactanceSensitivity,
    StrategyResult,
    evaluate_strategy,
    feasibility_analysis,
    fixed_economic_optimum,
    format_set,
    line_reactance_sensitivity,
)
from src.optimization.comparison import comparison_table, format_comparison  # noqa: E402
from src.optimization.economics import EconomicSummary, format_cop, format_number  # noqa: E402
from src.optimization.pipeline import AnalysisBundle, run_full_analysis, run_problem_2_1  # noqa: E402
from src.physics.step_by_step import PHASE_1, PHASE_2, PHASE_2_1, algebraic_development  # noqa: E402
from src.reporting import charts as CH  # noqa: E402
from src.reporting import theme as T  # noqa: E402
from src.reporting.analysis_text import (  # noqa: E402
    comparison_synthesis,
    problem1_analysis,
    problem2_analysis,
    problem21_analysis,
)

st.set_page_config(
    page_title="Laboratorio fasorial — Bancos de capacitores", page_icon=":material/bolt:", layout="wide"
)

_BUTTON_ROOTS = (
    '[data-testid="stButton"] button',
    '[data-testid="stFormSubmitButton"] button',
    '[data-testid="stDownloadButton"] button',
    '[data-testid="stLinkButton"] a',
    '[data-testid="stPopover"] button',
)


def _button_selector(suffix: str = "") -> str:
    return ", ".join(root + suffix for root in _BUTTON_ROOTS)


BUTTONS = _button_selector()
BUTTONS_PRIMARY = _button_selector('[kind^="primary"]')
BUTTONS_HOVER = _button_selector(":hover:not(:disabled)")
BUTTONS_ACTIVE = _button_selector(":active:not(:disabled)")
BUTTONS_FOCUS = _button_selector(":focus-visible")
BUTTONS_DISABLED = _button_selector(":disabled")
BUTTONS_CHILDREN = _button_selector(" *")

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
 /* KaTeX deja ~2 px de desborde en cada ecuación centrada y eso hacía aparecer una barra de desplazamiento
    al pasar el cursor; con este margen interno solo aparece si la ecuación de verdad no cabe. */
 [data-testid="stMarkdownContainer"] .katex-display {{ padding: 0 3px; }}

 /* Botones (st.button, st.form_submit_button, st.download_button, st.link_button, st.popover):
    texto, ícono, borde y fondo con alto contraste en todos los estados del tema oscuro. */
 {BUTTONS} {{
   background-color: {T.BUTTON_INK} !important; color: {T.BUTTON_BG} !important;
   border: 1px solid {T.BUTTON_BORDER} !important; opacity: 1 !important;
 }}
 {BUTTONS_PRIMARY} {{
   background-color: {T.BUTTON_BG} !important; color: {T.BUTTON_INK} !important;
   border-color: {T.BUTTON_BG} !important;
 }}
 {BUTTONS_HOVER} {{
   background-color: {T.BUTTON_BG} !important; color: {T.BUTTON_INK} !important;
   border-color: {T.BUTTON_BG} !important;
 }}
 {BUTTONS_ACTIVE} {{
   background-color: #CBD5E1 !important; color: {T.BUTTON_INK} !important; border-color: #CBD5E1 !important;
 }}
 {BUTTONS_FOCUS} {{ outline: 2px solid #38BDF8 !important; outline-offset: 2px; box-shadow: none !important; }}
 {BUTTONS_DISABLED} {{
   background-color: #1E293B !important; color: {T.BUTTON_BORDER} !important;
   border-color: #475569 !important; cursor: not-allowed;
 }}
 {BUTTONS_CHILDREN} {{ color: inherit !important; fill: currentColor !important; }}
</style>
"""
)

PLOT_CFG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 3}}

STRATEGY_UI: dict[Strategy, str] = {
    Strategy.NO_CAPACITOR: "Sin capacitor (Qc = 0)",
    Strategy.FIXED_ECONOMIC: "Banco fijo — óptimo económico",
}
# Únicas dos opciones de los selectores de estrategia del Problema 2.
STRATEGY_OPTIONS: list[str] = [s.value for s in STRATEGY_UI]

# Símbolos con subíndice: "V_gen" → "V<sub>gen</sub>" (Plotly) o "Vgen" (texto plano de widgets).
_SUBSCRIPT = re.compile(r"(?<![A-Za-z0-9])([A-Z])_\{?([A-Za-z0-9]+)\}?")
# Glifos decorativos que las figuras compartidas con el reporte traen y que la UI omite
# (escritos como escapes: check y warning).
_CHECK, _WARN = chr(0x2713), chr(0x26A0)
_GLYPHS = {f"{_CHECK} ": "", f"{_WARN} ": "", _CHECK: "", _WARN: ""}


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


def plot(target: object, fig: go.Figure, key: str | None = None) -> None:
    """Dibuja una figura; ``key`` distingue figuras idénticas que aparecen en más de una pestaña."""
    target.plotly_chart(tidy(fig), width="stretch", config=PLOT_CFG, key=key)  # type: ignore[attr-defined]


def ui_result(r: StrategyResult) -> StrategyResult:
    """Copia de presentación con etiqueta sin guiones bajos (no altera ningún cálculo)."""
    return replace(r, label=STRATEGY_UI[r.strategy])


# ==================================================================================
# Datos y caché
# ==================================================================================
@st.cache_resource(show_spinner="Resolviendo flujos de potencia y optimizaciones…")
def load_bundle() -> AnalysisBundle:
    csv = ROOT / "data" / "demand_profile_24h.csv"
    demand = DemandProfile.from_csv(csv) if csv.exists() else DemandProfile.default()
    return run_full_analysis(demand, include_sensitivity=False)


@st.cache_resource(show_spinner="Resolviendo el Problema 2.1 (línea a 66 kV)…")
def load_bundle_21() -> AnalysisBundle:
    """Problema 2.1: misma demanda y economía, con T1 = 1 kV : 66 kV y T2 = 66 kV : 120 V."""
    return run_problem_2_1(load_bundle().demand)


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


def one_line_diagram(
    circuit_label: str,
    circuit: object,
    t_index: int,
    problem2: bool,
    params: NetworkParameters | None = None,
    title: str | None = None,
) -> None:
    svg = CH.circuit_svg(
        params or P,
        circuit,  # type: ignore[arg-type]
        t_index,
        problem2=problem2,
        font_css=svg_font_css(),
        demand=D,
        title=title,
    )
    st.image(svg, width="stretch", alt=f"Esquema del circuito — {circuit_label}, hora {t_index + 1}")


T1_T2_TEXT = (
    "**T1 — Transformador elevador (1 kV : 13.2 kV, n₁ = 13.2).** Ubicado a la salida del generador; eleva la "
    "tensión para transportar la potencia con menor corriente y reducir las pérdidas I²R en la línea.\n\n"
    "**T2 — Transformador reductor (13.2 kV : 120 V, a₂ = 110).** Ubicado junto a la barra de carga; reduce la "
    "tensión de 13.2 kV a V₀ = 120∠0° V para alimentar L1 (residencial) y L2 (industrial)."
)


def md(text: str) -> str:
    """Texto seguro para Markdown: escapa el signo de pesos ('$ 1.000' → '\\$ 1.000').

    Streamlit lee ``$…$`` como LaTeX en línea; un párrafo con dos cifras en pesos podría interpretarse como una
    ecuación. Las celdas de las tablas no son Markdown y conservan el signo sin escapar.
    """
    return text.replace("$", r"\$")


def cop_md(value: float, decimals: int = 0) -> str:
    """Valor en pesos para insertarlo en un texto Markdown (título, nota, tooltip o tarjeta)."""
    return md(format_cop(value, decimals))


def cop_millions(value: float) -> str:
    """Valor COP compacto para tarjetas KPI, que admiten Markdown (el valor exacto va en el tooltip)."""
    sign = "-" if value < 0 else ""
    return md(f"{sign}$ {format_number(abs(value) / 1e6, 2)} M")


def payback_text(e: EconomicSummary) -> tuple[str, str]:
    """(valor, nota) del payback; con ahorro nulo o negativo la inversión no se recupera."""
    if e.capex_cop == 0:
        return "—", "Sin inversión"
    if not np.isfinite(e.payback_days):
        return "No se recupera", "Ahorro anual ≤ 0"
    return f"{format_number(e.payback_days, 1)} días", f"{format_number(e.payback_months, 1)} meses"


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
- Banco fijo evaluado: $Q_C = 378.35$ kvar en la barra de 120 V
- **Problema 2.1:** T1 = 1 kV : 66 kV ($n_1 = 66$) y T2 = 66 kV : 120 V ($a_2 = 550$);
  banco fijo de $Q_C = 87.25$ kvar
"""
    )

B = load_bundle()
P = B.params
D = B.demand
ECO = B.economic
QC = ECO.q_c_design_kvar
STRATS = {k: ui_result(v) for k, v in B.strategies.items()}
rec = STRATS[Strategy.FIXED_ECONOMIC]
NO_CAP = STRATS[Strategy.NO_CAPACITOR]
P1_DAILY_COST = B.problem1.daily_energy_loss_kwh * P.energy_price_cop_per_kwh


@dataclass(frozen=True)
class Case:
    """Un caso del Problema 2 (13.2 kV o 66 kV) listo para dibujar con la misma estructura."""

    bundle: AnalysisBundle
    key: str  # prefijo de las claves de los widgets
    strategies: dict[Strategy, StrategyResult]

    @property
    def params(self) -> NetworkParameters:
        return self.bundle.params

    @property
    def eco(self) -> FixedEconomicResult:
        return self.bundle.economic

    @property
    def qc(self) -> float:
        return self.bundle.economic.q_c_design_kvar

    @property
    def rec(self) -> StrategyResult:
        return self.strategies[Strategy.FIXED_ECONOMIC]

    @property
    def no_cap(self) -> StrategyResult:
        return self.strategies[Strategy.NO_CAPACITOR]


B21 = load_bundle_21()
P21 = B21.params
CASE2 = Case(B, "p2", STRATS)
CASE21 = Case(B21, "p21", {k: ui_result(v) for k, v in B21.strategies.items()})


def comparison_frame() -> pd.DataFrame:
    """Tabla comparativa (incluye fp neto mín–máx y estado del fp en las 24 h)."""
    table = B.comparison_table()
    return pd.DataFrame(
        {
            "Estrategia": [STRATEGY_UI[s] for s in B.strategies],
            "Qc instalado [kvar]": table["Q_C_instalado_kvar"].round(3),
            "Pérdidas [kWh/día]": table["E_loss_kWh_dia"].round(3),
            "CAPEX": table["CAPEX_COP"].map(format_cop),
            "Costo total anual": table["Costo_total_anual_COP"].map(format_cop),
            "Ahorro anual": table["Ahorro_anual_COP"].map(format_cop),
            "Payback [días]": table["Payback_dias"].map(
                lambda x: "no se recupera" if not np.isfinite(x) else format_number(x, 1)
            ),
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
        ":material/bolt: Problema 2.1 — Línea a 66 kV",
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
    st.subheader(f"Solución evaluada: transformadores + banco fijo de {QC:g} kvar")
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
        "Horas dentro de [950, 1100] V",
        f"{24 - rec.hours_out_of_band} / 24",
        "Fuera: hora " + ", ".join(map(str, ECO.hours_out)) if ECO.hours_out else "Cumple las 24 h",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[3].metric(
        "CAPEX del banco",
        cop_millions(e.capex_cop),
        f"{QC:g} kvar × 100 000 COP",
        help="Valor exacto: " + cop_md(e.capex_cop),
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[4].metric(
        "Ahorro anual vs Qc = 0",
        cop_millions(e.annual_savings_cop),
        f"{-e.loss_reduction_pct:+.1f} % pérdidas",
        help="Valor exacto: " + cop_md(e.annual_savings_cop) + ". Negativo: las pérdidas aumentan.",
        delta_color="inverse",
        border=True,
        height="stretch",
    )
    c[5].metric("Payback", *payback_text(e), border=True, height="stretch", **NEUTRAL)
    b1, b2 = st.columns(2)
    with b1:
        band_badge(rec)
    with b2:
        pf_badge(rec)
    st.caption(
        f"Problema 1 (b): {format_number(p1.daily_energy_loss_kwh, 2)} kWh/día de pérdidas × "
        f"{P.energy_price_cop_per_kwh:g} COP/kWh = **{cop_md(P1_DAILY_COST)} por día** "
        f"({cop_md(P1_DAILY_COST * P.days_per_year)} por año)."
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
    diag_choice = Strategy(
        st.selectbox(
            "Estrategia visualizada en el circuito del Problema 2",
            STRATEGY_OPTIONS,
            index=1,
            format_func=lambda v: STRATEGY_UI[Strategy(v)],
            key="diag_strategy",
        )
    )
    diag = STRATS[diag_choice]
    st.markdown(f"**Problema 2 — {diag.label}** (esquema de la Figura 2 del enunciado)")
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
        f"El máximo alcanzable con un banco fijo es {ECO.band.hours_in_band}/24 h, para Qc en "
        f"{format_set(ECO.band.window)} kvar; {QC:g} kvar es el de menor costo de esa ventana.",
        icon=":material/info:",
    )
    st.warning(
        f"**Observación matemática:** {QC:g} kvar no es el mínimo de J(Qc) = OPEX + CAPEX. Ese mínimo está en "
        f"{ECO.q_c_free_kvar:.2f} kvar ({cop_millions(ECO.free.economics.total_annual_cost_cop)} por año), pero deja "
        f"{ECO.free.hours_out_of_band} h fuera de banda. Con {QC:g} kvar el costo anual es "
        f"{cop_millions(e.total_annual_cost_cop)} "
        f"({e.total_annual_cost_cop / NO_CAP.economics.total_annual_cost_cop:.2f} veces el de Qc = 0): el banco "
        f"sobrecompensa las {rec.hours_leading} h (fp neto en adelanto, {rec.pf_net.min():.3f}–{rec.pf_net.max():.3f}) y "
        f"las pérdidas pasan de {NO_CAP.economics.daily_loss_kwh:,.0f} a {e.daily_loss_kwh:,.0f} kWh/día. "
        "Se justifica por regulación de tensión, no por ahorro de pérdidas.",
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
        help="Valor exacto: " + cop_md(P1_DAILY_COST),
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

    st.markdown("#### :material/insights: Análisis")
    st.markdown("\n".join(f"- {md(line)}" for line in problem1_analysis(B)))


# ==================================================================================
# 3. Problema 2 y Problema 2.1 (misma estructura; solo cambian T1 y T2)
# ==================================================================================
PHASOR_CASES = {CASE2.key: CASE2, CASE21.key: CASE21}


@st.cache_resource(show_spinner=False)
def animation_figure(case_key: str, strategy: str) -> go.Figure:
    """Animación fasorial de 24 h de un caso y una estrategia (se construye una sola vez por combinación)."""
    case = PHASOR_CASES[case_key]
    sel = case.strategies[Strategy(strategy)]
    return tidy(CH.fig_phasor_animation(sel.circuit, case.params, D))


def phasor_caption(prm: NetworkParameters) -> str:
    """Cómo leer el diagrama fasorial de un caso (línea a 13.2 kV o a 66 kV)."""
    z = prm.z_line / prm.n1**2
    v_ref = abs(prm.v_load_gen_side)
    common = (
        f"Fasores referidos al generador ({prm.t1_primary_v / 1000:g} kV): Vgen = V₀·a₂/n₁ + I·(Req + jX)/n₁, con "
        f"V₀·a₂/n₁ = {v_ref:.0f}∠0° V. Las corrientes se dibujan escaladas (factor V/A en la leyenda) y los círculos "
        f"verdes son |V| = {prm.v_gen_min:g} V y {prm.v_gen_max:g} V. A {prm.line_kv:g} kV la línea se ve desde el "
        f"generador como {z.real:.4f} + j{z.imag:.4f} Ω: "
    )
    if z.imag > prm.r_gen + z.real:
        return common + (
            "domina la reactancia, así que con corriente en atraso la caída jI·X tiene una componente grande en fase "
            "con V₀ y eleva |Vgen|; con corriente en adelanto (sobrecompensación) esa caída gira y |Vgen| vuelve a "
            "la banda."
        )
    return common + (
        f"las caídas son pequeñas frente a {v_ref:.0f} V y domina la resistiva en Rgen = {prm.r_gen:g} Ω; por eso el "
        f"panel inferior amplía la punta de V₀, donde se ve si Vgen cruza el círculo de {prm.v_gen_max:g} V."
    )


def hour_header(case: Case, sel: StrategyResult, t: int) -> None:
    """Datos de la hora ``t`` (0-based) de un caso y una estrategia, con el estado de la banda de tensión."""
    st.markdown(
        f"**{case.bundle.title} · hora {t + 1}:** P₁ = {D.p1_kw[t]:g} kW (fp {D.pf1[t]:.2f}), "
        f"P₂ = {D.p2_kw[t]:g} kW (fp {D.pf2[t]:.2f}) · Qc(t) = **{sel.q_c_profile_kvar[t]:.2f} kvar** · "
        f"|Vgen| = **{sel.v_gen_mag[t]:,.2f} V**"
    )
    if sel.violation_v[t] <= 1e-6:
        st.badge("Dentro de banda", icon=":material/check_circle:", color="green")
    else:
        st.badge(f"Fuera de banda por {sel.violation_v[t]:,.1f} V", icon=":material/warning:", color="red")


def phasor_block(case: Case, sel: StrategyResult, t: int, key: str) -> None:
    """Triángulo de potencias y diagrama fasorial de la hora ``t`` más la animación de las 24 h.

    Es el mismo bloque en el Modo docente y en las pestañas de los Problemas 2 y 2.1; ``key`` distingue los
    elementos de cada pestaña.
    """
    prm = case.params
    phasor = CH.fig_phasor_diagram(sel.circuit, prm, D, t)
    triangle = CH.fig_power_triangle(
        float(D.p_total_kw[t]),
        float(D.q_total_kvar[t]),
        float(sel.q_c_profile_kvar[t]),
        height=int(phasor.layout.height),
        p_day=D.p_total_kw,
        q_day=D.q_total_kvar,
    )
    g1, g2 = st.columns(2)
    plot(g1, triangle, key=f"{key}_triangle")
    plot(g2, phasor, key=f"{key}_phasor")
    st.caption(phasor_caption(prm))
    with st.expander("Animación de las 24 horas (reproducir / pausa)", icon=":material/play_circle:"):
        st.plotly_chart(
            animation_figure(case.key, sel.strategy.value),
            width="stretch",
            config=PLOT_CFG,
            key=f"{key}_animation",
        )


def strategy_selector(case: Case) -> StrategyResult:
    """Selector de estrategia (dos opciones), tarjetas KPI y estado de banda / fp del caso."""
    choice = Strategy(
        st.radio(
            "Estrategia",
            STRATEGY_OPTIONS,
            index=1,
            horizontal=True,
            format_func=lambda v: STRATEGY_UI[Strategy(v)],
            key=f"{case.key}_strategy",
        )
    )
    sel = case.strategies[choice]
    e = sel.economics
    c = st.columns(6)
    c[0].metric(
        "Qc instalado", f"{sel.q_c_installed_kvar:,.2f} kvar", "Banco fijo", border=True, height="stretch", **NEUTRAL
    )
    c[1].metric(
        "|Iline| máx",
        f"{np.abs(sel.circuit.i_line).max():.3f} A",
        f"Lado de {case.params.line_kv:g} kV",
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
        help="Valor exacto: " + cop_md(e.total_annual_cost_cop),
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[4].metric(
        "Ahorro anual",
        cop_millions(e.annual_savings_cop),
        "vs Qc = 0",
        help="Valor exacto: " + cop_md(e.annual_savings_cop),
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[5].metric("Payback", *payback_text(e), border=True, height="stretch", **NEUTRAL)
    b1, b2 = st.columns(2)
    with b1:
        band_badge(sel)
    with b2:
        pf_badge(sel)
    return sel


def strategy_charts(case: Case, sel: StrategyResult) -> None:
    """Gráficas, diagnóstico de factibilidad y tabla horaria de la estrategia seleccionada."""
    b, eco, qc, prm = case.bundle, case.eco, case.qc, case.params
    compare = st.checkbox("Superponer 'Sin capacitor' como referencia", value=True, key=f"{case.key}_compare")
    vlist = [case.no_cap, sel] if compare and sel.strategy is not Strategy.NO_CAPACITOR else [sel]
    col1, col2 = st.columns(2)
    plot(col1, CH.fig_vgen_band(vlist, prm))
    series = {r.label: (np.abs(r.circuit.i_line), *CH.strategy_style(r.strategy)) for r in vlist}
    plot(
        col2,
        CH.fig_hourly_metric(
            D.hours,
            series,
            f"Corriente de línea |I_line(t)| ({prm.line_kv:g} kV)",
            "|I_line| [A]",
            "A",
            fmt=".4f",
            height=400,
        ),
    )
    col3, col4 = st.columns(2)
    plot(col3, CH.fig_losses_stacked(sel.circuit, f"P_loss(t) apilada — {sel.label}"))
    pf_series = {r.label: (r.pf_net, *CH.strategy_style(r.strategy)) for r in vlist}
    pf_fig = CH.fig_hourly_metric(
        D.hours, pf_series, "Factor de potencia neto fp_neto(t) en la barra de 120 V", "fp neto", "", fmt=".4f"
    )
    pf_fig.update_yaxes(range=[0, 1.05])
    plot(col4, pf_fig)

    col5, col6 = st.columns(2)
    markers = {f"Banco fijo {qc:g} kvar": (qc, case.rec.economics.total_annual_cost_cop, T.SERIES[1])}
    if abs(eco.q_c_free_kvar - qc) > 10:  # si casi coinciden, un solo marcador evita etiquetas encimadas
        markers["Mínimo libre de J"] = (eco.q_c_free_kvar, eco.free.economics.total_annual_cost_cop, T.SERIES[6])
    plot(col5, CH.fig_cost_curve(b.scan, markers))
    plot(col6, CH.fig_band_hours(b.scan, qc, eco.band.hours_in_band))

    overlays = {sel.label: (sel.q_c_profile_kvar, *CH.strategy_style(sel.strategy))}
    plot(st, CH.fig_feasibility_map(b.feasibility, overlays))
    pairs = ", ".join(map(str, b.feasibility.conflicting_pairs)) or "ninguno"
    free_inside = any(iv.contains(eco.q_c_free_kvar) for iv in eco.band.window)
    choice_txt = (
        "El mínimo libre de $J$ está dentro de esa ventana, así que es el banco de menor costo que cumple"
        if free_inside
        else "El mínimo libre de $J$ queda fuera de esa ventana; como $J$ es convexa, el de menor costo dentro de ella "
        f"es su extremo más cercano, {eco.q_c_band_optimum_kvar:.4f} kvar"
    )
    with st.expander("Detalle del diagnóstico de factibilidad y del valor de Qc", icon=":material/functions:"):
        st.markdown(
            rf"""
$|V_{{gen}}(t,Q_C)|^2 = a\,Q_C^2 + b(t)\,Q_C + c(t)$ (parábola convexa) ⇒ cada hora tiene 1 o 2 intervalos factibles,
resueltos en forma cerrada y verificados con malla + `brentq` (desviación máx.
{b.feasibility.max_numeric_deviation_kvar:.2e} kvar). Intersección de las 24 h: **{format_set(b.feasibility.global_set)}**.
Pares de horas en conflicto: {pairs}.

Máximo de horas en banda con un banco fijo: **{eco.band.hours_in_band}/24**, para $Q_C \in$
{format_set(eco.band.window)} kvar. Mínimo libre de $J$ (sin exigir tensión): {eco.q_c_free_kvar:.4f} kvar (forma cerrada)
= {eco.q_c_free_numeric_kvar:.4f} kvar (numérico). {choice_txt}; se adopta **{qc:g} kvar**
($dJ/dQ_C = {eco.derivative_at_design:,.0f}$ COP/kvar en ese punto).
"""
        )
        st.dataframe(
            b.feasibility.to_dataframe()[["hour", "conjunto_analitico", "conjunto_numerico"]].rename(
                columns={
                    "hour": "Hora",
                    "conjunto_analitico": "Conjunto analítico [kvar]",
                    "conjunto_numerico": "Verificación numérica [kvar]",
                }
            ),
            hide_index=True,
            width="stretch",
        )
    with st.expander(f"Tabla horaria — {sel.label}", icon=":material/table:"):
        hourly = sel.circuit.to_dataframe()
        st.dataframe(
            pd.DataFrame(
                {
                    "Hora": hourly["hour"],
                    "P [kW]": hourly["P_load_kW"],
                    "Qneto [kvar]": hourly["Q_load_net_kvar"].round(3),
                    "fp neto": hourly["pf_net"].round(4),
                    "Estado fp": hourly["pf_net_estado"],
                    "|Iline| [A]": hourly["I_line_A"].round(4),
                    "|Igen| [A]": hourly["I_gen_A"].round(3),
                    "|Vgen| [V]": hourly["V_gen_V"].round(3),
                    "En banda": np.where(sel.violation_v <= 1e-6, "sí", "no"),
                    "Pérdidas línea [kW]": hourly["P_loss_line_kW"].round(4),
                    "Pérdidas generador [kW]": hourly["P_loss_gen_kW"].round(4),
                    "Pérdidas [kW]": hourly["P_loss_kW"].round(4),
                    "Qloss [kvar]": hourly["Q_loss_kvar"].round(4),
                    "|Sgen| [kVA]": hourly["S_gen_kVA"].round(3),
                }
            ),
            hide_index=True,
            width="stretch",
        )


def analysis_block(sections: dict[str, list[str]]) -> None:
    for heading, bullets in sections.items():
        st.markdown(f"**{heading}**")
        st.markdown("\n".join(f"- {md(line)}" for line in bullets))


with tabs[2]:
    st.subheader("Problema 2 — Red con transformadores ideales y optimización de Qc")
    sel2 = strategy_selector(CASE2)

    st.markdown("#### :material/architecture: Diagrama fasorial y triángulo de potencias — Problema 2")
    h2 = st.slider("Hora", 1, 24, 12, key="p2_hour")
    hour_header(CASE2, sel2, h2 - 1)
    phasor_block(CASE2, sel2, h2 - 1, key="p2")
    strategy_charts(CASE2, sel2)
    st.markdown(f"#### :material/insights: Análisis — banco fijo de {QC:g} kvar frente a Qc = 0")
    analysis_block(problem2_analysis(B))

with tabs[3]:
    st.subheader("Problema 2.1 — Red con T1 = 1 kV : 66 kV y T2 = 66 kV : 120 V")
    st.caption(
        "Misma red del Problema 2 con otra tensión de línea. No cambian V₀ = 120∠0° V, Rgen = 0.5 Ω, "
        "Zline = 80 + j900 Ω, la demanda de 24 h, la tarifa, el costo del banco ni la banda [950, 1100] V; "
        "todo lo demás se recalcula."
    )
    z_line_ref = P21.z_line / P21.n1**2
    r = st.columns(4)
    r[0].metric("T1 — elevador", "1 kV : 66 kV", f"n₁ = {P21.n1:g}", border=True, height="stretch", **NEUTRAL)
    r[1].metric("T2 — reductor", "66 kV : 120 V", f"a₂ = {P21.a2:g}", border=True, height="stretch", **NEUTRAL)
    r[2].metric(
        "Línea vista por el generador",
        f"{z_line_ref.real:.4f} + j{z_line_ref.imag:.4f} Ω",
        f"Zline / n₁² (a 13.2 kV: {(P.z_line / P.n1**2).real:.4f} + j{(P.z_line / P.n1**2).imag:.4f} Ω)",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    r[3].metric(
        "R total referida a 66 kV",
        f"{P21.r_eq_line_side:,.0f} Ω",
        f"80 + 0.5·{P21.n1:g}² (Rgen referida: {P21.r_gen_line_side:,.0f} Ω)",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    sel21 = strategy_selector(CASE21)

    st.markdown("#### Diagrama del circuito — Problema 2.1")
    h21 = st.slider("Hora", 1, 24, 12, key="p21_hour")
    one_line_diagram(
        "Problema 2.1",
        sel21.circuit,
        h21 - 1,
        problem2=True,
        params=P21,
        title=f"Problema 2.1 — Figura 2 con T1 = {P21.t1_label} y T2 = {P21.t2_label}",
    )
    st.markdown("#### :material/architecture: Diagrama fasorial y triángulo de potencias — Problema 2.1")
    hour_header(CASE21, sel21, h21 - 1)
    phasor_block(CASE21, sel21, h21 - 1, key="p21")
    strategy_charts(CASE21, sel21)

    st.markdown("#### :material/insights: Análisis — Problema 2.1 (línea a 66 kV)")
    analysis_block(problem21_analysis(B21, B))

    st.markdown("#### :material/compare_arrows: Comparación — Problema 2 vs. Problema 2.1")
    st.caption(
        f"Problema 2: T1 = 1 kV : 13.2 kV, T2 = 13.2 kV : 120 V, banco fijo de {QC:g} kvar. "
        f"Problema 2.1: T1 = 1 kV : 66 kV, T2 = 66 kV : 120 V, banco fijo de {CASE21.qc:g} kvar."
    )
    comparison_df = format_comparison(comparison_table(B, B21))
    st.dataframe(comparison_df, hide_index=True, width="stretch", height=36 * (len(comparison_df) + 1))
    name2, name21 = f"Problema 2 — {QC:g} kvar", f"Problema 2.1 — {CASE21.qc:g} kvar"
    rec21 = CASE21.rec
    g1, g2 = st.columns(2)
    plot(g1, CH.fig_compare_vgen({name2: (rec, T.SERIES[1], "solid"), name21: (rec21, T.SERIES[2], "solid")}, P))
    plot(
        g2,
        CH.fig_hourly_metric(
            D.hours,
            {
                name2: (np.abs(rec.circuit.i_line), T.SERIES[1], "solid"),
                name21: (np.abs(rec21.circuit.i_line), T.SERIES[2], "solid"),
            },
            "Corriente de línea |I_line(t)| con banco fijo (escala log)",
            "|I_line| [A]",
            "A",
            fmt=".4f",
            log_y=True,
            height=400,
        ),
    )
    g3, g4 = st.columns(2)
    plot(
        g3,
        CH.fig_hourly_metric(
            D.hours,
            {
                name2: (rec.circuit.p_loss_kw, T.SERIES[1], "solid"),
                name21: (rec21.circuit.p_loss_kw, T.SERIES[2], "solid"),
            },
            "Pérdidas activas P_loss(t) con banco fijo (escala log)",
            "P_loss [kW]",
            "kW",
            fmt=",.3f",
            log_y=True,
            height=400,
        ),
    )
    plot(
        g4,
        CH.fig_compare_daily_losses(
            {
                "P2 · Qc = 0": NO_CAP.circuit,
                f"P2 · {QC:g} kvar": rec.circuit,
                "P2.1 · Qc = 0": CASE21.no_cap.circuit,
                f"P2.1 · {CASE21.qc:g} kvar": rec21.circuit,
            }
        ),
    )
    st.markdown("**Síntesis técnica**")
    st.markdown("\n".join(f"- {md(line)}" for line in comparison_synthesis(B, B21)))

# ==================================================================================
# 4. Modo docente
# ==================================================================================
# Desarrollos disponibles: etiqueta del selector → (fase, caso). La Fase 1 es la red directa y no tiene caso
# con transformadores, así que las gráficas de arriba muestran entonces el Problema 2.
TEACH_PHASES: dict[str, tuple[str, Case | None]] = {
    "Fase 1 — Problema 1 (red directa)": (PHASE_1, None),
    "Fase 2 — Problema 2 (T1, T2 y banco Qc)": (PHASE_2, CASE2),
    f"Fase 2.1 — Problema 2.1 (T1 = {P21.t1_label}, T2 = {P21.t2_label} y banco Qc)": (PHASE_2_1, CASE21),
}

with tabs[4]:
    st.subheader("Laboratorio fasorial paso a paso")
    cA, cB = st.columns([1, 2])
    with cA:
        hour = st.slider("Hora t", 1, 24, 12, key="teach_hour")
        teach_choice = Strategy(
            st.selectbox("Estrategia de Qc", STRATEGY_OPTIONS, index=1, format_func=lambda v: STRATEGY_UI[Strategy(v)])
        )
    t = hour - 1
    # El selector «Desarrollo» está más abajo, junto al cálculo; el encabezado y las gráficas se llenan después
    # de leerlo para que toda la pestaña muestre el mismo caso (Problema 2 o Problema 2.1).
    header_area = cB.container()
    charts_area = st.container()

    st.markdown("#### :material/calculate: Cálculo algebraico paso a paso (método de clase)")
    phase_label = st.radio("Desarrollo", list(TEACH_PHASES), index=1, horizontal=True, key="teach_phase")
    phase, phase_case = TEACH_PHASES[phase_label]
    teach_case = phase_case or CASE2
    teach = teach_case.strategies[teach_choice]
    qc_t = float(teach.q_c_profile_kvar[t])

    with header_area:
        hour_header(teach_case, teach, t)
        if phase_case is None:
            st.caption(
                "La Fase 1 es la red directa a 120 V (sin transformadores ni banco); las gráficas muestran el "
                "Problema 2 con la estrategia elegida."
            )
    with charts_area:
        phasor_block(teach_case, teach, t, key="teach")

    if phase_case is None:
        dev = algebraic_development(D, P, t, direct=True, phase=phase)
    else:
        dev = algebraic_development(D, phase_case.params, t, q_c_kvar=qc_t, phase=phase)
    for step in dev.steps:
        st.markdown(f"**{step.number}. {step.title}**")
        for equation in step.equations:
            st.latex(r"\begin{gathered}" + equation + r"\end{gathered}")
    if dev.direct:
        st.markdown(
            f"**Problema 1 (b) — costo diario:** {B.problem1.daily_energy_loss_kwh:,.2f} kWh/día × "
            f"{P.energy_price_cop_per_kwh:g} COP/kWh = **{cop_md(P1_DAILY_COST)}/día**."
        )
    else:
        pf_txt, pf_lag = CH.pf_label(complex(dev.values["S_neto"]))
        if dev.in_band:
            st.badge("Cumple la restricción de tensión", icon=":material/check_circle:", color="green")
        else:
            st.badge("No cumple la restricción de tensión", icon=":material/warning:", color="red")
        if pf_lag:
            st.badge(f"fp neto {pf_txt}", icon=":material/check_circle:", color="green")
        else:
            st.badge(f"fp neto {pf_txt}", icon=":material/warning:", color="orange")

# ==================================================================================
# 5. Simulador What-If
# ==================================================================================
with tabs[5]:
    st.subheader("Simulador de presupuesto y sensibilidad")
    s = st.columns(5)
    budget = s[0].number_input("Presupuesto máximo [COP]", 0.0, 200_000_000.0, 40_000_000.0, 1_000_000.0, format="%.0f")
    tariff = s[1].slider("Tarifa [COP/kWh]", 300.0, 2000.0, float(P.energy_price_cop_per_kwh), 10.0)
    cpk = s[2].slider("Costo banco [COP/kvar]", 20_000.0, 400_000.0, float(P.capacitor_cost_cop_per_kvar), 5_000.0)
    x_line = s[3].slider("Reactancia de línea Xline [Ω]", 0.0, 1200.0, float(P.x_line), 5.0, key="x_line")
    horizon = s[4].slider("Horizonte [años]", 1, 10, 5)

    Pw = NetworkParameters(
        z_line=complex(P.r_line, x_line), energy_price_cop_per_kwh=tariff, capacitor_cost_cop_per_kvar=cpk
    )
    feas_w = feasibility_analysis(D, Pw, verify_numerically=False)
    eco_w = fixed_economic_optimum(D, Pw, feasibility=feas_w)
    econ_w = eco_w.result
    base_w = econ_w.economics.baseline_daily_loss_kwh
    q_budget = budget / cpk
    limited = q_budget < econ_w.q_c_installed_kvar
    fixed_budget = evaluate_strategy(
        D,
        Pw,
        min(econ_w.q_c_installed_kvar, q_budget),
        Strategy.FIXED_ECONOMIC,
        label="Banco fijo (limitado por presupuesto)" if limited else STRATEGY_UI[Strategy.FIXED_ECONOMIC],
        baseline_daily_loss_kwh=base_w,
    )

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
        "Qc del banco fijo económico",
        f"{econ_w.q_c_installed_kvar:.2f} kvar",
        f"{24 - econ_w.hours_out_of_band}/24 h en banda",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[2].metric(
        "Presupuesto",
        f"{q_budget:,.1f} kvar",
        "No alcanza para el banco" if limited else "Cubre el banco",
        border=True,
        height="stretch",
        **NEUTRAL,
    )
    c[3].metric("Payback", *payback_text(fixed_budget.economics), border=True, height="stretch", **NEUTRAL)

    if feas_w.is_feasible:
        q_feas = econ_w.q_c_installed_kvar
        st.success(
            f"Con Xline = {x_line:g} Ω un banco **fijo** de {q_feas:.2f} kvar cumple la banda las 24 h "
            f"(ventana común {format_set(feas_w.global_set)}).",
            icon=":material/check_circle:",
        )
    else:
        st.warning(
            f"Con Xline = {x_line:g} Ω no existe Qc fijo que cumpla [950, 1100] V las 24 h; el máximo es "
            f"{eco_w.band.hours_in_band}/24 h.",
            icon=":material/warning:",
        )

    summaries = {fixed_budget.label: (fixed_budget.economics, T.SERIES[1])}
    plot(st, CH.fig_cash_flow(summaries, horizon, budget))

    rows = []
    for name, (summ, _) in summaries.items():
        rows.append(
            {
                "Estrategia": name,
                "Qc [kvar]": round(summ.q_c_installed_kvar, 2),
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
