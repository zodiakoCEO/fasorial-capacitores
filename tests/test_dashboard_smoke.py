"""Prueba de humo del dashboard: renderiza todas las pestañas sin excepciones."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.domain.models import Strategy
from tests.latex_util import INLINE_MATH, unknown_commands

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(Path(__file__).resolve().parents[1] / "app" / "dashboard.py")


@pytest.fixture(scope="module")
def app():
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    return at


def test_dashboard_renders_without_exceptions(app) -> None:
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.tabs) == 6
    assert len(app.metric) >= 15
    assert any("Hallazgo central" in i.value for i in app.info)


STRATEGIES = [Strategy.NO_CAPACITOR.value, Strategy.FIXED_ECONOMIC.value]


def test_strategy_selectors_offer_only_two_options(app) -> None:
    labels = ["Sin capacitor (Qc = 0)", "Banco fijo — óptimo económico"]
    radio = app.radio[0]
    assert radio.label == "Estrategia" and list(radio.options) == labels
    boxes = [b for b in app.selectbox if "strategia" in b.label]
    assert len(boxes) == 2
    for box in boxes:
        assert list(box.options) == labels
    source = Path(APP).read_text(encoding="utf-8")
    for removed in ("mínima violación", "automático por pasos", "100 % en atraso", "Manual (Qc"):
        assert removed not in source


def test_analysis_sections(app) -> None:
    blocks = [m.value for m in app.markdown]
    text = "\n".join(blocks)
    assert "Hallazgos físicos automáticos" not in text
    assert "#### :material/insights: Análisis" in blocks  # Problema 1
    assert any(b.startswith("#### :material/insights: Análisis — banco fijo de 378.35 kvar") for b in blocks)
    for heading in ("Tensión del generador |Vgen(t)|", "Corriente de línea |Iline(t)|", "Pérdidas Ploss(t)"):
        assert f"**{heading}**" in blocks


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_every_strategy_renders(app, strategy: str) -> None:
    app.radio[0].set_value(strategy).run()
    assert not app.exception, [e.value for e in app.exception]


def test_what_if_reactance_feasible_region(app) -> None:
    x_slider = next(s for s in app.slider if s.key == "x_line")
    x_slider.set_value(500.0).run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("banco **fijo**" in s.value for s in app.success)


def test_teaching_hour_change(app) -> None:
    hour = next(s for s in app.slider if s.key == "teach_hour")
    hour.set_value(4).run()
    assert not app.exception
    assert len(app.latex) >= 10


_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x25A0, 0x25FF), (0x2300, 0x23FF), (0xFE0F, 0xFE0F))
EMOJI = re.compile("[" + "".join(f"{re.escape(chr(a))}-{re.escape(chr(b))}" for a, b in _RANGES) + "]")


def test_dashboard_source_has_no_emoji() -> None:
    source = Path(APP).read_text(encoding="utf-8")
    found = sorted({m.group() for m in EMOJI.finditer(source)})
    assert not found, f"Emojis/glifos decorativos en dashboard.py: {found}"


def test_teaching_phase_toggle(app) -> None:
    phase = next(r for r in app.radio if r.key == "teach_phase")
    for option in phase.options:
        phase.set_value(option).run()
        assert not app.exception, [e.value for e in app.exception]
        assert len(app.latex) >= 10


def test_latex_commands_are_well_formed(app) -> None:
    """Detecta comandos pegados a texto (p. ej. ``\\quadP``) en todo el LaTeX renderizado, en las tres fases."""
    phase = next(r for r in app.radio if r.key == "teach_phase")
    bad: set[str] = set()
    for option in phase.options:
        phase.set_value(option).run()
        sources = [e.value for e in app.latex]
        sources += [m for md in app.markdown for m in INLINE_MATH.findall(md.value)]
        for src in sources:
            bad |= unknown_commands(src)
    assert not bad, f"Comandos LaTeX desconocidos o sin espacio: {sorted(bad)}"


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_circuit_strategy_selector(app, strategy: str) -> None:
    box = next(s for s in app.selectbox if s.key == "diag_strategy")
    box.set_value(strategy).run()
    assert not app.exception, [e.value for e in app.exception]


def test_problem_2_1_tab_structure(app) -> None:
    """Pestaña 2.1: mismo selector de dos opciones, «Análisis» propio y «Comparación» justo debajo."""
    radio = next(r for r in app.radio if r.key == "p21_strategy")
    assert list(radio.options) == ["Sin capacitor (Qc = 0)", "Banco fijo — óptimo económico"]
    blocks = [m.value for m in app.markdown]
    analysis = blocks.index("#### :material/insights: Análisis — Problema 2.1 (línea a 66 kV)")
    comparison = blocks.index("#### :material/compare_arrows: Comparación — Problema 2 vs. Problema 2.1")
    assert analysis < comparison
    between = blocks[analysis:comparison]
    for heading in ("Efecto de elevar la línea de 13.2 kV a 66 kV", "Banco capacitivo y tensión |Vgen(t)|"):
        assert f"**{heading}**" in between
    assert "**Síntesis técnica**" in blocks[comparison:]
    assert any("Problema 2.1 — Red con T1 = 1 kV : 66 kV y T2 = 66 kV : 120 V" in h.value for h in app.subheader)
    assert any(m.value == "87.25 kvar" for m in app.metric)  # banco recalculado para 2.1
    assert any(m.value == "1 kV : 66 kV" for m in app.metric) and any(m.value == "66 kV : 120 V" for m in app.metric)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_problem_2_1_every_strategy_renders(app, strategy: str) -> None:
    radio = next(r for r in app.radio if r.key == "p21_strategy")
    radio.set_value(strategy).run()
    assert not app.exception, [e.value for e in app.exception]
    hour = next(s for s in app.slider if s.key == "p21_hour")
    hour.set_value(8).run()
    assert not app.exception, [e.value for e in app.exception]


def _luminance(hex_color: str) -> float:
    rgb = [int(hex_color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.fixture(scope="module")
def bundle():
    from src.optimization.pipeline import run_full_analysis

    return run_full_analysis(include_sensitivity=False)


def test_play_pause_buttons_have_high_contrast(bundle) -> None:
    """Reproducir / Pausa: texto oscuro sobre botón claro, legible también en el estado activo y :hover."""
    from src.reporting import charts as CH

    fig = CH.fig_phasor_animation(bundle.economic.result.circuit, bundle.params, bundle.demand)
    menu = fig.layout.updatemenus[0]
    assert [btn.label for btn in menu.buttons] == ["Reproducir", "Pausa"]
    assert menu.showactive is False
    assert _contrast(menu.font.color, menu.bgcolor) >= 7
    assert _contrast(menu.font.color, "#F4FAFF") >= 7  # fondo fijo de Plotly para el botón activo y el :hover


def test_button_css_covers_every_state() -> None:
    source = Path(APP).read_text(encoding="utf-8")
    for state in (":hover:not(:disabled)", ":active:not(:disabled)", ":focus-visible", ":disabled"):
        assert state in source
    assert _contrast("#E2E8F0", "#0F172A") >= 7
    assert _contrast("#0F172A", "#CBD5E1") >= 7  # estado :active
    assert _contrast("#94A3B8", "#1E293B") >= 4.5  # estado :disabled


def test_circuit_diagram_matches_figure_2(bundle) -> None:
    from src.reporting import charts as CH

    b = bundle
    svg = CH.circuit_svg(b.params, b.economic.result.circuit, 11, problem2=True, demand=b.demand)
    for label in ("0.5 Ω", "1kV:13.2kV", "80 Ω", "j900 Ω", "13.2kV:120V", "378.35 kvar", "Figura 2"):
        assert label in svg
    for symbol in ("line", "load", "gen"):  # I_line, I_load y V_gen con subíndice
        assert f">{symbol}</tspan>" in svg
    assert svg.count('r="3.4"') == 4  # dos puntos de polaridad por transformador
    assert "stroke-dasharray" not in svg  # banco activo
    off = CH.circuit_svg(b.params, b.no_capacitor.circuit, 11, problem2=True, demand=b.demand)
    assert "stroke-dasharray" in off and "(inactivo)" in off  # Q_C = 0: rama atenuada
    p1 = CH.circuit_svg(b.params, b.problem1, 11, problem2=False, demand=b.demand)
    assert "1kV:13.2kV" not in p1 and 'r="3.4"' not in p1
    assert _contrast(CH._SVG_WIRE, CH._SVG_CARD) >= 7 and _contrast(CH._SVG_MUTED, CH._SVG_CARD) >= 7
