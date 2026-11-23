"""Desarrollo numérico paso a paso (tabla horaria) de un flujo de potencia ya resuelto.

Reproduce, en el orden del cálculo manual, cada magnitud intermedia de la Fase 1 (red directa) o de la
Fase 2 (T1 + línea + T2 + banco Q_C) y verifica la conservación de potencia compleja de forma
independiente: S_gen = V_gen·I_gen* frente a S_neto + S_pérdidas,línea + S_pérdidas,gen.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.domain.models import CircuitResult, DemandProfile, NetworkParameters, Scenario

KILO = 1_000.0


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
