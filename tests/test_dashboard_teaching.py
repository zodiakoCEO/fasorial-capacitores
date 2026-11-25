"""Modo docente y bloques fasoriales del dashboard: Fase 2.1 (66 kV) y consistencia con el motor de cálculo."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.models import Strategy
from src.optimization.pipeline import run_full_analysis, run_problem_2_1
from tests.latex_util import braces_balanced, markdown_dollar_problems, unknown_commands

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(Path(__file__).resolve().parents[1] / "app" / "dashboard.py")

PHASE_1 = "Fase 1 — Problema 1 (red directa)"
PHASE_2 = "Fase 2 — Problema 2 (T1, T2 y banco Qc)"
PHASE_2_1 = "Fase 2.1 — Problema 2.1 (T1 = 1kV:66kV, T2 = 66kV:120V y banco Qc)"
TITLE_2 = "Problema 2 (1kV:13.2kV / 13.2kV:120V)"
TITLE_2_1 = "Problema 2.1 (1kV:66kV / 66kV:120V)"
ANIMATION = "Animación de las 24 horas (reproducir / pausa)"
FIXED, NO_CAP = Strategy.FIXED_ECONOMIC.value, Strategy.NO_CAPACITOR.value


@pytest.fixture(scope="module")
def app():
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    return at


@pytest.fixture(scope="module")
def b2():
    return run_full_analysis(include_sensitivity=False)


@pytest.fixture(scope="module")
def b21():
    return run_problem_2_1()


def tex(x: float, d: int) -> str:
    """Número como lo escribe el desarrollo: decimales fijos y separador de miles fino."""
    return f"{round(x, d) + 0.0:,.{d}f}".replace(",", r"\,")


def select(app, phase: str, hour: int = 12, strategy: str = FIXED) -> str:
    """Fija desarrollo, hora y estrategia del Modo docente y devuelve todo el LaTeX renderizado."""
    next(r for r in app.radio if r.key == "teach_phase").set_value(phase)
    next(s for s in app.slider if s.key == "teach_hour").set_value(hour)
    next(s for s in app.selectbox if s.label == "Estrategia de Qc").set_value(strategy)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return "\n".join(equations(app))


def markdown(app) -> list[str]:
    return [m.value for m in app.markdown]


def equations(app) -> list[str]:
    """Ecuaciones mostradas con ``st.latex``, sin los delimitadores ``$$`` que les añade Streamlit."""
    return [e.value.strip().removeprefix("$$").removesuffix("$$").strip() for e in app.latex]


# ----------------------------------------------------------------------------------
# Selector «Desarrollo»
# ----------------------------------------------------------------------------------
def test_development_selector_offers_three_phases(app) -> None:
    phase = next(r for r in app.radio if r.key == "teach_phase")
    assert phase.label == "Desarrollo"
    assert list(phase.options) == [PHASE_1, PHASE_2, PHASE_2_1]
    assert phase.value == PHASE_2  # la Fase 2 sigue siendo la opción inicial
    assert "1kV:66kV" in PHASE_2_1 and "66kV:120V" in PHASE_2_1


@pytest.mark.parametrize("phase", [PHASE_1, PHASE_2, PHASE_2_1])
def test_every_phase_renders_eight_numbered_steps(app, phase: str) -> None:
    select(app, phase)
    steps = [m for m in markdown(app) if m.startswith("**") and m[2:4] in {f"{n}." for n in range(1, 9)}]
    assert [s[2] for s in steps] == list("12345678"), steps
    assert steps[7] == "**8. Potencias y pérdidas (línea, generador y totales)**"
    assert len(app.latex) >= 14
    for equation in equations(app):  # mismo formato en las tres fases: bloque centrado ``gathered``
        assert equation.startswith(r"\begin{gathered}") and equation.endswith(r"\end{gathered}")
        assert not unknown_commands(equation), unknown_commands(equation)
        assert braces_balanced(equation)


# ----------------------------------------------------------------------------------
# Fase 2.1 — T1 = 1kV:66kV, T2 = 66kV:120V
# ----------------------------------------------------------------------------------
def test_phase_2_1_shows_66kv_development(app) -> None:
    latex = select(app, PHASE_2_1)
    blocks = markdown(app)
    for title in (
        "**3. Flujo neto en la barra de 120 V**",
        "**6. Relaciones de transformación y reflejo a la línea de 66 kV**",
        "**7. Caída de tensión en línea, tensión en el lado de 66 kV y tensión referida del generador Vgen**",
    ):
        assert title in blocks, title
    for token in (
        r"\text{T2 reductor (66 kV : 120 V):}\quad a_2 = \frac{66\,000}{120} = 550",
        r"\text{T1 elevador (1 kV : 66 kV):}\quad a_1 = \frac{1\,000}{66\,000} = \frac{1}{66}",
        r"I_{line} = \frac{I_{load}}{a_2} = \frac{I_{load}}{550}",
        r"Z_{line} = 80 + j900\;\Omega",
        r"\text{(en el nivel de 66 kV; la línea no se refleja)}",
        r"V_{rec} = a_2\,V_0 = 550\cdot 120\angle 0^\circ = 66\,000\angle 0^\circ\;\text{V}",
        r"S_{neto} = P_{tot} + j(Q_{tot} - Q_C) = 165 + j(157.2707 - 87.2500)",
        r"950 \le |V_{gen}| = 1\,099.9996\;\text{V} \le 1100",
    ):
        assert token in latex, token
    assert "13.2" not in latex and "110" not in latex.replace("1100", "").replace("1\\,100", "")
    header = next(m for m in blocks if m.startswith(f"**{TITLE_2_1} · hora 12:**"))
    assert "Qc(t) = **87.25 kvar**" in header and "|Vgen| = **1,100.00 V**" in header
    assert any("Cumple la restricción de tensión" in m for m in blocks)
    assert any("fp neto 0.921 (en atraso)" in m for m in blocks)


@pytest.mark.parametrize("strategy", [FIXED, NO_CAP])
@pytest.mark.parametrize("hour", [4, 8, 12, 19])
def test_phase_2_1_numbers_match_engine(app, b21, hour: int, strategy: str) -> None:
    """Cada cifra del desarrollo de la Fase 2.1 es la del motor del Problema 2.1 para esa hora y ese Q_C."""
    latex = select(app, PHASE_2_1, hour, strategy)
    result = b21.strategies[Strategy(strategy)]
    c, t = result.circuit, hour - 1
    q_c = float(result.q_c_profile_kvar[t])
    assert q_c == (87.25 if strategy == FIXED else 0.0)
    expected = {
        "Q_C": rf"- {tex(q_c, 4)})",
        "|S_neto|": tex(abs(c.s_load_kva[t]), 4),
        "fp_neto": f"{c.pf_net[t]:.6f}",
        "|I_load|": tex(abs(c.i_load[t]), 4),
        "|I_line|": tex(abs(c.i_line[t]), 6),
        "|I_gen|": tex(abs(c.i_gen[t]), 4),
        "|V_envío|": tex(abs(c.v_line_send[t]), 3),
        "|V_T1,prim|": tex(abs(c.v_t1_primary[t]), 3),
        "|V_gen|": tex(abs(c.v_gen[t]), 4),
        "P_loss,línea": rf"= {tex(c.p_loss_line_kw[t], 6)}\ \text{{kW}}",
        "P_loss,gen": rf"= {tex(c.p_loss_gen_kw[t], 6)}\ \text{{kW}}",
        "Q_loss,línea": rf"= {tex(c.q_loss_kvar[t], 6)}\ \text{{kvar}}",
        "|S_gen|": tex(abs(c.s_gen_kva[t]), 4),
    }
    for name, token in expected.items():
        assert token in latex, (name, token)
    inside = result.violation_v[t] <= 1e-6
    assert ("dentro de la banda" in latex) == inside
    blocks = markdown(app)
    badge = "Cumple la restricción de tensión" if inside else "No cumple la restricción de tensión"
    assert any(badge in m and not ("No cumple" in m and inside) for m in blocks)
    state = "adelanto" if c.leading_mask[t] else "atraso"
    assert rf"\text{{({state})}}" in latex
    # el encabezado del Modo docente (la pestaña 2.1 tiene el suyo, con su propia hora y estrategia)
    headers = [m for m in blocks if m.startswith(f"**{TITLE_2_1} · hora {hour}:**")]
    assert any(f"Qc(t) = **{q_c:.2f} kvar**" in h and f"|Vgen| = **{abs(c.v_gen[t]):,.2f} V**" in h for h in headers)


# ----------------------------------------------------------------------------------
# Fases 1 y 2: mismo formato, con sus propias relaciones
# ----------------------------------------------------------------------------------
def test_phase_2_keeps_13_2kv_relations(app, b2) -> None:
    latex = select(app, PHASE_2)
    blocks = markdown(app)
    assert "**6. Relaciones de transformación y reflejo a la línea de 13.2 kV**" in blocks
    c = b2.economic.result.circuit
    for token in (
        r"a_2 = \frac{13\,200}{120} = 110",
        r"a_1 = \frac{1\,000}{13\,200} = \frac{1}{13.2} = 0.075758",
        r"S_{neto} = P_{tot} + j(Q_{tot} - Q_C) = 165 + j(157.2707 - 378.3500)",
        r"275.8642\angle{-53.2646}^\circ\;\text{kVA}",  # ángulo negativo sin espacio de resta
        tex(abs(c.v_gen[11]), 4),
        tex(abs(c.i_line[11]), 6),
        rf"= {tex(c.p_loss_line_kw[11], 6)}\ \text{{kW}}",
    ):
        assert token in latex, token
    assert any(m.startswith(f"**{TITLE_2} · hora 12:**") and "378.35 kvar" in m for m in blocks)
    assert any("fp neto 0.598 (en adelanto — sobrecompensado)" in m for m in blocks)


def test_phase_1_is_the_direct_network(app, b2) -> None:
    latex = select(app, PHASE_1)
    blocks = markdown(app)
    assert "**6. Red directa a 120 V: sin transformadores**" in blocks
    assert "**7. Caída de tensión en línea y tensión del generador Vgen**" in blocks
    p1 = b2.problem1
    for token in (
        r"a_1 = a_2 = 1",
        tex(abs(p1.i_line[11]), 4),
        tex(abs(p1.v_gen[11]), 3),
        rf"= {tex(p1.p_loss_line_kw[11], 4)}\ \text{{kW}}",
        r"(157.2707 - 0.0000)",
    ):
        assert token in latex, token
    assert r"\le 1100" not in latex  # la banda de tensión es del Problema 2
    cost = next(m for m in blocks if m.startswith("**Problema 1 (b) — costo diario:**"))
    assert r"\$ 3.537.020.594 COP" in cost
    assert any("La Fase 1 es la red directa" in c.value for c in app.caption)


def test_header_and_charts_follow_the_selected_development(app) -> None:
    select(app, PHASE_2)
    captions = [c.value for c in app.caption]
    assert any("A 13.2 kV la línea se ve desde el generador como 0.4591 + j5.1653 Ω" in c for c in captions)
    select(app, PHASE_2_1)
    captions = [c.value for c in app.caption]
    assert any("A 66 kV la línea se ve desde el generador como 0.0184 + j0.2066 Ω" in c for c in captions)
    assert sum(m.startswith(f"**{TITLE_2_1} · hora") for m in markdown(app)) == 2  # Modo docente y pestaña 2.1


# ----------------------------------------------------------------------------------
# Diagrama fasorial en las pestañas de los Problemas 2 y 2.1
# ----------------------------------------------------------------------------------
def test_phasor_block_is_in_both_problem_tabs_and_teaching_mode(app) -> None:
    select(app, PHASE_2)
    blocks = markdown(app)
    assert "#### :material/architecture: Diagrama fasorial y triángulo de potencias — Problema 2" in blocks
    assert "#### :material/architecture: Diagrama fasorial y triángulo de potencias — Problema 2.1" in blocks
    assert [e.label for e in app.expander].count(ANIMATION) == 3
    assert {"teach_hour", "p2_hour", "p21_hour"} <= {s.key for s in app.slider}
    assert sum(m.startswith(f"**{TITLE_2} · hora 12:**") for m in blocks) == 2  # pestaña 2 y Modo docente
    assert sum(m.startswith(f"**{TITLE_2_1} · hora 12:**") for m in blocks) == 1  # pestaña 2.1


def test_problem_tabs_have_their_own_hour(app, b2, b21) -> None:
    select(app, PHASE_2)
    next(s for s in app.slider if s.key == "p2_hour").set_value(8)
    next(s for s in app.slider if s.key == "p21_hour").set_value(19)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    blocks = markdown(app)
    v2 = abs(b2.economic.result.circuit.v_gen[7])
    v21 = abs(b21.economic.result.circuit.v_gen[18])
    h2 = next(m for m in blocks if m.startswith(f"**{TITLE_2} · hora 8:**"))
    assert f"|Vgen| = **{v2:,.2f} V**" in h2 and "378.35 kvar" in h2
    h21 = next(m for m in blocks if m.startswith(f"**{TITLE_2_1} · hora 19:**"))
    assert f"|Vgen| = **{v21:,.2f} V**" in h21 and "87.25 kvar" in h21
    assert any("Fuera de banda por 111.2 V" in m for m in blocks)  # hora 8 del Problema 2
    assert any(m.startswith(f"**{TITLE_2} · hora 12:**") for m in blocks)  # el Modo docente conserva su hora


# ----------------------------------------------------------------------------------
# Higiene de Markdown: signos de pesos escapados y LaTeX en línea bien formado
# ----------------------------------------------------------------------------------
@pytest.mark.parametrize("phase", [PHASE_1, PHASE_2, PHASE_2_1])
def test_markdown_has_no_unescaped_currency(app, phase: str) -> None:
    select(app, phase)
    texts = [m.value for m in app.markdown] + [c.value for c in app.caption]
    texts += [e.value for group in (app.info, app.warning, app.success) for e in group]
    for metric in app.metric:
        texts += [str(metric.value), str(metric.label), str(getattr(metric, "help", "") or "")]
    problems = {text[:90]: found for text in texts if (found := markdown_dollar_problems(text))}
    assert not problems, problems
    assert sum(r"\$" in text for text in texts) >= 10  # las cifras en pesos siguen ahí, ya escapadas
    assert all("$" not in equation for equation in equations(app))
