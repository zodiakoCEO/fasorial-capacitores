"""Desarrollo algebraico paso a paso (Modo docente): Fase 1, Fase 2 y Fase 2.1 frente al motor de cálculo."""

from __future__ import annotations

import cmath
import math

import numpy as np
import pytest

from src.domain.constants import QC_FIXED_ECONOMIC_2_1_KVAR, QC_FIXED_ECONOMIC_KVAR
from src.domain.models import DemandProfile, NetworkParameters
from src.optimization.pipeline import params_2_1
from src.physics.circuit_solver import solve_problem1, solve_problem2
from src.physics.step_by_step import (
    PHASE_1,
    PHASE_2,
    PHASE_2_1,
    AlgebraDevelopment,
    algebraic_development,
)
from tests.latex_util import braces_balanced, unknown_commands

TITLES_1_TO_5 = [
    "Potencias reactivas de la Tabla 1 (cargas en atraso)",
    "Potencia de la carga (L1 + L2)",
    "Flujo neto en la barra de 120 V",
    "Factor de potencia neto",
    "Corriente de carga (120 V)",
]


@pytest.fixture(scope="module")
def demand() -> DemandProfile:
    return DemandProfile.default()


@pytest.fixture(scope="module")
def p2() -> NetworkParameters:
    return NetworkParameters()


@pytest.fixture(scope="module")
def p21() -> NetworkParameters:
    return params_2_1()


def _close(a: complex | float, b: complex | float, rel: float = 1e-12) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b), 1e-300)


def _check_against_solver(dev: AlgebraDevelopment, circuit, t: int) -> None:
    v = dev.values
    pairs = {
        "S_neto": circuit.s_load_kva[t],
        "fp_neto": circuit.pf_net[t],
        "I_load": circuit.i_load[t],
        "I_line": circuit.i_line[t],
        "I_gen": circuit.i_gen[t],
        "V_rec": circuit.v_line_receiving[t],
        "V_envio": circuit.v_line_send[t],
        "V_gen": circuit.v_gen[t],
        "P_loss_linea": circuit.p_loss_line_kw[t],
        "P_loss_gen": circuit.p_loss_gen_kw[t],
        "Q_loss_linea": circuit.q_loss_kvar[t],
        "S_gen": circuit.s_gen_kva[t],
    }
    for name, expected in pairs.items():
        assert _close(v[name], complex(expected)), (dev.phase, dev.hour, name, v[name], expected)


# ----------------------------------------------------------------------------------
# Consistencia numérica con el motor en las 24 horas
# ----------------------------------------------------------------------------------
@pytest.mark.parametrize("t", range(24))
def test_phase_1_matches_solver(demand, p2, t: int) -> None:
    dev = algebraic_development(demand, p2, t, direct=True)
    assert dev.phase == PHASE_1 and dev.direct and dev.in_band is None and dev.q_c_kvar == 0.0
    _check_against_solver(dev, solve_problem1(demand, p2), t)
    assert dev.values["a1"] == dev.values["a2"] == dev.values["n1"] == 1.0
    assert dev.values["I_line"] == dev.values["I_gen"] == dev.values["I_load"]
    assert dev.values["R_eq"] == pytest.approx(80.5)


@pytest.mark.parametrize("q_c", [0.0, QC_FIXED_ECONOMIC_KVAR])
@pytest.mark.parametrize("t", range(24))
def test_phase_2_matches_solver(demand, p2, t: int, q_c: float) -> None:
    dev = algebraic_development(demand, p2, t, q_c_kvar=q_c, phase=PHASE_2)
    circuit = solve_problem2(demand, q_c, p2)
    _check_against_solver(dev, circuit, t)
    assert _close(dev.values["V_T1_prim"], complex(circuit.v_t1_primary[t]))
    assert (dev.values["a2"], dev.values["n1"]) == (pytest.approx(110.0), pytest.approx(13.2))
    assert dev.in_band == (950.0 - 1e-6 <= abs(circuit.v_gen[t]) <= 1100.0 + 1e-6)


@pytest.mark.parametrize("q_c", [0.0, QC_FIXED_ECONOMIC_2_1_KVAR])
@pytest.mark.parametrize("t", range(24))
def test_phase_2_1_matches_engine(demand, p21, t: int, q_c: float) -> None:
    """Fase 2.1 (T1 = 1kV:66kV, T2 = 66kV:120V): cada paso coincide con el motor del Problema 2.1."""
    dev = algebraic_development(demand, p21, t, q_c_kvar=q_c, phase=PHASE_2_1)
    circuit = solve_problem2(demand, q_c, p21)
    _check_against_solver(dev, circuit, t)
    v = dev.values
    assert _close(v["V_T1_prim"], complex(circuit.v_t1_primary[t]))
    assert (v["a2"], v["n1"], v["a1"]) == (pytest.approx(550.0), pytest.approx(66.0), pytest.approx(1 / 66))
    assert _close(v["V_rec"], 66_000.0)
    assert v["R_gen_linea"] == pytest.approx(2178.0) and v["R_eq"] == pytest.approx(2258.0)
    # Las dos rutas de cálculo (tramo a tramo y reflejada al generador) dan la misma V_gen
    assert _close(v["V_gen"], v["V_gen_reflejada"])
    assert _close(v["P_loss_linea"] + v["P_loss_gen"], v["P_loss_tot_Req"])
    assert v["Q_loss_gen"] == 0.0
    assert _close(v["S_neto"] + v["S_loss_tot"], v["S_gen"]) and v["error_conservacion"] < 1e-12
    assert dev.in_band == (950.0 - 1e-6 <= abs(circuit.v_gen[t]) <= 1100.0 + 1e-6)
    lead = circuit.leading_mask[t]
    assert dev.pf_state == ("adelanto" if lead else "atraso")


def test_phase_2_1_reference_hour_12(demand, p21) -> None:
    """Hora 12 con Q_C = 87.25 kvar: valores de referencia calculados a mano."""
    v = algebraic_development(demand, p21, 11, q_c_kvar=QC_FIXED_ECONOMIC_2_1_KVAR, phase=PHASE_2_1).values
    assert v["Q1"] == pytest.approx(86.7173, abs=1e-4) and v["Q2"] == pytest.approx(70.5534, abs=1e-4)
    assert v["S_carga"] == pytest.approx(complex(165.0, 157.2707), abs=1e-4)
    assert v["S_neto"] == pytest.approx(complex(165.0, 70.0207), abs=1e-4)
    assert v["fp_neto"] == pytest.approx(0.920540, abs=1e-6)
    assert v["I_load"] == pytest.approx(complex(1375.0, -583.5059), abs=1e-3)
    assert v["I_line"] == pytest.approx(complex(2.5, -1.060920), abs=1e-6)
    assert v["I_gen"] == pytest.approx(complex(165.0, -70.0207), abs=1e-4)
    assert v["dV_line"] == pytest.approx(complex(1154.828, 2165.126), abs=1e-3)
    assert v["V_envio"] == pytest.approx(complex(67154.828, 2165.126), abs=1e-3)
    assert v["V_T1_prim"] == pytest.approx(complex(1017.4974, 32.8049), abs=1e-4)
    assert v["dV_Rgen"] == pytest.approx(complex(82.5, -35.0104), abs=1e-4)
    assert abs(v["V_gen"]) == pytest.approx(1099.9996, abs=1e-4)
    assert math.degrees(cmath.phase(v["V_gen"])) == pytest.approx(-0.1149, abs=1e-4)
    assert v["P_loss_linea"] == pytest.approx(0.590044, abs=1e-6)
    assert v["Q_loss_linea"] == pytest.approx(6.637996, abs=1e-6)
    assert v["P_loss_gen"] == pytest.approx(16.063950, abs=1e-6)
    assert v["S_gen"] == pytest.approx(complex(181.6540, 76.6587), abs=1e-4)


# ----------------------------------------------------------------------------------
# Estructura y contenido de los ocho pasos
# ----------------------------------------------------------------------------------
def test_eight_numbered_steps_in_every_phase(demand, p2, p21) -> None:
    cases = (
        algebraic_development(demand, p2, 11, direct=True),
        algebraic_development(demand, p2, 11, q_c_kvar=QC_FIXED_ECONOMIC_KVAR, phase=PHASE_2),
        algebraic_development(demand, p21, 11, q_c_kvar=QC_FIXED_ECONOMIC_2_1_KVAR, phase=PHASE_2_1),
    )
    for dev in cases:
        assert [s.number for s in dev.steps] == list(range(1, 9))
        assert [s.title for s in dev.steps[:5]] == TITLES_1_TO_5
        assert dev.steps[7].title == "Potencias y pérdidas (línea, generador y totales)"
        assert all(len(s.equations) >= 1 for s in dev.steps)
        assert "_" not in "".join(s.title for s in dev.steps)  # sin guiones bajos que Markdown lea como cursiva
    assert cases[0].steps[5].title == "Red directa a 120 V: sin transformadores"
    assert cases[1].steps[5].title == "Relaciones de transformación y reflejo a la línea de 13.2 kV"
    assert cases[2].steps[5].title == "Relaciones de transformación y reflejo a la línea de 66 kV"
    assert cases[2].steps[6].title == (
        "Caída de tensión en línea, tensión en el lado de 66 kV y tensión referida del generador Vgen"
    )


def test_phase_2_1_shows_66kv_relations(demand, p21) -> None:
    dev = algebraic_development(demand, p21, 11, q_c_kvar=QC_FIXED_ECONOMIC_2_1_KVAR, phase=PHASE_2_1)
    relations = " ".join(dev.steps[5].equations)
    for token in (
        r"\text{T2 reductor (66 kV : 120 V):}\quad a_2 = \frac{66\,000}{120} = 550",
        r"\text{T1 elevador (1 kV : 66 kV):}\quad a_1 = \frac{1\,000}{66\,000} = \frac{1}{66} = 0.015152",
        r"n_1 = \frac{1}{a_1} = 66",
        r"I_{line} = \frac{I_{load}}{a_2} = \frac{I_{load}}{550} = 2.500000 - j1.060920",
        r"I_{gen} = \frac{I_{line}}{a_1} = n_1\,I_{line} = 66\,I_{line} = 165.0000 - j70.0207",
        r"Z_{line} = 80 + j900\;\Omega = 903.5486\angle{84.9204}^\circ\;\Omega",
        r"\text{(en el nivel de 66 kV; la línea no se refleja)}",
        r"R_{gen}' = \frac{R_{gen}}{a_1^2} = 0.5\cdot 66^2 = 2\,178\;\Omega",
        r"R_{eq} = 80 + 2\,178 = 2\,258\;\Omega",
    ):
        assert token in relations, token
    voltages = " ".join(dev.steps[6].equations)
    for token in (
        r"V_{rec} = a_2\,V_0 = 550\cdot 120\angle 0^\circ = 66\,000\angle 0^\circ\;\text{V}",
        r"\Delta V_{line} = I_{line}\,Z_{line} = I_{line}\,(80 + j900) = 1\,154.828 + j2\,165.126\;\text{V}",
        r"V_{envío} = V_{rec} + \Delta V_{line} = 67\,154.828 + j2\,165.126\;\text{V}",
        r"V_{T1,prim} = a_1\,V_{envío} = \frac{V_{envío}}{66} = 1\,017.497 + j32.805\;\text{V}",
        r"\Delta V_{Rgen} = R_{gen}\,I_{gen} = 0.5\,I_{gen} = 82.500 - j35.010\;\text{V}",
        r"V_{gen} = V_{T1,prim} + \Delta V_{Rgen} = 1\,099.9974 - j2.2054\;\text{V}",
        r"= 1\,099.9996\angle{-0.1149}^\circ\;\text{V}",
        r"1\,000\angle 0^\circ\;\text{V} + I_{gen}\,(0.518365 + j0.206612)\;\Omega",
        r"950 \le |V_{gen}| = 1\,099.9996\;\text{V} \le 1100\quad\text{(dentro de la banda [950, 1100] V)}",
    ):
        assert token in voltages, token
    powers = " ".join(dev.steps[7].equations)
    for token in (
        r"P_{loss,línea} = \frac{|I_{line}|^2\cdot 80}{1000} = 0.590044\ \text{kW}",
        r"Q_{loss,línea} = \frac{|I_{line}|^2\cdot 900}{1000} = 6.637996\ \text{kvar}",
        r"P_{loss,gen} = \frac{|I_{gen}|^2\cdot 0.5}{1000} = 16.063950\ \text{kW}",
        r"Q_{loss,gen} = 0\ \text{kvar}",
        r"= \frac{|I_{line}|^2\cdot 2\,258}{1000} = 16.653994\ \text{kW}",
        r"S_{gen} = \frac{V_{gen}\,I_{gen}^*}{1000} = 181.6540 + j76.6587\;\text{kVA}",
        r"S_{neto} + S_{loss,tot} = 181.6540 + j76.6587\;\text{kVA} = S_{gen}",
    ):
        assert token in powers, token
    assert r"Q_C) = 165 + j(157.2707 - 87.2500) = 165.0000 + j70.0207\;\text{kVA}" in dev.steps[2].equations[0]
    assert r"= 0.920540\ \text{(atraso)}" in dev.steps[3].equations[0]


def test_band_statement_is_true_in_every_case(demand, p2, p21) -> None:
    inside = algebraic_development(demand, p21, 11, q_c_kvar=QC_FIXED_ECONOMIC_2_1_KVAR).steps[6].equations[-1]
    assert r"\le 1100" in inside and "dentro de la banda" in inside
    above = algebraic_development(demand, p21, 11, q_c_kvar=0.0).steps[6].equations[-1]
    assert r"|V_{gen}| = 1\,119.0300\;\text{V} > 1100\;\text{V}" in above and "por 19.0300 V" in above
    below = algebraic_development(demand, p2, 7, q_c_kvar=QC_FIXED_ECONOMIC_KVAR).steps[6].equations[-1]
    assert r"|V_{gen}| = 838.8386\;\text{V} < 950\;\text{V}" in below and "por 111.1614 V" in below
    leading = algebraic_development(demand, p2, 11, q_c_kvar=QC_FIXED_ECONOMIC_KVAR)
    assert leading.pf_state == "adelanto" and r"\text{(adelanto)}" in leading.steps[3].equations[0]
    assert r"275.8642\angle{-53.2646}^\circ" in leading.steps[2].equations[0]  # ángulo negativo entre llaves


def test_direct_network_rejects_capacitor(demand, p2) -> None:
    with pytest.raises(ValueError, match="no tiene banco"):
        algebraic_development(demand, p2, 0, q_c_kvar=10.0, direct=True)


# ----------------------------------------------------------------------------------
# Higiene LaTeX
# ----------------------------------------------------------------------------------
@pytest.mark.parametrize("t", [0, 3, 7, 11, 18, 23])
def test_latex_is_clean(demand, p2, p21, t: int) -> None:
    cases = [algebraic_development(demand, p2, t, direct=True)]
    cases += [algebraic_development(demand, p2, t, q_c_kvar=q) for q in (0.0, QC_FIXED_ECONOMIC_KVAR)]
    cases += [algebraic_development(demand, p21, t, q_c_kvar=q) for q in (0.0, QC_FIXED_ECONOMIC_2_1_KVAR)]
    for dev in cases:
        for eq in dev.latex:
            assert not unknown_commands(eq), (unknown_commands(eq), eq)
            assert braces_balanced(eq), eq
            assert "$" not in eq and "_{}" not in eq
            assert eq.count(r"\left") == eq.count(r"\right")
            assert "-0.0000" not in eq and "nan" not in eq and "inf" not in eq
            assert not any(tok in eq for tok in (r"\quadP", r"\quadQ", r"\quadI", r"\quadV", r"\quadS"))


def test_values_are_independent_of_numpy_types(demand, p21) -> None:
    dev = algebraic_development(demand, p21, 0, q_c_kvar=QC_FIXED_ECONOMIC_2_1_KVAR)
    assert all(isinstance(x, (complex, float)) for x in dev.values.values())
    assert dev.hour == 1 and dev.v_gen_mag == pytest.approx(float(np.abs(dev.values["V_gen"])))
