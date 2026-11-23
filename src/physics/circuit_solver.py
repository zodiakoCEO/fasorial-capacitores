"""Solucionador fasorial de las dos topologías (funciones puras, vectorizadas por hora).

Problema 1:  V_gen → R_gen → Z_line → V_0 → (L1 ‖ L2)
Problema 2:  V_gen → R_gen → T1 (1:13.2) → Z_line → T2 (110:1) → V_0 → (L1 ‖ L2 ‖ Q_C)

Para el Problema 2 la tensión del generador es **afín** en Q_C:

    V_gen(t, Q_C) = A(t) + B · Q_C

con  k = 1000 / (V_0 · a2)  [A por kVA],  Z_eq = Z_line + R_gen · n1²,

    A(t) = V_0·a2 / n1 + k·(P(t) − jQ(t))·Z_eq / n1,      B = j·k·Z_eq / n1.

Esto permite resolver analíticamente la factibilidad |V_gen| ∈ [950, 1100] V como
desigualdades cuadráticas en Q_C (ver ``voltage_magnitude_quadratic``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from src.domain.models import (
    CircuitResult,
    ComplexArray,
    DemandProfile,
    FloatArray,
    NetworkParameters,
    Scenario,
)

KILO = 1_000.0


def reactive_power_kvar(p_kw: npt.ArrayLike, pf: npt.ArrayLike) -> FloatArray:
    """Q = P · tan(arccos(pf)) para factor de potencia en atraso."""
    return np.asarray(p_kw, float) * np.tan(np.arccos(np.asarray(pf, float)))


def load_current(s_kva: npt.ArrayLike, v_load: complex) -> ComplexArray:
    """I = conj(S / V)  con S en kVA convertido a VA."""
    return np.conj(np.asarray(s_kva, complex) * KILO / v_load)


def _as_hourly(q_c_kvar: float | npt.ArrayLike, n: int) -> FloatArray:
    q = np.asarray(q_c_kvar, dtype=float)
    if q.ndim == 0:
        return np.full(n, float(q))
    if q.shape != (n,):
        raise ValueError(f"Q_C debe ser escalar o vector de {n} horas")
    return q.astype(float)


# ==================================================================================
# Problema 1 — red directa a 120 V
# ==================================================================================
def solve_problem1(demand: DemandProfile, params: NetworkParameters | None = None) -> CircuitResult:
    """Flujo de potencia de la red directa (sin transformadores ni capacitor)."""
    params = params or NetworkParameters()
    n = demand.n_hours
    s_load = demand.s_total_kva
    i_load = load_current(s_load, params.v_load)
    i_line = i_load
    v_load = np.full(n, params.v_load, dtype=complex)
    v_line_send = v_load + i_line * params.z_line
    v_gen = v_line_send + i_line * params.r_gen

    i2 = np.abs(i_line) ** 2
    p_loss_line = i2 * params.r_line / KILO
    p_loss_gen = i2 * params.r_gen / KILO
    q_loss = i2 * params.x_line / KILO
    s_gen = s_load + (p_loss_line + p_loss_gen) + 1j * q_loss

    return CircuitResult(
        scenario=Scenario.PROBLEM_1_DIRECT,
        hours=demand.hours,
        q_c_kvar=np.zeros(n),
        s_load_kva=s_load,
        i_load=i_load,
        i_line=i_line,
        i_gen=i_line,
        v_load=v_load,
        v_line_receiving=v_load,
        v_line_send=v_line_send,
        v_t1_primary=v_line_send,
        v_gen=v_gen,
        p_loss_line_kw=p_loss_line,
        p_loss_gen_kw=p_loss_gen,
        q_loss_kvar=q_loss,
        s_gen_kva=s_gen,
    )


# ==================================================================================
# Problema 2 — red con transformadores ideales + banco de capacitores
# ==================================================================================
def solve_problem2(
    demand: DemandProfile,
    q_c_kvar: float | npt.ArrayLike = 0.0,
    params: NetworkParameters | None = None,
) -> CircuitResult:
    """Flujo de potencia con T1, T2 ideales y banco Q_C (escalar fijo o vector horario)."""
    params = params or NetworkParameters()
    n = demand.n_hours
    q_c = _as_hourly(q_c_kvar, n)

    s_net = demand.p_total_kw + 1j * (demand.q_total_kvar - q_c)
    i_load = load_current(s_net, params.v_load)
    i_line = i_load / params.a2
    i_gen = i_line * params.n1

    v_load = np.full(n, params.v_load, dtype=complex)
    v_recv = v_load * params.a2
    v_send = v_recv + i_line * params.z_line
    v_t1_prim = v_send / params.n1
    v_gen = v_t1_prim + i_gen * params.r_gen

    p_loss_line = np.abs(i_line) ** 2 * params.r_line / KILO
    p_loss_gen = np.abs(i_gen) ** 2 * params.r_gen / KILO
    q_loss = np.abs(i_line) ** 2 * params.x_line / KILO
    s_gen = s_net + (p_loss_line + p_loss_gen) + 1j * q_loss

    return CircuitResult(
        scenario=Scenario.PROBLEM_2_TRANSFORMERS,
        hours=demand.hours,
        q_c_kvar=q_c,
        s_load_kva=s_net,
        i_load=i_load,
        i_line=i_line,
        i_gen=i_gen,
        v_load=v_load,
        v_line_receiving=v_recv,
        v_line_send=v_send,
        v_t1_primary=v_t1_prim,
        v_gen=v_gen,
        p_loss_line_kw=p_loss_line,
        p_loss_gen_kw=p_loss_gen,
        q_loss_kvar=q_loss,
        s_gen_kva=s_gen,
        meta={"n1": params.n1, "a2": params.a2, "R_eq_line_side": params.r_eq_line_side},
    )


# ==================================================================================
# Modelo afín V_gen(Q_C) = A + B·Q_C y forma cuadrática de |V_gen|²
# ==================================================================================
@dataclass(frozen=True, slots=True, eq=False)
class AffineVoltageModel:
    """V_gen(t, Q_C) = A(t) + B · Q_C  (Q_C en kvar)."""

    A: ComplexArray
    B: complex

    def v_gen(self, q_c_kvar: float | npt.ArrayLike) -> ComplexArray:
        return self.A + self.B * np.asarray(q_c_kvar, float)

    def magnitude(self, q_c_kvar: float | npt.ArrayLike) -> FloatArray:
        return np.abs(self.v_gen(q_c_kvar))

    @property
    def quadratic(self) -> tuple[float, FloatArray, FloatArray]:
        """Coeficientes (a, b, c) con |V_gen|² = a·Q_C² + b(t)·Q_C + c(t)."""
        a = float(abs(self.B) ** 2)
        b = 2.0 * np.real(self.A * np.conj(self.B))
        c = np.abs(self.A) ** 2
        return a, b, c


def affine_voltage_model(demand: DemandProfile, params: NetworkParameters | None = None) -> AffineVoltageModel:
    params = params or NetworkParameters()
    # I_line = conj(S_net)·k  con  k = 1000 / (conj(V_0)·a2)  [A de línea por kVA]
    k = KILO / (np.conj(params.v_load) * params.a2)
    z_over_n1 = params.z_eq_line_side / params.n1
    s_conj = demand.p_total_kw - 1j * demand.q_total_kvar
    A = params.v_line_receiving / params.n1 + k * s_conj * z_over_n1
    B = 1j * k * z_over_n1
    return AffineVoltageModel(A=np.asarray(A, complex), B=complex(B))


def daily_loss_quadratic(demand: DemandProfile, params: NetworkParameters | None = None) -> tuple[float, FloatArray]:
    """P_loss(t, Q_C) [kW] = κ · (P(t)² + (Q(t) − Q_C)²)  con κ = R_eq·1000 / (V_0·a2)².

    Devuelve (κ, Q(t)) para derivadas cerradas del óptimo económico.
    """
    params = params or NetworkParameters()
    kappa = params.r_eq_line_side * KILO / abs(params.v_line_receiving) ** 2
    return float(kappa), demand.q_total_kvar
