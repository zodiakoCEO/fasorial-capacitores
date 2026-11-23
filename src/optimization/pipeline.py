"""Orquestador: ejecuta todos los análisis y devuelve un paquete inmutable de resultados."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.domain.models import CircuitResult, DemandProfile, NetworkParameters, Strategy
from src.optimization.capacitor_optimizer import (
    FeasibilityReport,
    FixedEconomicResult,
    FixedLaggingResult,
    LaggingVoltageLimit,
    ParetoResult,
    ReactanceSensitivity,
    StrategyResult,
    SwitchedBankResult,
    SwitchedLaggingResult,
    evaluate_strategy,
    feasibility_analysis,
    fixed_economic_optimum,
    fixed_lagging_optimum,
    fixed_voltage_pareto,
    lagging_voltage_limit,
    line_reactance_sensitivity,
    switched_capacitor_bank,
    switched_lagging_bank,
)
from src.physics.circuit_solver import solve_problem1


@dataclass(frozen=True, slots=True, eq=False)
class AnalysisBundle:
    demand: DemandProfile
    params: NetworkParameters
    problem1: CircuitResult
    no_capacitor: StrategyResult
    feasibility: FeasibilityReport
    economic: FixedEconomicResult
    pareto: ParetoResult
    switched: SwitchedBankResult
    fixed_lagging: FixedLaggingResult
    switched_lagging: SwitchedLaggingResult
    lagging_limit: LaggingVoltageLimit
    sensitivity: ReactanceSensitivity | None

    @property
    def strategies(self) -> dict[Strategy, StrategyResult]:
        return {
            Strategy.NO_CAPACITOR: self.no_capacitor,
            Strategy.FIXED_ECONOMIC: self.economic.result,
            Strategy.FIXED_MIN_VIOLATION: self.pareto.recommended,
            Strategy.SWITCHED: self.switched.result,
            Strategy.FIXED_LAGGING: self.fixed_lagging.result,
            Strategy.SWITCHED_LAGGING: self.switched_lagging.result,
        }

    def comparison_table(self) -> pd.DataFrame:
        rows = [r.summary_row() for r in self.strategies.values()]
        if self.switched.continuous_reference is not None:
            rows.append(self.switched.continuous_reference.summary_row())
        return pd.DataFrame(rows)


def run_full_analysis(
    demand: DemandProfile | None = None,
    params: NetworkParameters | None = None,
    switched_step_kvar: float | None = 25.0,
    include_sensitivity: bool = True,
) -> AnalysisBundle:
    demand = demand or DemandProfile.default()
    params = params or NetworkParameters()
    feas = feasibility_analysis(demand, params)
    no_cap = evaluate_strategy(demand, params, 0.0, Strategy.NO_CAPACITOR)
    return AnalysisBundle(
        demand=demand,
        params=params,
        problem1=solve_problem1(demand, params),
        no_capacitor=no_cap,
        feasibility=feas,
        economic=fixed_economic_optimum(demand, params),
        pareto=fixed_voltage_pareto(demand, params, feasibility=feas),
        switched=switched_capacitor_bank(demand, params, step_kvar=switched_step_kvar, feasibility=feas),
        fixed_lagging=fixed_lagging_optimum(demand, params),
        switched_lagging=switched_lagging_bank(demand, params, step_kvar=switched_step_kvar or 25.0),
        lagging_limit=lagging_voltage_limit(demand, params, feasibility=feas),
        sensitivity=line_reactance_sensitivity(demand, params) if include_sensitivity else None,
    )
