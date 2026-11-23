"""Optimización técnico-económica del banco de capacitores (Problema 2).

Cuatro modos comparables:

1. ``feasibility_analysis``     — intervalos exactos de Q_C por hora con 950 ≤ |V_gen| ≤ 1100 V.
2. ``fixed_economic_optimum``   — mínimo de J(Q_C) = OPEX anual + CAPEX (cerrado + numérico).
3. ``fixed_voltage_pareto``     — frontera de Pareto costo vs. violación de tensión (banco fijo).
4. ``switched_capacitor_bank``  — banco automático por pasos 100 % factible las 24 h.

Requisito operativo adicional (factor de potencia neto siempre en atraso, Q_net(t) = Q(t) − Q_C(t) ≥ 0):

5. ``fixed_lagging_optimum``     — banco fijo de mínimo costo con 0 ≤ Q_C ≤ min_t Q(t).
6. ``switched_lagging_bank``     — banco por pasos con 0 ≤ Q_C(t) ≤ Q(t) en cada hora.
7. ``lagging_voltage_limit``     — cota inferior exacta de |V_gen| alcanzable sin adelanto (teorema).

Base matemática (ver ``src.physics.circuit_solver``):

    |V_gen(t, Q_C)|² = a·Q_C² + b(t)·Q_C + c(t)        (parábola convexa, a > 0)
    P_loss(t, Q_C)   = κ·(P(t)² + (Q(t) − Q_C)²)  [kW]  con κ = R_eq·1000/13 200²

por lo que cada restricción horaria es una desigualdad cuadrática con solución cerrada.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.optimize import brentq, minimize_scalar

from src.domain.constants import QC_SEARCH_MAX_KVAR
from src.domain.models import (
    LAGGING_TOL_KVAR,
    CircuitResult,
    DemandProfile,
    FloatArray,
    NetworkParameters,
    Strategy,
)
from src.optimization.economics import EconomicSummary, build_economic_summary
from src.physics.circuit_solver import affine_voltage_model, daily_loss_quadratic, solve_problem2

# ==================================================================================
# Álgebra de intervalos
# ==================================================================================
EPS = 1e-9


@dataclass(frozen=True, slots=True)
class Interval:
    """Intervalo cerrado [lo, hi] de Q_C en kvar."""

    lo: float
    hi: float

    @property
    def width(self) -> float:
        return self.hi - self.lo

    def contains(self, x: float, tol: float = 1e-9) -> bool:
        return self.lo - tol <= x <= self.hi + tol

    def clip(self, x: float) -> float:
        return float(min(max(x, self.lo), self.hi))

    def intersect(self, other: Interval) -> Interval | None:
        lo, hi = max(self.lo, other.lo), min(self.hi, other.hi)
        return Interval(lo, hi) if hi >= lo - EPS else None

    def __str__(self) -> str:
        return f"[{self.lo:.3f}, {self.hi:.3f}]"


IntervalSet = tuple[Interval, ...]


def intersect_sets(a: Sequence[Interval], b: Sequence[Interval]) -> IntervalSet:
    out = [x for i, j in itertools.product(a, b) if (x := i.intersect(j)) is not None]
    return tuple(sorted(out, key=lambda iv: iv.lo))


def intersect_many(sets: Sequence[Sequence[Interval]]) -> IntervalSet:
    acc: IntervalSet = tuple(sets[0]) if sets else ()
    for s in sets[1:]:
        acc = intersect_sets(acc, s)
        if not acc:
            break
    return acc


def set_contains(intervals: Sequence[Interval], x: float, tol: float = 1e-9) -> bool:
    return any(iv.contains(x, tol) for iv in intervals)


def project_onto_set(intervals: Sequence[Interval], x: float) -> float:
    """Punto de un conjunto de intervalos más cercano a ``x`` (proyección euclídea)."""
    if not intervals:
        raise ValueError("Conjunto vacío")
    candidates = [iv.clip(x) for iv in intervals]
    return min(candidates, key=lambda c: abs(c - x))


def format_set(intervals: Sequence[Interval]) -> str:
    return " ∪ ".join(str(iv) for iv in intervals) if intervals else "∅"


# ==================================================================================
# Violación de tensión
# ==================================================================================
def voltage_violation(v_mag: npt.ArrayLike, params: NetworkParameters) -> FloatArray:
    """Distancia (V) de |V_gen| a la banda [V_min, V_max]; 0 si está dentro."""
    v = np.asarray(v_mag, float)
    return np.maximum(0.0, np.maximum(v - params.v_gen_max, params.v_gen_min - v))


# ==================================================================================
# 1. Diagnóstico exacto de factibilidad
# ==================================================================================
def _quadratic_roots(a: float, b: float, c: float) -> tuple[float, float] | None:
    """Raíces reales ordenadas de a·x² + b·x + c (a > 0), forma numéricamente estable."""
    disc = b * b - 4.0 * a * c
    if disc < 0:
        return None
    sq = math.sqrt(disc)
    qq = -0.5 * (b + math.copysign(sq, b))
    r1 = qq / a
    r2 = c / qq if qq != 0 else -b / (2 * a)
    return (min(r1, r2), max(r1, r2))


def analytic_hour_feasible_set(
    a: float, b: float, c: float, v_min: float, v_max: float, q_lo: float, q_hi: float
) -> IntervalSet:
    """{Q_C ∈ [q_lo, q_hi] : v_min² ≤ a·Q_C² + b·Q_C + c ≤ v_max²} en forma cerrada."""
    domain = Interval(q_lo, q_hi)
    upper = _quadratic_roots(a, b, c - v_max**2)
    if upper is None:
        return ()
    below_max = (Interval(*upper),)
    lower = _quadratic_roots(a, b, c - v_min**2)
    above_min: IntervalSet = (
        (Interval(-math.inf, math.inf),)
        if lower is None
        else (Interval(-math.inf, lower[0]), Interval(lower[1], math.inf))
    )
    return intersect_sets(intersect_sets(below_max, above_min), (domain,))


def numeric_hour_feasible_set(
    magnitude: callable,  # type: ignore[valid-type]
    v_min: float,
    v_max: float,
    q_lo: float,
    q_hi: float,
    n_grid: int = 40_001,
) -> IntervalSet:
    """Verificación independiente: malla densa + refinamiento de fronteras con ``brentq``."""
    q = np.linspace(q_lo, q_hi, n_grid)
    v = magnitude(q)
    inside = (v >= v_min) & (v <= v_max)
    if not inside.any():
        return ()

    def boundary(i: int) -> float:
        # frontera entre q[i] y q[i+1]: el cruce es con v_min o v_max
        v_i, v_j = v[i], v[i + 1]
        level = v_max if max(v_i, v_j) > v_max else v_min
        return float(brentq(lambda x: float(magnitude(np.array([x]))[0]) - level, q[i], q[i + 1], xtol=1e-12))

    out: list[Interval] = []
    changes = np.flatnonzero(np.diff(inside.astype(int)))
    start = q_lo if inside[0] else None
    for i in changes:
        if inside[i]:  # sale de la banda
            out.append(Interval(float(start), boundary(int(i))))  # type: ignore[arg-type]
            start = None
        else:  # entra a la banda
            start = boundary(int(i))
    if start is not None:
        out.append(Interval(float(start), q_hi))
    return tuple(out)


@dataclass(frozen=True, slots=True, eq=False)
class FeasibilityReport:
    hours: npt.NDArray[np.int64]
    hourly_sets: tuple[IntervalSet, ...]
    numeric_sets: tuple[IntervalSet, ...]
    global_set: IntervalSet
    conflicting_pairs: tuple[tuple[int, int], ...]
    max_numeric_deviation_kvar: float
    q_search_max: float

    @property
    def is_feasible(self) -> bool:
        return bool(self.global_set)

    @property
    def hourly_q_min(self) -> FloatArray:
        return np.array([s[0].lo if s else np.nan for s in self.hourly_sets])

    @property
    def hourly_q_max(self) -> FloatArray:
        return np.array([s[-1].hi if s else np.nan for s in self.hourly_sets])

    @property
    def conflict_hours(self) -> tuple[int, ...]:
        return tuple(sorted({h for pair in self.conflicting_pairs for h in pair}))

    @property
    def critical_pair(self) -> tuple[int, int] | None:
        """Par de horas con mayor separación entre sus conjuntos factibles."""
        if not self.conflicting_pairs:
            return None
        idx = {int(h): i for i, h in enumerate(self.hours)}

        def gap(pair: tuple[int, int]) -> float:
            sa, sb = self.hourly_sets[idx[pair[0]]], self.hourly_sets[idx[pair[1]]]
            return (
                min(max(ia.lo - ib.hi, ib.lo - ia.hi) for ia, ib in itertools.product(sa, sb))
                if sa and sb
                else math.inf
            )

        return max(self.conflicting_pairs, key=gap)

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for h, s, ns in zip(self.hours, self.hourly_sets, self.numeric_sets, strict=True):
            rows.append(
                {
                    "hour": int(h),
                    "n_intervalos": len(s),
                    "Q_min_kvar": s[0].lo if s else np.nan,
                    "Q_max_kvar": s[-1].hi if s else np.nan,
                    "rama_baja_lo": s[0].lo if s else np.nan,
                    "rama_baja_hi": s[0].hi if s else np.nan,
                    "rama_alta_lo": s[1].lo if len(s) > 1 else np.nan,
                    "rama_alta_hi": s[1].hi if len(s) > 1 else np.nan,
                    "conjunto_analitico": format_set(s),
                    "conjunto_numerico": format_set(ns),
                }
            )
        return pd.DataFrame(rows)


def feasibility_analysis(
    demand: DemandProfile,
    params: NetworkParameters | None = None,
    q_search_max: float = QC_SEARCH_MAX_KVAR,
    verify_numerically: bool = True,
) -> FeasibilityReport:
    """Diagnóstico exacto de los Q_C fijos que cumplen la banda de tensión cada hora."""
    params = params or NetworkParameters()
    model = affine_voltage_model(demand, params)
    a, b, c = model.quadratic
    sets: list[IntervalSet] = []
    num_sets: list[IntervalSet] = []
    max_dev = 0.0
    for t in range(demand.n_hours):
        s = analytic_hour_feasible_set(
            a, float(b[t]), float(c[t]), params.v_gen_min, params.v_gen_max, 0.0, q_search_max
        )
        sets.append(s)
        if verify_numerically:
            mag = lambda q, t=t: np.abs(model.A[t] + model.B * np.asarray(q, float))  # noqa: E731
            ns = numeric_hour_feasible_set(mag, params.v_gen_min, params.v_gen_max, 0.0, q_search_max)
            num_sets.append(ns)
            if len(ns) != len(s):
                max_dev = math.inf
            else:
                for i1, i2 in zip(s, ns, strict=True):
                    max_dev = max(max_dev, abs(i1.lo - i2.lo), abs(i1.hi - i2.hi))
        else:
            num_sets.append(())
    pairs = tuple(
        (int(demand.hours[i]), int(demand.hours[j]))
        for i, j in itertools.combinations(range(demand.n_hours), 2)
        if not intersect_sets(sets[i], sets[j])
    )
    return FeasibilityReport(
        hours=demand.hours,
        hourly_sets=tuple(sets),
        numeric_sets=tuple(num_sets),
        global_set=intersect_many(sets),
        conflicting_pairs=pairs,
        max_numeric_deviation_kvar=max_dev,
        q_search_max=q_search_max,
    )


# ==================================================================================
# Evaluación común de estrategias
# ==================================================================================
@dataclass(frozen=True, slots=True, eq=False)
class StrategyResult:
    strategy: Strategy
    label: str
    q_c_profile_kvar: FloatArray
    q_c_installed_kvar: float
    circuit: CircuitResult
    economics: EconomicSummary
    violation_v: FloatArray
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def v_gen_mag(self) -> FloatArray:
        return np.abs(self.circuit.v_gen)

    @property
    def max_violation_v(self) -> float:
        return float(np.max(self.violation_v))

    @property
    def rms_violation_v(self) -> float:
        return float(np.sqrt(np.mean(self.violation_v**2)))

    @property
    def hours_out_of_band(self) -> int:
        return int(np.count_nonzero(self.violation_v > 1e-6))

    @property
    def is_voltage_feasible(self) -> bool:
        return self.hours_out_of_band == 0

    @property
    def q_net_kvar(self) -> FloatArray:
        return self.circuit.q_net_kvar

    @property
    def pf_net(self) -> FloatArray:
        return self.circuit.pf_net

    @property
    def hours_leading(self) -> int:
        """Horas con fp neto en adelanto (Q_net < 0, sobrecompensación capacitiva)."""
        return int(np.count_nonzero(self.circuit.leading_mask))

    @property
    def is_always_lagging(self) -> bool:
        return self.hours_leading == 0

    @property
    def pf_status(self) -> str:
        n = self.circuit.hours.size
        return f"{n}/{n} h en atraso" if self.is_always_lagging else f"{self.hours_leading} h en adelanto"

    def summary_row(self) -> dict[str, object]:
        e = self.economics
        return {
            "Estrategia": self.label,
            "Q_C_instalado_kvar": self.q_c_installed_kvar,
            "I_line_max_A": float(np.max(np.abs(self.circuit.i_line))),
            "E_loss_kWh_dia": e.daily_loss_kwh,
            "OPEX_anual_COP": e.annual_loss_cost_cop,
            "CAPEX_COP": e.capex_cop,
            "Costo_total_anual_COP": e.total_annual_cost_cop,
            "Ahorro_anual_COP": e.annual_savings_cop,
            "Payback_dias": e.payback_days,
            "V_gen_min_V": float(self.v_gen_mag.min()),
            "V_gen_max_V": float(self.v_gen_mag.max()),
            "Horas_fuera_banda": self.hours_out_of_band,
            "Violacion_max_V": self.max_violation_v,
            "Violacion_RMS_V": self.rms_violation_v,
            "fp_neto_min": float(self.pf_net.min()),
            "fp_neto_max": float(self.pf_net.max()),
            "Horas_adelanto": self.hours_leading,
            "Estado_fp_24h": self.pf_status,
        }


def evaluate_strategy(
    demand: DemandProfile,
    params: NetworkParameters,
    q_c_profile: float | npt.ArrayLike,
    strategy: Strategy,
    label: str | None = None,
    q_c_installed: float | None = None,
    baseline_daily_loss_kwh: float | None = None,
    extra: dict[str, object] | None = None,
) -> StrategyResult:
    circuit = solve_problem2(demand, q_c_profile, params)
    installed = float(np.max(circuit.q_c_kvar)) if q_c_installed is None else float(q_c_installed)
    if baseline_daily_loss_kwh is None:
        baseline_daily_loss_kwh = solve_problem2(demand, 0.0, params).daily_energy_loss_kwh
    econ = build_economic_summary(installed, circuit.daily_energy_loss_kwh, baseline_daily_loss_kwh, params)
    return StrategyResult(
        strategy=strategy,
        label=label or strategy.value,
        q_c_profile_kvar=circuit.q_c_kvar,
        q_c_installed_kvar=installed,
        circuit=circuit,
        economics=econ,
        violation_v=voltage_violation(np.abs(circuit.v_gen), params),
        extra=extra or {},
    )


def total_annual_cost_fixed(q_c: npt.ArrayLike, demand: DemandProfile, params: NetworkParameters) -> FloatArray:
    """J(Q_C) vectorizado = 960·365·Σ_t κ(P² + (Q − Q_C)²) + 100 000·Q_C  [COP/año]."""
    q_c = np.asarray(q_c, float)
    kappa, q = daily_loss_quadratic(demand, params)
    p2 = np.sum(demand.p_total_kw**2)
    daily = kappa * (p2 + np.sum((q[None, :] - q_c.reshape(-1, 1)) ** 2, axis=1))
    annual = daily * params.energy_price_cop_per_kwh * params.days_per_year
    return (annual + params.capacitor_cost_cop_per_kvar * q_c.reshape(-1)).reshape(q_c.shape)


# ==================================================================================
# 2. Óptimo económico del banco fijo
# ==================================================================================
@dataclass(frozen=True, slots=True, eq=False)
class FixedEconomicResult:
    q_c_closed_form_kvar: float
    q_c_numeric_kvar: float
    derivative_at_optimum: float
    result: StrategyResult


def closed_form_fixed_optimum(demand: DemandProfile, params: NetworkParameters) -> float:
    """dJ/dQ_C = −2·c_e·κ·Σ(Q(t) − Q_C) + c_cap = 0  ⇒  Q_C* = mean(Q) − c_cap / (2·c_e·κ·N)."""
    kappa, q = daily_loss_quadratic(demand, params)
    c_e = params.energy_price_cop_per_kwh * params.days_per_year
    q_star = float(np.mean(q) - params.capacitor_cost_cop_per_kvar / (2.0 * c_e * kappa * len(q)))
    return max(q_star, 0.0)


def cost_derivative(q_c: float, demand: DemandProfile, params: NetworkParameters) -> float:
    kappa, q = daily_loss_quadratic(demand, params)
    c_e = params.energy_price_cop_per_kwh * params.days_per_year
    return float(-2.0 * c_e * kappa * np.sum(q - q_c) + params.capacitor_cost_cop_per_kvar)


def fixed_economic_optimum(
    demand: DemandProfile, params: NetworkParameters | None = None, q_search_max: float = QC_SEARCH_MAX_KVAR
) -> FixedEconomicResult:
    params = params or NetworkParameters()
    q_closed = closed_form_fixed_optimum(demand, params)
    res = minimize_scalar(
        lambda x: float(total_annual_cost_fixed(x, demand, params)),
        bounds=(0.0, q_search_max),
        method="bounded",
        options={"xatol": 1e-10},
    )
    q_num = float(res.x)
    result = evaluate_strategy(
        demand,
        params,
        q_closed,
        Strategy.FIXED_ECONOMIC,
        extra={"Q_C_numerico": q_num, "iteraciones": int(res.nfev)},
    )
    return FixedEconomicResult(
        q_c_closed_form_kvar=q_closed,
        q_c_numeric_kvar=q_num,
        derivative_at_optimum=cost_derivative(q_closed, demand, params),
        result=result,
    )


# ==================================================================================
# 3. Compromiso costo–tensión (Pareto) para banco fijo
# ==================================================================================
@dataclass(frozen=True, slots=True, eq=False)
class ParetoResult:
    grid: pd.DataFrame
    front: pd.DataFrame
    minimax: StrategyResult
    economic: StrategyResult
    feasible_optimum: StrategyResult | None
    feasibility: FeasibilityReport

    @property
    def recommended(self) -> StrategyResult:
        """Banco fijo recomendado: óptimo estrictamente factible si existe; si no, el minimax."""
        return self.feasible_optimum or self.minimax


def _violation_metrics(
    q_grid: FloatArray, demand: DemandProfile, params: NetworkParameters
) -> tuple[FloatArray, FloatArray]:
    model = affine_voltage_model(demand, params)
    v = np.abs(model.A[None, :] + model.B * q_grid[:, None])
    viol = voltage_violation(v, params)
    return viol.max(axis=1), np.sqrt((viol**2).mean(axis=1))


def pareto_front_mask(cost: FloatArray, violation: FloatArray) -> npt.NDArray[np.bool_]:
    """Puntos no dominados (minimizar ambos objetivos)."""
    order = np.lexsort((violation, cost))
    mask = np.zeros(len(cost), bool)
    best = math.inf
    for i in order:
        if violation[i] < best - 1e-12:
            mask[i] = True
            best = violation[i]
    return mask


def fixed_voltage_pareto(
    demand: DemandProfile,
    params: NetworkParameters | None = None,
    q_search_max: float = 800.0,
    grid_step_kvar: float = 0.25,
    feasibility: FeasibilityReport | None = None,
) -> ParetoResult:
    params = params or NetworkParameters()
    feas = feasibility or feasibility_analysis(demand, params, verify_numerically=False)
    baseline = solve_problem2(demand, 0.0, params).daily_energy_loss_kwh

    q_grid = np.arange(0.0, q_search_max + grid_step_kvar / 2, grid_step_kvar)
    cost = total_annual_cost_fixed(q_grid, demand, params)
    vmax, vrms = _violation_metrics(q_grid, demand, params)
    grid = pd.DataFrame(
        {"Q_C_kvar": q_grid, "Costo_total_anual_COP": cost, "Violacion_max_V": vmax, "Violacion_RMS_V": vrms}
    )
    front = grid[pareto_front_mask(cost, vmax)].reset_index(drop=True)

    # Minimax: malla densa + refinamiento local acotado
    i0 = int(np.argmin(vmax))
    lo, hi = max(q_grid[max(i0 - 2, 0)], 0.0), q_grid[min(i0 + 2, len(q_grid) - 1)]
    ref = minimize_scalar(
        lambda x: float(_violation_metrics(np.array([x]), demand, params)[0][0]),
        bounds=(lo, hi),
        method="bounded",
        options={"xatol": 1e-9},
    )
    q_minimax = float(ref.x) if ref.fun <= vmax[i0] else float(q_grid[i0])
    minimax = evaluate_strategy(
        demand, params, q_minimax, Strategy.FIXED_MIN_VIOLATION, baseline_daily_loss_kwh=baseline
    )
    econ = fixed_economic_optimum(demand, params).result

    feasible_opt: StrategyResult | None = None
    if feas.is_feasible:
        q_unc = closed_form_fixed_optimum(demand, params)
        candidates = [iv.clip(q_unc) for iv in feas.global_set]
        q_best = min(candidates, key=lambda x: float(total_annual_cost_fixed(x, demand, params)))
        feasible_opt = evaluate_strategy(
            demand,
            params,
            q_best,
            Strategy.FIXED_MIN_VIOLATION,
            label="Banco Fijo — Óptimo Estrictamente Factible",
            baseline_daily_loss_kwh=baseline,
        )
    return ParetoResult(
        grid=grid, front=front, minimax=minimax, economic=econ, feasible_optimum=feasible_opt, feasibility=feas
    )


# ==================================================================================
# 4. Banco automático por pasos (switched capacitor bank)
# ==================================================================================
COMMERCIAL_STEPS_KVAR: tuple[float, ...] = (50.0, 25.0, 20.0, 12.5, 10.0, 5.0, 2.5, 1.0)


@dataclass(frozen=True, slots=True, eq=False)
class SwitchedBankResult:
    result: StrategyResult
    step_kvar: float | None
    n_steps: int | None
    q_c_max_kvar: float
    q_c_max_lower_bound_kvar: float
    cost_curve: pd.DataFrame
    continuous_reference: StrategyResult | None

    @property
    def schedule(self) -> pd.DataFrame:
        r = self.result
        df = pd.DataFrame(
            {
                "hour": r.circuit.hours,
                "Q_C_kvar": r.q_c_profile_kvar,
                "V_gen_V": r.v_gen_mag,
                "P_loss_kW": r.circuit.p_loss_kw,
            }
        )
        if self.step_kvar:
            df.insert(2, "pasos_activos", np.rint(r.q_c_profile_kvar / self.step_kvar).astype(int))
        return df


def _dispatch_continuous(sets: Sequence[IntervalSet], q_target: FloatArray, q_max: float) -> FloatArray | None:
    """Q_C(t) = proyección de Q(t) (mín. pérdidas horarias) sobre F_t ∩ [0, Q_max]."""
    out = np.empty(len(sets))
    cap = (Interval(0.0, q_max),)
    for t, s in enumerate(sets):
        allowed = intersect_sets(s, cap)
        if not allowed:
            return None
        out[t] = project_onto_set(allowed, float(q_target[t]))
    return out


def _dispatch_discrete(sets: Sequence[IntervalSet], q_target: FloatArray, n_max: int, step: float) -> FloatArray | None:
    levels = np.arange(n_max + 1) * step
    out = np.empty(len(sets))
    for t, s in enumerate(sets):
        ok = [lv for lv in levels if set_contains(s, lv, tol=1e-7)]
        if not ok:
            return None
        out[t] = min(ok, key=lambda lv: abs(lv - q_target[t]))
    return out


def _annual_cost_of_profile(
    q_profile: FloatArray, q_installed: float, demand: DemandProfile, params: NetworkParameters
) -> float:
    kappa, q = daily_loss_quadratic(demand, params)
    daily = kappa * float(np.sum(demand.p_total_kw**2 + (q - q_profile) ** 2))
    return (
        daily * params.energy_price_cop_per_kwh * params.days_per_year
        + params.capacitor_cost_cop_per_kvar * q_installed
    )


def switched_capacitor_bank(
    demand: DemandProfile,
    params: NetworkParameters | None = None,
    step_kvar: float | None = 25.0,
    q_search_max: float = 800.0,
    feasibility: FeasibilityReport | None = None,
) -> SwitchedBankResult:
    """Banco automático: minimiza OPEX + CAPEX(Q_C_max) con 950 ≤ |V_gen(t)| ≤ 1100 V ∀t.

    - Despacho interno (por hora, convexo): para un Q_C_max dado, el Q_C(t) óptimo es la
      proyección de Q(t) (compensación total ⇒ mínimas pérdidas) sobre el conjunto factible.
    - Problema externo (1-D): barrido fino de Q_C_max + ``minimize_scalar`` acotado.
    - Si ``step_kvar`` no es None se usan pasos discretos k·step; si con ese paso no existe
      despacho 100 % factible se prueba automáticamente el siguiente paso comercial menor.
    """
    params = params or NetworkParameters()
    feas = feasibility or feasibility_analysis(demand, params, verify_numerically=False)
    if any(len(s) == 0 for s in feas.hourly_sets):
        raise ValueError("Hay horas sin ningún Q_C que cumpla la banda de tensión: problema infactible")
    q_target = demand.q_total_kvar
    sets = feas.hourly_sets
    lower_bound = float(max(min(iv.lo for iv in s) for s in sets))
    baseline = solve_problem2(demand, 0.0, params).daily_energy_loss_kwh

    # ---- Referencia continua (cota inferior ideal) ---------------------------------
    def cont_cost(q_max: float) -> float:
        prof = _dispatch_continuous(sets, q_target, q_max)
        return math.inf if prof is None else _annual_cost_of_profile(prof, q_max, demand, params)

    q_grid = np.arange(lower_bound, q_search_max, 0.25)
    costs = np.array([cont_cost(x) for x in q_grid])
    i0 = int(np.nanargmin(costs))
    lo, hi = q_grid[max(i0 - 1, 0)], q_grid[min(i0 + 1, len(q_grid) - 1)]
    ref = minimize_scalar(cont_cost, bounds=(lo, hi), method="bounded", options={"xatol": 1e-9})
    q_max_cont = float(ref.x) if ref.fun <= costs[i0] else float(q_grid[i0])
    prof_cont = _dispatch_continuous(sets, q_target, q_max_cont)
    assert prof_cont is not None
    continuous = evaluate_strategy(
        demand,
        params,
        prof_cont,
        Strategy.SWITCHED,
        label="Banco Automático — Control Continuo (ideal)",
        q_c_installed=q_max_cont,
        baseline_daily_loss_kwh=baseline,
    )
    cost_curve = pd.DataFrame({"Q_C_max_kvar": q_grid, "Costo_total_anual_COP": costs})

    if step_kvar is None:
        return SwitchedBankResult(continuous, None, None, q_max_cont, lower_bound, cost_curve, continuous)

    # ---- Banco discreto por pasos --------------------------------------------------
    steps_to_try = [step_kvar] + [s for s in COMMERCIAL_STEPS_KVAR if s < step_kvar]
    for step in steps_to_try:
        best: tuple[float, int, FloatArray] | None = None
        for n in range(math.ceil(lower_bound / step - 1e-9), int(q_search_max // step) + 1):
            prof = _dispatch_discrete(sets, q_target, n, step)
            if prof is None:
                continue
            cost = _annual_cost_of_profile(prof, n * step, demand, params)
            if best is None or cost < best[0] - 1e-6:
                best = (cost, n, prof)
        if best is not None:
            _, n_best, prof = best
            result = evaluate_strategy(
                demand,
                params,
                prof,
                Strategy.SWITCHED,
                label=f"Banco Automático — {n_best} × {step:g} kvar",
                q_c_installed=n_best * step,
                baseline_daily_loss_kwh=baseline,
                extra={"step_kvar": step, "n_steps": n_best},
            )
            return SwitchedBankResult(result, step, n_best, n_best * step, lower_bound, cost_curve, continuous)
    raise RuntimeError("No se encontró despacho discreto factible con los pasos comerciales")


# ==================================================================================
# 5–7. Requisito de factor de potencia neto en atraso (Q_net(t) ≥ 0 las 24 h)
# ==================================================================================
@dataclass(frozen=True, slots=True, eq=False)
class FixedLaggingResult:
    """Banco fijo de mínimo costo anual con 0 ≤ Q_C ≤ min_t Q(t) (nunca en adelanto)."""

    q_c_upper_bound_kvar: float
    binding_hour: int
    q_c_unconstrained_kvar: float
    q_c_closed_form_kvar: float
    q_c_numeric_kvar: float
    result: StrategyResult

    @property
    def bound_is_active(self) -> bool:
        return self.q_c_unconstrained_kvar > self.q_c_upper_bound_kvar


def fixed_lagging_optimum(demand: DemandProfile, params: NetworkParameters | None = None) -> FixedLaggingResult:
    """min J(Q_C) s.a. 0 ≤ Q_C ≤ min_t Q(t).

    J es una parábola convexa, por lo que el óptimo restringido es la proyección del óptimo libre
    (forma cerrada) sobre [0, min Q]; se verifica con ``minimize_scalar`` acotado.
    """
    params = params or NetworkParameters()
    q = demand.q_total_kvar
    i_min = int(np.argmin(q))
    bound = float(q[i_min])
    q_free = closed_form_fixed_optimum(demand, params)
    q_closed = float(min(max(q_free, 0.0), bound))
    res = minimize_scalar(
        lambda x: float(total_annual_cost_fixed(x, demand, params)),
        bounds=(0.0, bound),
        method="bounded",
        options={"xatol": 1e-10},
    )
    result = evaluate_strategy(
        demand,
        params,
        q_closed,
        Strategy.FIXED_LAGGING,
        extra={"Q_C_numerico": float(res.x), "Q_C_cota": bound, "hora_limitante": int(demand.hours[i_min])},
    )
    return FixedLaggingResult(
        q_c_upper_bound_kvar=bound,
        binding_hour=int(demand.hours[i_min]),
        q_c_unconstrained_kvar=q_free,
        q_c_closed_form_kvar=q_closed,
        q_c_numeric_kvar=float(res.x),
        result=result,
    )


@dataclass(frozen=True, slots=True, eq=False)
class SwitchedLaggingResult:
    """Banco automático por pasos con Q_C(t) = k(t)·paso ≤ Q(t) en las 24 h."""

    result: StrategyResult
    step_kvar: float
    n_steps: int
    cost_curve: pd.DataFrame

    @property
    def q_c_max_kvar(self) -> float:
        return self.n_steps * self.step_kvar

    @property
    def schedule(self) -> pd.DataFrame:
        r = self.result
        return pd.DataFrame(
            {
                "hour": r.circuit.hours,
                "Q_load_kvar": r.q_net_kvar + r.q_c_profile_kvar,
                "pasos_activos": np.rint(r.q_c_profile_kvar / self.step_kvar).astype(int),
                "Q_C_kvar": r.q_c_profile_kvar,
                "Q_net_kvar": r.q_net_kvar,
                "pf_net": r.pf_net,
                "V_gen_V": r.v_gen_mag,
                "P_loss_kW": r.circuit.p_loss_kw,
            }
        )


def lagging_dispatch(q_load: npt.ArrayLike, n_steps: int, step_kvar: float) -> FloatArray:
    """Q_C(t) = mayor múltiplo del paso ≤ min(Q(t), n·paso): mínimas pérdidas sin pasar a adelanto."""
    cap = np.minimum(np.asarray(q_load, float), n_steps * step_kvar)
    return np.floor(cap / step_kvar + 1e-12) * step_kvar


def switched_lagging_bank(
    demand: DemandProfile, params: NetworkParameters | None = None, step_kvar: float = 25.0
) -> SwitchedLaggingResult:
    """min OPEX + CAPEX(n·paso) s.a. Q_C(t) ∈ {0, paso, …, n·paso} y Q_C(t) ≤ Q(t) ∀t.

    Para un número de pasos ``n`` el despacho horario óptimo es el mayor nivel que no excede Q(t)
    (las pérdidas κ·(Q − Q_C)² decrecen al acercarse a Q); luego se barre ``n`` exhaustivamente.
    """
    if step_kvar <= 0:
        raise ValueError("El paso del banco debe ser positivo")
    params = params or NetworkParameters()
    q = demand.q_total_kvar
    baseline = solve_problem2(demand, 0.0, params).daily_energy_loss_kwh
    n_max = int(np.floor(q.max() / step_kvar + 1e-12))
    rows = []
    for n in range(n_max + 1):
        prof = lagging_dispatch(q, n, step_kvar)
        rows.append(
            {
                "n_pasos": n,
                "Q_C_max_kvar": n * step_kvar,
                "Costo_total_anual_COP": _annual_cost_of_profile(prof, n * step_kvar, demand, params),
            }
        )
    curve = pd.DataFrame(rows)
    n_best = int(curve.loc[curve["Costo_total_anual_COP"].idxmin(), "n_pasos"])
    result = evaluate_strategy(
        demand,
        params,
        lagging_dispatch(q, n_best, step_kvar),
        Strategy.SWITCHED_LAGGING,
        label=f"Banco Automático en Atraso — {n_best} × {step_kvar:g} kvar",
        q_c_installed=n_best * step_kvar,
        baseline_daily_loss_kwh=baseline,
        extra={"step_kvar": step_kvar, "n_steps": n_best},
    )
    return SwitchedLaggingResult(result, step_kvar, n_best, curve)


@dataclass(frozen=True, slots=True, eq=False)
class LaggingVoltageLimit:
    """Teorema: cota inferior exacta de |V_gen(t)| con fp neto en atraso (0 ≤ Q_C ≤ Q(t)).

    |V_gen|² es una parábola convexa en Q_C; su mínimo sobre [0, Q(t)] se obtiene recortando el
    vértice −b/(2a) al intervalo. Si esa cota supera 1100 V en alguna hora, ningún diseño (fijo o
    conmutado, continuo o discreto) puede cumplir la banda sin entrar en adelanto en esa hora.
    """

    hours: npt.NDArray[np.int64]
    q_load_kvar: FloatArray
    v_gen_no_cap: FloatArray
    v_gen_unity_pf: FloatArray
    v_gen_floor: FloatArray
    q_c_at_floor_kvar: FloatArray
    q_c_band_min_kvar: FloatArray
    lagging_feasible_sets: tuple[IntervalSet, ...]
    v_gen_max_allowed: float

    @property
    def worst_index(self) -> int:
        return int(np.argmax(self.v_gen_floor))

    @property
    def worst_hour(self) -> int:
        return int(self.hours[self.worst_index])

    @property
    def max_floor_v(self) -> float:
        """máx_t mín_{0 ≤ Q_C ≤ Q(t)} |V_gen(t, Q_C)| (1 438.03 V en la hora 12 con los datos del enunciado)."""
        return float(self.v_gen_floor[self.worst_index])

    @property
    def floor_is_unity_pf(self) -> npt.NDArray[np.bool_]:
        """True cuando la cota se alcanza justo en Q_net = 0 (fp = 1)."""
        return np.isclose(self.q_c_at_floor_kvar, self.q_load_kvar, rtol=0, atol=1e-9)

    @property
    def hours_band_reachable_lagging(self) -> int:
        return sum(1 for s in self.lagging_feasible_sets if s)

    @property
    def lagging_band_feasible(self) -> bool:
        return self.hours_band_reachable_lagging == len(self.hours)

    @property
    def q_net_required_kvar(self) -> FloatArray:
        """Q_net = Q − Q_C,mín(banda): negativo ⇒ la banda exige inyección capacitiva en adelanto."""
        return self.q_load_kvar - self.q_c_band_min_kvar

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "hour": self.hours,
                "Q_load_kvar": self.q_load_kvar,
                "V_gen_QC0_V": self.v_gen_no_cap,
                "V_gen_fp1_V": self.v_gen_unity_pf,
                "V_gen_min_en_atraso_V": self.v_gen_floor,
                "Q_C_en_minimo_kvar": self.q_c_at_floor_kvar,
                "banda_alcanzable_en_atraso": [bool(s) for s in self.lagging_feasible_sets],
                "Q_C_min_banda_kvar": self.q_c_band_min_kvar,
                "Q_net_requerido_banda_kvar": self.q_net_required_kvar,
                "fp_requerido_banda": [
                    "adelanto" if x < -LAGGING_TOL_KVAR else "atraso" for x in self.q_net_required_kvar
                ],
            }
        )


def lagging_voltage_limit(
    demand: DemandProfile, params: NetworkParameters | None = None, feasibility: FeasibilityReport | None = None
) -> LaggingVoltageLimit:
    params = params or NetworkParameters()
    feas = feasibility or feasibility_analysis(demand, params, verify_numerically=False)
    model = affine_voltage_model(demand, params)
    a, b, _ = model.quadratic
    q = demand.q_total_kvar
    q_at_floor = np.clip(-b / (2.0 * a), 0.0, q)
    lag_sets = tuple(intersect_sets(s, (Interval(0.0, float(qt)),)) for s, qt in zip(feas.hourly_sets, q, strict=True))
    return LaggingVoltageLimit(
        hours=demand.hours,
        q_load_kvar=q,
        v_gen_no_cap=model.magnitude(0.0),
        v_gen_unity_pf=model.magnitude(q),
        v_gen_floor=model.magnitude(q_at_floor),
        q_c_at_floor_kvar=q_at_floor,
        q_c_band_min_kvar=np.array([s[0].lo if s else np.nan for s in feas.hourly_sets]),
        lagging_feasible_sets=lag_sets,
        v_gen_max_allowed=params.v_gen_max,
    )


# ==================================================================================
# Sensibilidad: reactancia de línea crítica para que un banco FIJO sea factible
# ==================================================================================
def fixed_bank_feasible(
    demand: DemandProfile, params: NetworkParameters, q_search_max: float = QC_SEARCH_MAX_KVAR
) -> bool:
    return feasibility_analysis(demand, params, q_search_max, verify_numerically=False).is_feasible


@dataclass(frozen=True, slots=True, eq=False)
class ReactanceSensitivity:
    """Rangos de X_line (Ω) en los que existe un banco FIJO factible las 24 h."""

    feasible_ranges: IntervalSet
    scan: pd.DataFrame
    x_actual: float

    @property
    def x_critical_upper(self) -> float | None:
        """Mayor X_line con banco fijo factible (umbral relevante al reducir X desde 900 Ω)."""
        below = [iv for iv in self.feasible_ranges if iv.lo <= self.x_actual]
        return below[-1].hi if below else None

    @property
    def actual_is_feasible(self) -> bool:
        return set_contains(self.feasible_ranges, self.x_actual)


def _bisect_transition(
    demand: DemandProfile, params: NetworkParameters, x_feas: float, x_infeas: float, tol: float
) -> float:
    """Frontera entre un X factible y otro infactible (devuelve el lado factible)."""
    while abs(x_infeas - x_feas) > tol:
        mid = 0.5 * (x_feas + x_infeas)
        if fixed_bank_feasible(demand, params.with_line_reactance(mid)):
            x_feas = mid
        else:
            x_infeas = mid
    return x_feas


def line_reactance_sensitivity(
    demand: DemandProfile,
    params: NetworkParameters | None = None,
    x_max: float | None = None,
    scan_step: float = 5.0,
    tol: float = 1e-4,
) -> ReactanceSensitivity:
    """Barrido de X_line ∈ [0, x_max] + bisección exacta de cada transición factible/infactible.

    La factibilidad NO es monótona en X: con X → 0 el capacitor pierde capacidad de
    regulación (solo modifica la parte imaginaria de V_gen), y con X grande la dispersión
    de |V_gen| entre horas valle y pico supera el ancho de la banda.
    """
    params = params or NetworkParameters()
    x_max = x_max if x_max is not None else max(params.x_line, 1.0) * 1.5
    xs = np.arange(0.0, x_max + scan_step / 2, scan_step)
    rows = []
    for x in xs:
        rep = feasibility_analysis(demand, params.with_line_reactance(float(x)), verify_numerically=False)
        rows.append(
            {
                "X_line_ohm": float(x),
                "factible": rep.is_feasible,
                "ancho_ventana_kvar": sum(iv.width for iv in rep.global_set),
                "ventana_Q_C": format_set(rep.global_set),
            }
        )
    scan = pd.DataFrame(rows)
    flags = scan["factible"].to_numpy(bool)
    ranges: list[Interval] = []
    i = 0
    while i < len(xs):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(xs) and flags[j + 1]:
            j += 1
        lo = float(xs[i]) if i == 0 else _bisect_transition(demand, params, float(xs[i]), float(xs[i - 1]), tol)
        hi = (
            float(xs[j])
            if j == len(xs) - 1
            else _bisect_transition(demand, params, float(xs[j]), float(xs[j + 1]), tol)
        )
        ranges.append(Interval(lo, hi))
        i = j + 1
    return ReactanceSensitivity(tuple(ranges), scan, params.x_line)
