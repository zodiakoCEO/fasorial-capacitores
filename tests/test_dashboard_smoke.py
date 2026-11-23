"""Prueba de humo del dashboard: renderiza todas las pestañas sin excepciones."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.domain.models import Strategy

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(Path(__file__).resolve().parents[1] / "app" / "dashboard.py")


@pytest.fixture(scope="module")
def app():
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    return at


def test_dashboard_renders_without_exceptions(app) -> None:
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.tabs) == 5
    assert len(app.metric) >= 15
    assert any("Hallazgo central" in i.value for i in app.info)


@pytest.mark.parametrize("strategy", [s.value for s in Strategy])
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


LATEX_COMMANDS = {
    "Omega", "angle", "begin", "cdot", "circ", "cos", "end", "frac", "le", "ge", "left", "right",
    "min", "max", "quad", "qquad", "tan", "text", "varepsilon", "mathrm", "approx", "times",
}  # fmt: skip
LATEX_CMD = re.compile(r"\\([A-Za-z]+)")
INLINE_MATH = re.compile(r"\$([^$]+)\$")


def test_latex_commands_are_well_formed(app) -> None:
    """Detecta comandos pegados a texto (p. ej. ``\\quadP``) en todo el LaTeX renderizado, ambas fases."""
    phase = next(r for r in app.radio if r.key == "teach_phase")
    bad: set[str] = set()
    for option in phase.options:
        phase.set_value(option).run()
        sources = [e.value for e in app.latex]
        sources += [m for md in app.markdown for m in INLINE_MATH.findall(md.value)]
        for src in sources:
            bad |= {f"\\{cmd}" for cmd in LATEX_CMD.findall(src) if cmd not in LATEX_COMMANDS}
    assert not bad, f"Comandos LaTeX desconocidos o sin espacio: {sorted(bad)}"


@pytest.mark.parametrize("strategy", [s.value for s in Strategy if s is not Strategy.MANUAL])
def test_circuit_strategy_selector(app, strategy: str) -> None:
    box = next(s for s in app.selectbox if s.key == "diag_strategy")
    box.set_value(strategy).run()
    assert not app.exception, [e.value for e in app.exception]
