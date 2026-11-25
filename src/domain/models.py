"""Modelos de dominio inmutables: parámetros de red, perfil de demanda y resultados."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pandas as pd

from src.domain import constants as C

FloatArray = npt.NDArray[np.float64]
LAGGING_TOL_KVAR = 1e-9  # Q_net ≥ −tol se considera en atraso (o unitario)
ComplexArray = npt.NDArray[np.complex128]


def _frozen(array: npt.ArrayLike, dtype: type = np.float64) -> npt.NDArray:
    """Copia ``array`` como ndarray de solo lectura (inmutabilidad real del dominio)."""
    out = np.array(array, dtype=dtype, copy=True)
    out.setflags(write=False)
    return out


class Scenario(StrEnum):
    """Topologías eléctricas modeladas."""

    PROBLEM_1_DIRECT = "Problema 1 — Red directa a 120 V"
    PROBLEM_2_TRANSFORMERS = "Problema 2 — Red con transformadores + Q_C"


class Strategy(StrEnum):
    """Estrategias de compensación reactiva evaluadas en el Problema 2."""

    NO_CAPACITOR = "Sin Capacitor (Q_C=0)"
    FIXED_ECONOMIC = "Banco Fijo — Óptimo Económico"
    FIXED_MIN_VIOLATION = "Banco Fijo — Mínima Violación de Tensión"
    SWITCHED = "Banco Automático por Pasos (100% Factible)"
    FIXED_LAGGING = "Banco Fijo — 100% en Atraso"
    SWITCHED_LAGGING = "Banco Automático por Pasos — 100% en Atraso"
    MANUAL = "Manual (Slider de Q_C)"


@dataclass(frozen=True, slots=True)
class NetworkParameters:
    """Parámetros eléctricos y económicos del sistema (valores por defecto = enunciado)."""

    v_load: complex = C.V0_LOAD
    r_gen: float = C.R_GEN_OHM
    z_line: complex = C.Z_LINE_OHM
    t1_primary_v: float = C.T1_PRIMARY_V
    t1_secondary_v: float = C.T1_SECONDARY_V
    t2_primary_v: float = C.T2_PRIMARY_V
    t2_secondary_v: float = C.T2_SECONDARY_V
    energy_price_cop_per_kwh: float = C.ENERGY_PRICE_COP_PER_KWH
    days_per_year: int = C.DAYS_PER_YEAR
    capacitor_cost_cop_per_kvar: float = C.CAPACITOR_COST_COP_PER_KVAR
    v_gen_min: float = C.V_GEN_MIN_V
    v_gen_max: float = C.V_GEN_MAX_V

    @property
    def n1(self) -> float:
        """Relación del transformador elevador T1 (secundario / primario) = 13.2."""
        return self.t1_secondary_v / self.t1_primary_v

    @property
    def a2(self) -> float:
        """Relación del transformador reductor T2 (primario / secundario) = 110."""
        return self.t2_primary_v / self.t2_secondary_v

    @property
    def r_line(self) -> float:
        return self.z_line.real

    @property
    def x_line(self) -> float:
        return self.z_line.imag

    @property
    def r_eq_line_side(self) -> float:
        """Resistencia total referida al lado de 13.2 kV: R_line + R_gen·n1² (= 167.12 Ω)."""
        return self.r_line + self.r_gen * self.n1**2

    @property
    def z_eq_line_side(self) -> complex:
        """Impedancia serie total referida al lado de línea (13.2 kV)."""
        return self.z_line + self.r_gen * self.n1**2

    @property
    def v_line_receiving(self) -> complex:
        """Tensión en el primario de T2 = V_0 · a2 (13 200∠0° V)."""
        return self.v_load * self.a2

    @property
    def line_kv(self) -> float:
        """Tensión nominal de la línea en kV (secundario de T1 = primario de T2)."""
        return self.t1_secondary_v / 1000.0

    @property
    def t1_label(self) -> str:
        """Relación de T1 como en la Figura 2: '1kV:13.2kV'."""
        return f"{self.t1_primary_v / 1000:g}kV:{self.t1_secondary_v / 1000:g}kV"

    @property
    def t2_label(self) -> str:
        """Relación de T2 como en la Figura 2: '13.2kV:120V'."""
        return f"{self.t2_primary_v / 1000:g}kV:{self.t2_secondary_v:g}V"

    @property
    def r_gen_line_side(self) -> float:
        """R_gen referida al lado de línea: R_gen·n1² (87.12 Ω a 13.2 kV; 2178 Ω a 66 kV)."""
        return self.r_gen * self.n1**2

    @property
    def z_gen_side(self) -> complex:
        """Impedancia serie total vista desde el generador: R_gen + Z_line / n1²."""
        return self.r_gen + self.z_line / self.n1**2

    @property
    def v_load_gen_side(self) -> complex:
        """Tensión de la carga referida al generador: V_0·a2 / n1 (1000∠0° V en ambos casos)."""
        return self.v_load * self.a2 / self.n1

    def with_line_voltage(self, v_line: float) -> NetworkParameters:
        """Misma red con otra tensión de línea: T1 = primario : v_line y T2 = v_line : secundario."""
        return replace(self, t1_secondary_v=v_line, t2_primary_v=v_line)

    def with_line_reactance(self, x_line: float) -> NetworkParameters:
        return replace(self, z_line=complex(self.r_line, x_line))


@dataclass(frozen=True, slots=True, eq=False)
class DemandProfile:
    """Perfil de demanda horaria de las cargas L1 (residencial) y L2 (industrial)."""

    hours: npt.NDArray[np.int64]
    p1_kw: FloatArray
    pf1: FloatArray
    p2_kw: FloatArray
    pf2: FloatArray

    def __post_init__(self) -> None:
        n = len(self.hours)
        for name in ("p1_kw", "pf1", "p2_kw", "pf2"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"'{name}' debe tener {n} registros")
        for pf in (self.pf1, self.pf2):
            if np.any((np.asarray(pf) <= 0) | (np.asarray(pf) > 1)):
                raise ValueError("Los factores de potencia deben estar en (0, 1]")
        object.__setattr__(self, "hours", _frozen(self.hours, np.int64))
        for name in ("p1_kw", "pf1", "p2_kw", "pf2"):
            object.__setattr__(self, name, _frozen(getattr(self, name)))

    # -- Construcción -------------------------------------------------------------
    @classmethod
    def default(cls) -> DemandProfile:
        table = np.array(C.DEMAND_TABLE, dtype=float)
        return cls(
            hours=table[:, 0].astype(np.int64),
            p1_kw=table[:, 1],
            pf1=table[:, 2],
            p2_kw=table[:, 3],
            pf2=table[:, 4],
        )

    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> DemandProfile:
        missing = set(C.DEMAND_CSV_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"Columnas faltantes en el perfil de demanda: {sorted(missing)}")
        df = df.sort_values("hour")
        return cls(
            hours=df["hour"].to_numpy(np.int64),
            p1_kw=df["P1_kW"].to_numpy(float),
            pf1=df["pf1"].to_numpy(float),
            p2_kw=df["P2_kW"].to_numpy(float),
            pf2=df["pf2"].to_numpy(float),
        )

    @classmethod
    def from_csv(cls, path: str | Path) -> DemandProfile:
        return cls.from_dataframe(pd.read_csv(path))

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "hour": self.hours,
                "P1_kW": self.p1_kw,
                "pf1": self.pf1,
                "P2_kW": self.p2_kw,
                "pf2": self.pf2,
            }
        )

    # -- Potencias derivadas ------------------------------------------------------
    @property
    def n_hours(self) -> int:
        return len(self.hours)

    @property
    def q1_kvar(self) -> FloatArray:
        return self.p1_kw * np.tan(np.arccos(self.pf1))

    @property
    def q2_kvar(self) -> FloatArray:
        return self.p2_kw * np.tan(np.arccos(self.pf2))

    @property
    def p_total_kw(self) -> FloatArray:
        return self.p1_kw + self.p2_kw

    @property
    def q_total_kvar(self) -> FloatArray:
        return self.q1_kvar + self.q2_kvar

    @property
    def s_total_kva(self) -> ComplexArray:
        return self.p_total_kw + 1j * self.q_total_kvar


@dataclass(frozen=True, slots=True, eq=False)
class CircuitResult:
    """Resultado horario (vectorizado, 1 elemento por hora) de un flujo de potencia.

    Convenciones: corrientes en A, tensiones en V, potencias en kW / kvar / kVA.
    En el Problema 1 no hay transformadores, por lo que ``i_gen == i_line`` y
    ``v_line_send``/``v_t1_primary`` coinciden con la tensión aguas arriba de Z_line.
    """

    scenario: Scenario
    hours: npt.NDArray[np.int64]
    q_c_kvar: FloatArray
    s_load_kva: ComplexArray
    i_load: ComplexArray
    i_line: ComplexArray
    i_gen: ComplexArray
    v_load: ComplexArray
    v_line_receiving: ComplexArray
    v_line_send: ComplexArray
    v_t1_primary: ComplexArray
    v_gen: ComplexArray
    p_loss_line_kw: FloatArray
    p_loss_gen_kw: FloatArray
    q_loss_kvar: FloatArray
    s_gen_kva: ComplexArray
    meta: dict[str, float] = field(default_factory=dict)

    @property
    def p_loss_kw(self) -> FloatArray:
        return self.p_loss_line_kw + self.p_loss_gen_kw

    @property
    def q_net_kvar(self) -> FloatArray:
        """Q_net(t) = Q_load(t) − Q_C(t) vista desde la barra de 120 V (> 0 ⇒ en atraso)."""
        return self.s_load_kva.imag

    @property
    def pf_net(self) -> FloatArray:
        """Factor de potencia neto en la barra de carga, |P| / |S_net| (1.0 si Q_net = 0)."""
        return np.abs(self.s_load_kva.real) / np.maximum(np.abs(self.s_load_kva), 1e-12)

    @property
    def leading_mask(self) -> npt.NDArray[np.bool_]:
        """Horas con factor de potencia neto en adelanto (sobrecompensación, Q_net < 0)."""
        return self.q_net_kvar < -LAGGING_TOL_KVAR

    @property
    def s_loss_kva(self) -> ComplexArray:
        return self.p_loss_kw + 1j * self.q_loss_kvar

    @property
    def daily_energy_loss_kwh(self) -> float:
        return float(np.sum(self.p_loss_kw) * C.HOUR_DURATION_H)

    @property
    def daily_energy_served_kwh(self) -> float:
        return float(np.sum(self.s_load_kva.real) * C.HOUR_DURATION_H)

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "hour": self.hours,
                "Q_C_kvar": self.q_c_kvar,
                "P_load_kW": self.s_load_kva.real,
                "Q_load_net_kvar": self.s_load_kva.imag,
                "pf_net": self.pf_net,
                "pf_net_estado": np.where(self.leading_mask, "adelanto", "atraso"),
                "I_load_A": np.abs(self.i_load),
                "I_line_A": np.abs(self.i_line),
                "I_line_deg": np.degrees(np.angle(self.i_line)),
                "I_gen_A": np.abs(self.i_gen),
                "V_gen_V": np.abs(self.v_gen),
                "V_gen_deg": np.degrees(np.angle(self.v_gen)),
                "P_loss_line_kW": self.p_loss_line_kw,
                "P_loss_gen_kW": self.p_loss_gen_kw,
                "P_loss_kW": self.p_loss_kw,
                "Q_loss_kvar": self.q_loss_kvar,
                "P_gen_kW": self.s_gen_kva.real,
                "Q_gen_kvar": self.s_gen_kva.imag,
                "S_gen_kVA": np.abs(self.s_gen_kva),
                "pf_gen": np.abs(self.s_gen_kva.real) / np.maximum(np.abs(self.s_gen_kva), 1e-12),
            }
        )
