"""Desarrollo numérico paso a paso de un flujo de potencia.

Dos productos:

- ``hourly_step_table``: tabla de 24 filas con cada magnitud intermedia de un flujo ya resuelto, en el orden del
  cálculo manual, y con la conservación de potencia compleja verificada de forma independiente
  (S_gen = V_gen·I_gen* frente a S_neto + S_pérdidas,línea + S_pérdidas,gen).
- ``algebraic_development``: desarrollo algebraico de **una hora** («método de clase») para la Fase 1 (red directa
  a 120 V), la Fase 2 (T1 = 1kV:13.2kV, T2 = 13.2kV:120V) y la Fase 2.1 (T1 = 1kV:66kV, T2 = 66kV:120V).
  Cada paso se recalcula a partir del anterior —no se copia del solucionador—, así que compararlo con
  ``solve_problem1`` / ``solve_problem2`` es una verificación independiente de los resultados.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.domain.models import CircuitResult, DemandProfile, NetworkParameters, Scenario

KILO = 1_000.0
BAND_TOL_V = 1e-6  # misma tolerancia que usa el optimizador para contar una hora «fuera de banda»

PHASE_1 = "Fase 1"
PHASE_2 = "Fase 2"
PHASE_2_1 = "Fase 2.1"


def power_balance_error(circuit: CircuitResult, params: NetworkParameters) -> np.ndarray:
    """Error relativo |V_gen·I_gen* − (S_neto + |I_line|²·Z_line + |I_gen|²·R_gen)| / |S_gen| por hora."""
    s_gen = circuit.v_gen * np.conj(circuit.i_gen) / KILO
    s_line = np.abs(circuit.i_line) ** 2 * params.z_line / KILO
    s_rgen = np.abs(circuit.i_gen) ** 2 * params.r_gen / KILO
    return np.abs(s_gen - (circuit.s_load_kva + s_line + s_rgen)) / np.abs(s_gen)


def hourly_step_table(demand: DemandProfile, circuit: CircuitResult, params: NetworkParameters) -> pd.DataFrame:
    """Tabla de 24 filas con todas las magnitudes intermedias (kW, kvar, kVA, A, V)."""
    p2 = circuit.scenario is Scenario.PROBLEM_2_TRANSFORMERS
    s_load = demand.s_total_kva
    s_net = circuit.s_load_kva
    s_gen = circuit.v_gen * np.conj(circuit.i_gen) / KILO

    def mag_ang(prefix: str, z: np.ndarray) -> dict[str, np.ndarray]:
        return {f"{prefix}_mag": np.abs(z), f"{prefix}_deg": np.degrees(np.angle(z))}

    cols: dict[str, object] = {
        "hour": demand.hours,
        "P1_kW": demand.p1_kw,
        "pf1": demand.pf1,
        "Q1_kvar": demand.q1_kvar,
        "P2_kW": demand.p2_kw,
        "pf2": demand.pf2,
        "Q2_kvar": demand.q2_kvar,
        "P_carga_kW": s_load.real,
        "Q_carga_kvar": s_load.imag,
        "Q_C_kvar": circuit.q_c_kvar,
        "Q_neto_kvar": s_net.imag,
        "S_neto_kVA": np.abs(s_net),
        "fp_neto": circuit.pf_net,
        "fp_neto_estado": np.where(circuit.leading_mask, "adelanto", "atraso"),
        **mag_ang("I_load_A", circuit.i_load),
        **mag_ang("I_line_A", circuit.i_line),
        **mag_ang("I_gen_A", circuit.i_gen),
        **mag_ang("V_line_envio_V", circuit.v_line_send),
        **mag_ang("V_T1_prim_V", circuit.v_t1_primary),
        **mag_ang("V_gen_V", circuit.v_gen),
        "P_loss_line_kW": circuit.p_loss_line_kw,
        "P_loss_gen_kW": circuit.p_loss_gen_kw,
        "P_loss_total_kW": circuit.p_loss_kw,
        "Q_loss_kvar": circuit.q_loss_kvar,
        "P_gen_kW": s_gen.real,
        "Q_gen_kvar": s_gen.imag,
        "error_conservacion_rel": power_balance_error(circuit, params),
    }
    df = pd.DataFrame(cols)
    if not p2:  # en la red directa no hay transformadores ni banco
        df = df.drop(columns=["V_T1_prim_V_mag", "V_T1_prim_V_deg"])
    return df


# ==================================================================================
# Desarrollo algebraico de una hora (LaTeX)
# ==================================================================================
@dataclass(frozen=True, slots=True)
class AlgebraStep:
    """Un paso numerado del desarrollo: título y una o más ecuaciones LaTeX (sin delimitadores)."""

    number: int
    title: str
    equations: tuple[str, ...]


@dataclass(frozen=True, slots=True, eq=False)
class AlgebraDevelopment:
    """Desarrollo algebraico de una hora: pasos para mostrar y valores numéricos de cada magnitud."""

    phase: str
    hour: int
    direct: bool
    q_c_kvar: float
    steps: tuple[AlgebraStep, ...]
    values: dict[str, complex | float]
    pf_state: str  # "atraso", "adelanto" o "unitario"
    in_band: bool | None  # None en la red directa (la banda de tensión es del Problema 2)

    @property
    def latex(self) -> tuple[str, ...]:
        """Todas las ecuaciones, en orden."""
        return tuple(eq for step in self.steps for eq in step.equations)

    @property
    def v_gen_mag(self) -> float:
        return abs(self.values["V_gen"])


def _n(x: float, d: int) -> str:
    """Número con ``d`` decimales y separador de miles fino (sin '-0.000')."""
    return f"{round(x, d) + 0.0:,.{d}f}".replace(",", r"\,")


def _g(x: float) -> str:
    """Parámetro en forma corta con separador de miles fino: 66000 → 66\\,000; 13.2 → 13.2."""
    return f"{x:,g}".replace(",", r"\,")


def _rect(z: complex, d: int) -> str:
    sign = "+" if round(z.imag, d) >= 0 else "-"
    return f"{_n(z.real, d)} {sign} j{_n(abs(z.imag), d)}"


def _deg(z: complex, d: int = 4) -> str:
    return f"{round(math.degrees(cmath.phase(z)), d) + 0.0:.{d}f}"


def _polar(z: complex, d: int) -> str:
    """Forma polar; el ángulo va entre llaves para que un signo menos no se espacie como una resta."""
    return rf"{_n(abs(z), d)}\angle{{{_deg(z)}}}^\circ"


def _cx(z: complex, d: int, unit: str) -> str:
    """Complejo en dos renglones: rectangular y polar."""
    return rf"{_rect(z, d)}\;{unit} \\ = {_polar(z, d)}\;{unit}"


def _sci(x: float) -> str:
    if x == 0:
        return "0"
    mantissa, exponent = f"{x:.1e}".split("e")
    return rf"{mantissa}\times 10^{{{int(exponent)}}}"


_A, _V, _KVA, _OHM = r"\text{A}", r"\text{V}", r"\text{kVA}", r"\Omega"


def algebraic_development(
    demand: DemandProfile,
    params: NetworkParameters,
    t_index: int,
    q_c_kvar: float = 0.0,
    direct: bool = False,
    phase: str | None = None,
) -> AlgebraDevelopment:
    """Desarrollo algebraico de la hora ``t_index`` (0-based) en ocho pasos.

    ``direct=True`` es la Fase 1 (red directa a 120 V, sin transformadores ni banco). En otro caso se usan las
    relaciones de ``params``: Fase 2 con la línea a 13.2 kV o Fase 2.1 con la línea a 66 kV; ``q_c_kvar`` es el
    banco conectado en la barra de 120 V en esa hora.
    """
    if direct and q_c_kvar:
        raise ValueError("La red directa (Fase 1) no tiene banco de capacitores")
    t = t_index
    p1, pf1, p2, pf2 = (float(x[t]) for x in (demand.p1_kw, demand.pf1, demand.p2_kw, demand.pf2))
    v0 = complex(params.v_load)
    v_sec = abs(v0)
    r_gen, z_line = params.r_gen, params.z_line
    r_line, x_line = z_line.real, z_line.imag

    # 1–5: carga, flujo neto y corriente en la barra de 120 V
    tan1, tan2 = math.tan(math.acos(pf1)), math.tan(math.acos(pf2))
    q1, q2 = p1 * tan1, p2 * tan2
    p_tot, q_tot = p1 + p2, q1 + q2
    s_load = complex(p_tot, q_tot)
    s_net = complex(p_tot, q_tot - q_c_kvar)
    pf = p_tot / abs(s_net)
    pf_state = "unitario" if abs(s_net.imag) <= 1e-9 else "atraso" if s_net.imag > 0 else "adelanto"
    i_load = (s_net * KILO / v0).conjugate()

    # 6: relaciones de transformación y corrientes
    a2, n1 = (1.0, 1.0) if direct else (params.a2, params.n1)
    a1 = 1.0 / n1
    i_line = i_load / a2
    i_gen = i_line / a1
    r_gen_line = r_gen / a1**2
    r_eq = r_line + r_gen_line

    # 7: tensiones, de la carga hacia el generador
    v_rec = v0 * a2
    dv_line = i_line * z_line
    v_send = v_rec + dv_line
    v_t1 = a1 * v_send
    dv_rgen = r_gen * i_gen
    v_gen = v_t1 + dv_rgen
    v0_ref = a1 * a2 * v0
    z_ref = r_gen + a1**2 * z_line
    v_gen_ref = v0_ref + i_gen * z_ref
    vg = abs(v_gen)
    in_band = None if direct else params.v_gen_min - BAND_TOL_V <= vg <= params.v_gen_max + BAND_TOL_V

    # 8: pérdidas y potencia del generador
    p_line = abs(i_line) ** 2 * r_line / KILO
    q_line = abs(i_line) ** 2 * x_line / KILO
    p_gen = abs(i_gen) ** 2 * r_gen / KILO
    s_loss = complex(p_line + p_gen, q_line)
    p_check = abs(i_line) ** 2 * r_eq / KILO
    s_gen = v_gen * i_gen.conjugate() / KILO
    s_sum = s_net + s_loss
    err = abs(s_gen - s_sum) / abs(s_gen)

    head = (
        (
            "Potencias reactivas de la Tabla 1 (cargas en atraso)",
            (
                rf"Q_1 = P_1\tan(\cos^{{-1}}{pf1:.2f}) = {p1:g}\cdot{tan1:.6f} = {_n(q1, 4)}\ \text{{kvar}} \\ "
                rf"Q_2 = P_2\tan(\cos^{{-1}}{pf2:.2f}) = {p2:g}\cdot{tan2:.6f} = {_n(q2, 4)}\ \text{{kvar}}",
            ),
        ),
        (
            "Potencia de la carga (L1 + L2)",
            (rf"S_{{carga}} = ({p1:g} + {p2:g}) + j({_n(q1, 4)} + {_n(q2, 4)}) = {_cx(s_load, 4, _KVA)}",),
        ),
        (
            f"Flujo neto en la barra de {v_sec:g} V",
            (
                rf"S_{{neto}} = P_{{tot}} + j(Q_{{tot}} - Q_C) = {p_tot:g} + j({_n(q_tot, 4)} - {_n(q_c_kvar, 4)})"
                rf" = {_cx(s_net, 4, _KVA)}",
            ),
        ),
        (
            "Factor de potencia neto",
            (
                rf"fp_{{neto}} = \frac{{P_{{tot}}}}{{|S_{{neto}}|}} = \frac{{{_n(p_tot, 4)}}}{{{_n(abs(s_net), 4)}}}"
                rf" = {pf:.6f}\ \text{{({pf_state})}}",
            ),
        ),
        (
            f"Corriente de carga ({v_sec:g} V)",
            (
                rf"I_{{load}} = \left(\frac{{S_{{neto}}\cdot 1000}}{{{v_sec:g}\angle 0^\circ}}\right)^*"
                rf" = {_cx(i_load, 4, _A)}",
            ),
        ),
    )

    z_line_tex = rf"{_g(r_line)} + j{_g(x_line)}"
    if direct:
        d_loss = 4
        relations = (
            f"Red directa a {v_sec:g} V: sin transformadores",
            (
                rf"\text{{Sin T1 ni T2 (}}a_1 = a_2 = 1\text{{):}}\quad I_{{line}} = I_{{gen}} = I_{{load}}"
                rf" = {_cx(i_line, 4, _A)}",
                rf"Z_{{line}} = {z_line_tex}\;{_OHM} = {_polar(z_line, 4)}\;{_OHM}\quad"
                rf"\text{{(en el nivel de {v_sec:g} V, sin reflejar)}} \\ "
                rf"R_{{eq}} = {_g(r_line)} + {_g(r_gen)} = {_g(r_eq)}\;{_OHM}",
            ),
        )
        voltages = (
            "Caída de tensión en línea y tensión del generador Vgen",
            (
                rf"\Delta V_{{line}} = I_{{line}}\,Z_{{line}} = I_{{line}}\,({z_line_tex}) = {_cx(dv_line, 3, _V)}",
                rf"V_{{envío}} = V_0 + \Delta V_{{line}} = {v_sec:g}\angle 0^\circ + \Delta V_{{line}}"
                rf" = {_cx(v_send, 3, _V)}",
                rf"\Delta V_{{Rgen}} = R_{{gen}}\,I_{{gen}} = {_g(r_gen)}\,I_{{gen}} = {_cx(dv_rgen, 3, _V)}",
                rf"V_{{gen}} = V_{{envío}} + \Delta V_{{Rgen}} = {_cx(v_gen, 3, _V)}",
            ),
        )
    else:
        d_loss = 6
        kv, v_prim_kv = params.line_kv, params.t1_primary_v / KILO
        relations = (
            f"Relaciones de transformación y reflejo a la línea de {kv:g} kV",
            (
                rf"\text{{T2 reductor ({kv:g} kV : {v_sec:g} V):}}\quad a_2 = "
                rf"\frac{{{_g(params.t2_primary_v)}}}{{{_g(params.t2_secondary_v)}}} = {_g(a2)}",
                rf"\text{{T1 elevador ({v_prim_kv:g} kV : {kv:g} kV):}}\quad a_1 = "
                rf"\frac{{{_g(params.t1_primary_v)}}}{{{_g(params.t1_secondary_v)}}} = \frac{{1}}{{{_g(n1)}}}"
                rf" = {a1:.6f},\quad n_1 = \frac{{1}}{{a_1}} = {_g(n1)}",
                rf"I_{{line}} = \frac{{I_{{load}}}}{{a_2}} = \frac{{I_{{load}}}}{{{_g(a2)}}} = {_cx(i_line, 6, _A)}",
                rf"I_{{gen}} = \frac{{I_{{line}}}}{{a_1}} = n_1\,I_{{line}} = {_g(n1)}\,I_{{line}}"
                rf" = {_cx(i_gen, 4, _A)}",
                rf"Z_{{line}} = {z_line_tex}\;{_OHM} = {_polar(z_line, 4)}\;{_OHM} \\ "
                rf"\text{{(en el nivel de {kv:g} kV; la línea no se refleja)}}",
                rf"\text{{Reflejo de }}R_{{gen}}\text{{ a la línea de {kv:g} kV:}}\quad R_{{gen}}' = "
                rf"\frac{{R_{{gen}}}}{{a_1^2}} = {_g(r_gen)}\cdot {_g(n1)}^2 = {_g(r_gen_line)}\;{_OHM} \\ "
                rf"R_{{eq}} = {_g(r_line)} + {_g(r_gen_line)} = {_g(r_eq)}\;{_OHM}",
            ),
        )
        v_min, v_max = params.v_gen_min, params.v_gen_max
        if in_band:
            band = (
                rf"{v_min:g} \le |V_{{gen}}| = {_n(vg, 4)}\;{_V} \le {v_max:g}\quad"
                rf"\text{{(dentro de la banda [{v_min:g}, {v_max:g}] V)}}"
            )
        elif vg > v_max:
            band = (
                rf"|V_{{gen}}| = {_n(vg, 4)}\;{_V} > {v_max:g}\;{_V}\quad"
                rf"\text{{(fuera de la banda [{v_min:g}, {v_max:g}] V por {vg - v_max:,.4f} V)}}"
            )
        else:
            band = (
                rf"|V_{{gen}}| = {_n(vg, 4)}\;{_V} < {v_min:g}\;{_V}\quad"
                rf"\text{{(fuera de la banda [{v_min:g}, {v_max:g}] V por {v_min - vg:,.4f} V)}}"
            )
        voltages = (
            f"Caída de tensión en línea, tensión en el lado de {kv:g} kV y tensión referida del generador Vgen",
            (
                rf"V_{{rec}} = a_2\,V_0 = {_g(a2)}\cdot {v_sec:g}\angle 0^\circ = {_g(abs(v_rec))}\angle 0^\circ\;{_V}"
                rf"\quad\text{{(lado de {kv:g} kV, primario de T2)}}",
                rf"\Delta V_{{line}} = I_{{line}}\,Z_{{line}} = I_{{line}}\,({z_line_tex}) = {_cx(dv_line, 3, _V)}",
                rf"V_{{envío}} = V_{{rec}} + \Delta V_{{line}} = {_cx(v_send, 3, _V)}"
                rf"\quad\text{{(lado de {kv:g} kV, secundario de T1)}}",
                rf"V_{{T1,prim}} = a_1\,V_{{envío}} = \frac{{V_{{envío}}}}{{{_g(n1)}}} = {_cx(v_t1, 3, _V)}",
                rf"\Delta V_{{Rgen}} = R_{{gen}}\,I_{{gen}} = {_g(r_gen)}\,I_{{gen}} = {_cx(dv_rgen, 3, _V)}",
                rf"V_{{gen}} = V_{{T1,prim}} + \Delta V_{{Rgen}} = {_cx(v_gen, 4, _V)}",
                rf"\text{{Comprobación con todo referido al lado de {v_prim_kv:g} kV:}} \\ "
                rf"V_{{gen}} = a_1 a_2\,V_0 + I_{{gen}}\left(R_{{gen}} + a_1^2\,Z_{{line}}\right) \\ "
                rf"= {_g(abs(v0_ref))}\angle 0^\circ\;{_V} + I_{{gen}}\,({_rect(z_ref, 6)})\;{_OHM}"
                rf" = {_polar(v_gen_ref, 4)}\;{_V}",
                band,
            ),
        )

    powers = (
        "Potencias y pérdidas (línea, generador y totales)",
        (
            rf"P_{{loss,línea}} = \frac{{|I_{{line}}|^2\cdot {_g(r_line)}}}{{1000}} = {_n(p_line, d_loss)}\ \text{{kW}}"
            rf" \\ Q_{{loss,línea}} = \frac{{|I_{{line}}|^2\cdot {_g(x_line)}}}{{1000}}"
            rf" = {_n(q_line, d_loss)}\ \text{{kvar}}",
            rf"P_{{loss,gen}} = \frac{{|I_{{gen}}|^2\cdot {_g(r_gen)}}}{{1000}} = {_n(p_gen, d_loss)}\ \text{{kW}}"
            rf" \\ Q_{{loss,gen}} = 0\ \text{{kvar}}\quad\text{{(}}R_{{gen}}\text{{ es resistiva pura)}}",
            rf"S_{{loss,tot}} = (P_{{loss,línea}} + P_{{loss,gen}}) + j\,(Q_{{loss,línea}} + Q_{{loss,gen}}) \\ "
            rf"= {_rect(s_loss, d_loss)}\;{_KVA} \\ "
            rf"\text{{Comprobación:}}\quad P_{{loss,tot}} = \frac{{|I_{{line}}|^2\cdot R_{{eq}}}}{{1000}}"
            rf" = \frac{{|I_{{line}}|^2\cdot {_g(r_eq)}}}{{1000}} = {_n(p_check, d_loss)}\ \text{{kW}}",
            rf"S_{{gen}} = \frac{{V_{{gen}}\,I_{{gen}}^*}}{{1000}} = {_cx(s_gen, 4, _KVA)}",
            rf"S_{{neto}} + S_{{loss,tot}} = {_rect(s_sum, 4)}\;{_KVA} = S_{{gen}}"
            rf"\quad\left(\varepsilon_{{rel}} = {_sci(err)}\right)",
        ),
    )

    steps = tuple(
        AlgebraStep(number, title, equations)
        for number, (title, equations) in enumerate((*head, relations, voltages, powers), 1)
    )
    values: dict[str, complex | float] = {
        "P_tot": p_tot,
        "Q1": q1,
        "Q2": q2,
        "Q_tot": q_tot,
        "S_carga": s_load,
        "S_neto": s_net,
        "fp_neto": pf,
        "I_load": i_load,
        "a1": a1,
        "a2": a2,
        "n1": n1,
        "I_line": i_line,
        "I_gen": i_gen,
        "Z_line": z_line,
        "R_gen_linea": r_gen_line,
        "R_eq": r_eq,
        "V_rec": v_rec,
        "dV_line": dv_line,
        "V_envio": v_send,
        "V_T1_prim": v_t1,
        "dV_Rgen": dv_rgen,
        "V_gen": v_gen,
        "V_gen_reflejada": v_gen_ref,
        "P_loss_linea": p_line,
        "Q_loss_linea": q_line,
        "P_loss_gen": p_gen,
        "Q_loss_gen": 0.0,
        "S_loss_tot": s_loss,
        "P_loss_tot_Req": p_check,
        "S_gen": s_gen,
        "error_conservacion": err,
    }
    return AlgebraDevelopment(
        phase=phase or (PHASE_1 if direct else PHASE_2),
        hour=int(demand.hours[t]),
        direct=direct,
        q_c_kvar=float(q_c_kvar),
        steps=steps,
        values=values,
        pf_state=pf_state,
        in_band=in_band,
    )
