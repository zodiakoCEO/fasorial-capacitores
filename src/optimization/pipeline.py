"""Orquestador: ejecuta todos los análisis y devuelve un paquete inmutable de resultados.

El Problema 2 se presenta con dos estrategias: «Sin capacitor (Q_C = 0)» y «Banco fijo — óptimo
económico» (Q_C = 378.35 kvar con los datos del enunciado). El Problema 2.1 repite el análisis completo
con T1 = 1 kV : 66 kV y T2 = 66 kV : 120 V (Q_C = 87.25 kvar).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.domain.constants import LINE_VOLTAGE_2_1_V
from src.domain.models import CircuitResult, DemandProfile, NetworkParameters, Strategy
from src.optimization.capacitor_optimizer import (
    FeasibilityReport,
    FixedEconomicResult,
    ReactanceSensitivity,
    StrategyResult,
    evaluate_strategy,
    feasibility_analysis,
    fixed_bank_scan,
    fixed_economic_optimum,
    line_reactance_sensitivity,
)
from src.physics.circuit_solver import solve_problem1

CASE_2 = "Problema 2"
CASE_2_1 = "Problema 2.1"


@dataclass(frozen=True, slots=True, eq=False)
class AnalysisBundle:
    demand: DemandProfile
    params: NetworkParameters
    problem1: CircuitResult
    no_capacitor: StrategyResult
    feasibility: FeasibilityReport
    economic: FixedEconomicResult
    scan: pd.DataFrame
    sensitivity: ReactanceSensitivity | None
    name: str = CASE_2

    @property
    def title(self) -> str:
        """Nombre del caso con sus relaciones de transformación: 'Problema 2.1 (1kV:66kV / 66kV:120V)'."""
        return f"{self.name} ({self.params.t1_label} / {self.params.t2_label})"

    @property
    def strategies(self) -> dict[Strategy, StrategyResult]:
        return {
            Strategy.NO_CAPACITOR: self.no_capacitor,
            Strategy.FIXED_ECONOMIC: self.economic.result,
        }

    def comparison_table(self) -> pd.DataFrame:
        return pd.DataFrame([r.summary_row() for r in self.strategies.values()])


def run_full_analysis(
    demand: DemandProfile | None = None,
    params: NetworkParameters | None = None,
    include_sensitivity: bool = True,
    name: str = CASE_2,
) -> AnalysisBundle:
    demand = demand or DemandProfile.default()
    params = params or NetworkParameters()
    feas = feasibility_analysis(demand, params)
    return AnalysisBundle(
        demand=demand,
        params=params,
        problem1=solve_problem1(demand, params),
        no_capacitor=evaluate_strategy(demand, params, 0.0, Strategy.NO_CAPACITOR),
        feasibility=feas,
        economic=fixed_economic_optimum(demand, params, feasibility=feas),
        scan=fixed_bank_scan(demand, params, feas),
        sensitivity=line_reactance_sensitivity(demand, params) if include_sensitivity else None,
        name=name,
    )


def params_2_1(base: NetworkParameters | None = None) -> NetworkParameters:
    """Parámetros del Problema 2.1: los del enunciado con la línea a 66 kV (n1 = 66, a2 = 550)."""
    return (base or NetworkParameters()).with_line_voltage(LINE_VOLTAGE_2_1_V)


def run_problem_2_1(
    demand: DemandProfile | None = None,
    params: NetworkParameters | None = None,
    include_sensitivity: bool = False,
) -> AnalysisBundle:
    """Análisis completo del Problema 2.1 (misma demanda y economía; solo cambian T1 y T2)."""
    return run_full_analysis(demand, params_2_1(params), include_sensitivity, name=CASE_2_1)
