"""Evaluación económica: OPEX de pérdidas, CAPEX del banco, payback, ROI y flujo de caja."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.domain.models import NetworkParameters

ROI_HORIZONS_YEARS: tuple[int, ...] = (1, 3, 5)


def annual_loss_cost_cop(daily_loss_kwh: float, params: NetworkParameters) -> float:
    """OPEX anual de pérdidas = E_loss_diaria · tarifa · 365."""
    return daily_loss_kwh * params.energy_price_cop_per_kwh * params.days_per_year


def capacitor_capex_cop(q_c_installed_kvar: float, params: NetworkParameters) -> float:
    """CAPEX = 100 000 COP/kvar · Q_C instalado."""
    return q_c_installed_kvar * params.capacitor_cost_cop_per_kvar


@dataclass(frozen=True, slots=True)
class EconomicSummary:
    """Indicadores económicos de una estrategia frente a la referencia Q_C = 0."""

    q_c_installed_kvar: float
    capex_cop: float
    daily_loss_kwh: float
    annual_loss_cost_cop: float
    baseline_daily_loss_kwh: float
    baseline_annual_loss_cost_cop: float

    @property
    def total_annual_cost_cop(self) -> float:
        """J = OPEX anual + CAPEX (función objetivo del enunciado)."""
        return self.annual_loss_cost_cop + self.capex_cop

    @property
    def daily_loss_reduction_kwh(self) -> float:
        return self.baseline_daily_loss_kwh - self.daily_loss_kwh

    @property
    def loss_reduction_pct(self) -> float:
        return 100.0 * self.daily_loss_reduction_kwh / self.baseline_daily_loss_kwh

    @property
    def annual_savings_cop(self) -> float:
        """Ahorro bruto anual en pérdidas frente a Q_C = 0."""
        return self.baseline_annual_loss_cost_cop - self.annual_loss_cost_cop

    @property
    def net_first_year_benefit_cop(self) -> float:
        return self.annual_savings_cop - self.capex_cop

    @property
    def payback_years(self) -> float:
        if self.capex_cop == 0:
            return 0.0
        if self.annual_savings_cop <= 0:
            return math.inf
        return self.capex_cop / self.annual_savings_cop

    @property
    def payback_months(self) -> float:
        return self.payback_years * 12.0

    @property
    def payback_days(self) -> float:
        return self.payback_years * 365.0

    def roi_pct(self, years: float) -> float:
        """ROI simple (sin descuento) = (ahorro acumulado − CAPEX) / CAPEX."""
        if self.capex_cop == 0:
            return math.inf if self.annual_savings_cop > 0 else 0.0
        return 100.0 * (self.annual_savings_cop * years - self.capex_cop) / self.capex_cop

    @property
    def roi_table(self) -> dict[int, float]:
        return {y: self.roi_pct(y) for y in ROI_HORIZONS_YEARS}

    def as_dict(self) -> dict[str, float]:
        out = {
            "Q_C_instalado_kvar": self.q_c_installed_kvar,
            "CAPEX_COP": self.capex_cop,
            "E_loss_diaria_kWh": self.daily_loss_kwh,
            "OPEX_perdidas_anual_COP": self.annual_loss_cost_cop,
            "Costo_total_anual_COP": self.total_annual_cost_cop,
            "Reduccion_perdidas_kWh_dia": self.daily_loss_reduction_kwh,
            "Reduccion_perdidas_pct": self.loss_reduction_pct,
            "Ahorro_anual_COP": self.annual_savings_cop,
            "Beneficio_neto_anio1_COP": self.net_first_year_benefit_cop,
            "Payback_meses": self.payback_months,
            "Payback_dias": self.payback_days,
        }
        out.update({f"ROI_{y}a_pct": v for y, v in self.roi_table.items()})
        return out


def build_economic_summary(
    q_c_installed_kvar: float,
    daily_loss_kwh: float,
    baseline_daily_loss_kwh: float,
    params: NetworkParameters,
) -> EconomicSummary:
    return EconomicSummary(
        q_c_installed_kvar=q_c_installed_kvar,
        capex_cop=capacitor_capex_cop(q_c_installed_kvar, params),
        daily_loss_kwh=daily_loss_kwh,
        annual_loss_cost_cop=annual_loss_cost_cop(daily_loss_kwh, params),
        baseline_daily_loss_kwh=baseline_daily_loss_kwh,
        baseline_annual_loss_cost_cop=annual_loss_cost_cop(baseline_daily_loss_kwh, params),
    )


def cumulative_cash_flow(
    summary: EconomicSummary, horizon_years: float = 5.0, points_per_year: int = 12
) -> pd.DataFrame:
    """Flujo de caja acumulado (sin descuento): −CAPEX en t=0 + ahorro lineal en el tiempo."""
    n = max(round(horizon_years * points_per_year), 1)
    t_years = np.linspace(0.0, horizon_years, n + 1)
    cum = -summary.capex_cop + summary.annual_savings_cop * t_years
    return pd.DataFrame({"anio": t_years, "mes": t_years * 12.0, "flujo_acumulado_COP": cum})


def format_cop(value: float, decimals: int = 0) -> str:
    """Formato de moneda colombiano: separador de miles '.', decimales ','."""
    if not math.isfinite(value):
        return "∞"
    sign = "-" if value < 0 else ""
    raw = f"{abs(value):,.{decimals}f}"
    raw = raw.replace(",", "§").replace(".", ",").replace("§", ".")
    return f"{sign}$ {raw} COP"


def format_number(value: float, decimals: int = 2) -> str:
    if not math.isfinite(value):
        return "∞"
    raw = f"{value:,.{decimals}f}"
    return raw.replace(",", "§").replace(".", ",").replace("§", ".")
