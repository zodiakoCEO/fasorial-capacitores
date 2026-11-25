"""Texto de las secciones «Análisis» (Problemas 1, 2 y 2.1) y de la «Comparación», compartido por el dashboard y el reporte.

Cada función devuelve una lista de viñetas en Markdown calculadas a partir de los resultados; no hay
cifras escritas a mano. Los símbolos se escriben sin guion bajo (Vgen, Iline, Qc) para que se lean igual
en Streamlit y en el reporte.
"""

from __future__ import annotations

import numpy as np

from src.domain.models import NetworkParameters
from src.optimization.capacitor_optimizer import format_set
from src.optimization.economics import EconomicSummary, format_cop
from src.optimization.pipeline import AnalysisBundle


def _hours(hours: list[int]) -> str:
    """Lista compacta de horas: [1, 2, 3, 8] → '1–3 y 8'."""
    if not hours:
        return "ninguna"
    runs: list[list[int]] = [[hours[0]]]
    for h in hours[1:]:
        if h == runs[-1][-1] + 1:
            runs[-1].append(h)
        else:
            runs.append([h])
    parts = [str(r[0]) if len(r) == 1 else f"{r[0]}–{r[-1]}" for r in runs]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " y " + parts[-1]


def problem1_analysis(b: AnalysisBundle) -> list[str]:
    p1, d, prm = b.problem1, b.demand, b.params
    i_mag = np.abs(p1.i_line)
    imax = int(np.argmax(i_mag))
    ratio = p1.daily_energy_loss_kwh / p1.daily_energy_served_kwh
    daily_cost = p1.daily_energy_loss_kwh * prm.energy_price_cop_per_kwh
    return [
        f"La corriente de línea llega a **{i_mag.max():,.1f} A** en la hora {imax + 1}: entregar "
        f"{d.p_total_kw[imax]:.0f} kW a 120 V exige miles de amperios, y esa misma corriente recorre los 80 Ω de la línea.",
        f"Las pérdidas del día suman **{p1.daily_energy_loss_kwh:,.0f} kWh** frente a "
        f"**{p1.daily_energy_served_kwh:,.0f} kWh** entregados: **{ratio:,.0f} veces** la energía útil "
        f"(eficiencia {100 / (1 + ratio):.3f} %).",
        f"El generador debe aportar hasta **{np.abs(p1.s_gen_kva).max() / 1e3:,.0f} MVA** y sostener hasta "
        f"**{np.abs(p1.v_gen).max() / 1e3:,.0f} kV**; casi todo es potencia reactiva de la línea "
        f"({p1.q_loss_kvar.sum() / max(p1.p_loss_kw.sum(), 1e-9):.2f} kvar por cada kW perdido, relación X/R = 900/80.5).",
        f"Costo de las pérdidas: {p1.daily_energy_loss_kwh:,.2f} kWh × {prm.energy_price_cop_per_kwh:g} COP/kWh = "
        f"**{format_cop(daily_cost)} por día** ({format_cop(daily_cost * prm.days_per_year)} por año).",
        "Conclusión: la red directa a 120 V no es operable; hay que transportar a mayor tensión (Problema 2).",
    ]


def problem2_analysis(b: AnalysisBundle) -> dict[str, list[str]]:
    """Análisis de las gráficas del banco fijo adoptado frente a «Sin capacitor (Qc = 0)»."""
    nc, ec, eco, prm, d, f = b.no_capacitor, b.economic.result, b.economic, b.params, b.demand, b.feasibility
    qc = eco.q_c_design_kvar
    hours = ec.circuit.hours
    v0, v1 = nc.v_gen_mag, ec.v_gen_mag
    out = [int(h) for h in hours[ec.violation_v > 1e-6]]
    low = [int(h) for h in hours[v1 < prm.v_gen_min - 1e-6]]
    high = [int(h) for h in hours[v1 > prm.v_gen_max + 1e-6]]
    inside = ec.violation_v <= 1e-6
    margin_low = np.where(inside, v1 - prm.v_gen_min, np.inf)
    margin_high = np.where(inside, prm.v_gen_max - v1, np.inf)
    k_low, k_high = int(np.argmin(margin_low)), int(np.argmin(margin_high))
    near_floor = [int(h) for h in hours[inside & (v1 - prm.v_gen_min < 5.0)]]
    idx = {int(h): i for i, h in enumerate(hours)}

    voltage = [
        f"Sin capacitor, |Vgen| va de {v0.min():,.1f} V a {v0.max():,.1f} V y está por encima de "
        f"{prm.v_gen_max:g} V las {nc.hours_out_of_band} horas: con corriente en atraso la caída en j900 Ω se suma a la "
        "tensión de la carga.",
        f"Con Qc = {qc:g} kvar, |Vgen| queda entre {v1.min():,.2f} V y {v1.max():,.2f} V y "
        f"**{24 - len(out)} de 24 horas** entran en la banda [{prm.v_gen_min:g}, {prm.v_gen_max:g}] V.",
    ]
    if near_floor:
        voltage.append(
            f"Horas valle ({_hours(near_floor)}): |Vgen| queda pegado al límite inferior, entre "
            f"{v1[[idx[h] for h in near_floor]].min():,.2f} V y {v1[[idx[h] for h in near_floor]].max():,.2f} V. "
            f"El margen mínimo es de {margin_low[k_low]:.4f} V en la hora {int(hours[k_low])}: esa hora es la que "
            f"fija el tamaño del banco, y con un kvar menos saldría de la banda."
        )
    voltage.append(
        f"Horas pico: el máximo es {v1.max():,.2f} V en la hora {int(hours[int(np.argmax(v1))])}, a "
        f"{margin_high[k_high]:.2f} V del límite superior."
    )
    for h in low + high:
        i = idx[h]
        side = "por debajo de" if h in low else "por encima de"
        limit = prm.v_gen_min if h in low else prm.v_gen_max
        voltage.append(
            f"**Hora {h}, fuera de banda:** |Vgen| = {v1[i]:,.2f} V, {ec.violation_v[i]:,.2f} V {side} {limit:g} V. "
            f"Esa hora solo admite Qc en {format_set(f.hourly_sets[i])} kvar; {qc:g} kvar cae en el hueco entre sus "
            "dos tramos, donde la sobrecompensación hunde la tensión."
        )
    if eco.band.window:
        voltage.append(
            f"Ningún banco fijo cumple las 24 horas (intersección {format_set(f.global_set)}). El máximo alcanzable es "
            f"{eco.band.hours_in_band}/24 horas, con Qc en {format_set(eco.band.window)} kvar; {qc:g} kvar es el extremo "
            "de menor costo de esa ventana."
        )
    q_net = ec.q_net_kvar
    voltage.append(
        f"El banco supera la demanda reactiva en las {ec.hours_leading} horas (Q de la carga máx. "
        f"{d.q_total_kvar.max():.1f} kvar): el flujo neto es capacitivo, de {q_net.max():,.1f} kvar a "
        f"{q_net.min():,.1f} kvar, y el factor de potencia neto queda **en adelanto entre {ec.pf_net.min():.3f} y "
        f"{ec.pf_net.max():.3f}**. La banda se alcanza precisamente por esa sobrecompensación."
    )

    i0, i1 = np.abs(nc.circuit.i_line), np.abs(ec.circuit.i_line)
    inverted = int(np.argmax(i1)) == int(np.argmin(d.p_total_kw)) and int(np.argmin(i1)) == int(np.argmax(d.p_total_kw))
    current = [
        f"Sin capacitor, |Iline| sigue a la carga: mínimo {i0.min():.3f} A (hora {int(hours[int(np.argmin(i0))])}) y "
        f"máximo {i0.max():.3f} A (hora {int(hours[int(np.argmax(i0))])}).",
        f"Con Qc = {qc:g} kvar {'el perfil se invierte: ' if inverted else ''}máximo {i1.max():.3f} A en la hora "
        f"{int(hours[int(np.argmax(i1))])}{' (la de menor carga)' if inverted else ''} y mínimo {i1.min():.3f} A en la "
        f"hora {int(hours[int(np.argmin(i1))])}{' (la de mayor carga)' if inverted else ''}. La corriente la domina el "
        "excedente capacitivo |Q − Qc|, que es mayor cuanto menos reactiva pide la carga.",
        f"La corriente sube en las 24 horas: el promedio pasa de {i0.mean():.3f} A a {i1.mean():.3f} A "
        f"(×{i1.mean() / i0.mean():.2f}) y el máximo de {i0.max():.3f} A a {i1.max():.3f} A (×{i1.max() / i0.max():.2f}). "
        f"Aun así es {np.abs(b.problem1.i_line).max() / i1.max():.0f} veces menor que el máximo del Problema 1.",
    ]

    c0, c1 = nc.circuit, ec.circuit
    e0, e1 = nc.economics, ec.economics
    share_gen = c1.p_loss_gen_kw.sum() / c1.p_loss_kw.sum()
    k_max, k_min = int(np.argmax(c1.p_loss_kw)), int(np.argmin(c1.p_loss_kw))
    losses = [
        f"El reparto es el mismo en todas las horas: {100 * share_gen:.2f} % en la resistencia del generador "
        f"(0.5 Ω, que referida a {prm.line_kv:g} kV vale {prm.r_gen * prm.n1**2:.2f} Ω) y {100 * (1 - share_gen):.2f} % en los "
        f"{prm.r_line:g} Ω de la línea.",
        f"Con Qc = {qc:g} kvar las pérdidas van de {c1.p_loss_kw.min():.2f} kW (hora {int(hours[k_min])}) a "
        f"{c1.p_loss_kw.max():.2f} kW (hora {int(hours[k_max])}); en esa hora se pierden {c1.p_loss_kw[k_max]:.1f} kW "
        f"para entregar {d.p_total_kw[k_max]:.0f} kW. Sin capacitor van de {c0.p_loss_kw.min():.2f} kW a "
        f"{c0.p_loss_kw.max():.2f} kW.",
        f"Energía perdida al día: **{e1.daily_loss_kwh:,.2f} kWh** ({c1.p_loss_line_kw.sum():,.2f} en la línea y "
        f"{c1.p_loss_gen_kw.sum():,.2f} en el generador) frente a {e0.daily_loss_kwh:,.2f} kWh sin capacitor: "
        f"×{e1.daily_loss_kwh / e0.daily_loss_kwh:.2f}. Equivale al "
        f"{100 * e1.daily_loss_kwh / c1.daily_energy_served_kwh:.1f} % de la energía entregada.",
        f"Costo de las pérdidas: {format_cop(e1.daily_loss_kwh * prm.energy_price_cop_per_kwh)} por día y "
        f"**{format_cop(e1.annual_loss_cost_cop)} por año** (sin capacitor: {format_cop(e0.annual_loss_cost_cop)} por "
        f"año). Con el banco ({format_cop(e1.capex_cop)}) el costo total anual es "
        f"**{format_cop(e1.total_annual_cost_cop)}**.",
        f"El banco no se paga con ahorro de pérdidas: frente a Qc = 0 las pérdidas cuestan "
        f"{format_cop(-e1.annual_savings_cop)} más por año. Lo que compra es regulación de tensión "
        f"({24 - len(out)}/24 horas en banda frente a {24 - nc.hours_out_of_band}/24). El mínimo de J sin exigir tensión "
        f"está en {eco.q_c_free_kvar:.2f} kvar ({format_cop(eco.free.economics.total_annual_cost_cop)} por año), pero "
        f"deja {eco.free.hours_out_of_band} horas fuera de banda.",
    ]
    return {
        "Tensión del generador |Vgen(t)|": voltage,
        "Corriente de línea |Iline(t)|": current,
        "Pérdidas Ploss(t)": losses,
    }


def _kv(prm: NetworkParameters) -> str:
    return f"{prm.line_kv:g} kV"


def problem21_analysis(b21: AnalysisBundle, b2: AnalysisBundle) -> dict[str, list[str]]:
    """Análisis exclusivo del Problema 2.1 (línea a 66 kV): efecto físico del cambio de tensión y banco nuevo."""
    p21, p2, d = b21.params, b2.params, b21.demand
    nc, eco = b21.no_capacitor, b21.economic
    ec = eco.result
    hours = ec.circuit.hours
    qc = eco.q_c_design_kvar
    kv21, kv2 = _kv(p21), _kv(p2)
    k = p21.n1 / p2.n1  # factor de elevación de la tensión de línea (66 / 13.2 = 5)
    z21, z2 = p21.z_gen_side, p2.z_gen_side
    zl21, zl2 = p21.z_line / p21.n1**2, p2.z_line / p2.n1**2
    peak = int(np.argmax(d.p_total_kw))
    i_gen_peak = abs(nc.circuit.i_gen[peak])
    drop21, drop2 = i_gen_peak * zl21.imag, i_gen_peak * zl2.imag

    change = [
        f"Las relaciones pasan a n₁ = {p21.n1:g} (T1 = {p21.t1_label}) y a₂ = {p21.a2:g} (T2 = {p21.t2_label}). Para la "
        f"misma potencia, la corriente de línea es Iload/{p21.a2:g}: **{k:g} veces menor** que a {kv2} "
        f"(Iload/{p2.a2:g}). La corriente del generador no cambia, porque la tensión referida al generador sigue siendo "
        f"V₀·a₂/n₁ = {abs(p21.v_load_gen_side):,.0f} V.",
        f"La línea 80 + j900 Ω, vista desde el generador, se divide por n₁²: a {kv21} vale "
        f"{zl21.real:.4f} + j{zl21.imag:.4f} Ω, frente a {zl2.real:.4f} + j{zl2.imag:.4f} Ω a {kv2} "
        f"(**{k**2:g} veces menor**). La impedancia total que ve el generador baja de {z2.real:.4f} + j{z2.imag:.4f} Ω "
        f"a {z21.real:.4f} + j{z21.imag:.4f} Ω.",
        f"Regulación de tensión: en la hora {int(hours[peak])} (carga máxima, Igen = {i_gen_peak:.1f} A) la caída en la "
        f"reactancia de la línea es de {drop21:.1f} V a {kv21}, frente a {drop2:,.1f} V a {kv2}. Sin capacitor, |Vgen| "
        f"queda entre {nc.v_gen_mag.min():,.1f} V y {nc.v_gen_mag.max():,.1f} V (a {kv2}: "
        f"{b2.no_capacitor.v_gen_mag.min():,.1f}–{b2.no_capacitor.v_gen_mag.max():,.1f} V).",
        f"Pérdidas: los 80 Ω de la línea casi desaparecen del balance. La resistencia del generador (0.5 Ω) referida a "
        f"{kv21} vale {p21.r_gen_line_side:,.0f} Ω frente a los {p21.r_line:g} Ω de la línea, así que el generador "
        f"disipa el {100 * p21.r_gen_line_side / p21.r_eq_line_side:.2f} % y la línea el "
        f"{100 * p21.r_line / p21.r_eq_line_side:.2f} % (a {kv2}: "
        f"{100 * p2.r_gen_line_side / p2.r_eq_line_side:.2f} % y {100 * p2.r_line / p2.r_eq_line_side:.2f} %).",
    ]

    v1 = ec.v_gen_mag
    out0 = [int(h) for h in hours[nc.violation_v > 1e-6]]
    out1 = [int(h) for h in hours[ec.violation_v > 1e-6]]
    margin_high = np.where(ec.violation_v <= 1e-6, p21.v_gen_max - v1, np.inf)
    k_bind = int(np.argmin(margin_high))
    free = eco.free
    bank = [
        f"Sin capacitor quedan fuera de banda {len(out0)} horas ({_hours(out0)}), todas por encima de "
        f"{p21.v_gen_max:g} V; la mayor violación es de {nc.max_violation_v:.2f} V. Son las horas con la industria en "
        "servicio y mayor demanda reactiva.",
        f"A {kv21} sí existe un banco fijo que cumple las 24 horas: la intersección de las ventanas horarias es "
        f"{format_set(b21.feasibility.global_set)} kvar. La cota inferior la impone la hora "
        f"{int(hours[k_bind])}, la de mayor carga.",
        f"El mínimo libre de J está en {eco.q_c_free_kvar:.2f} kvar y queda {eco.q_c_band_optimum_kvar - eco.q_c_free_kvar:.2f} "
        f"kvar por debajo de la ventana: dejaría {free.hours_out_of_band} hora fuera por {free.max_violation_v:.2f} V. "
        f"Como J es convexa, el banco de menor costo que cumple es el extremo inferior de la ventana, "
        f"{eco.q_c_band_optimum_kvar:.4f} kvar, que se adopta como **{qc:g} kvar**.",
        f"Con Qc = {qc:g} kvar, |Vgen| queda entre {v1.min():,.2f} V (hora {int(hours[int(np.argmin(v1))])}) y "
        f"{v1.max():,.2f} V (hora {int(hours[int(np.argmax(v1))])}): **{24 - len(out1)} de 24 horas en banda**. La hora "
        f"{int(hours[k_bind])} queda a {margin_high[k_bind]:.4f} V del límite superior; el límite inferior tiene "
        f"{v1.min() - p21.v_gen_min:.1f} V de holgura.",
        f"Exigir la banda cuesta {format_cop(ec.economics.total_annual_cost_cop - free.economics.total_annual_cost_cop)} "
        f"por año frente al mínimo libre de J: la restricción de tensión y el criterio económico prácticamente coinciden.",
    ]

    i0, i1 = np.abs(nc.circuit.i_line), np.abs(ec.circuit.i_line)
    up = [int(h) for h in hours[i1 > i0 + 1e-12]]
    current = [
        f"Sin capacitor, |Iline| va de {i0.min():.4f} A (hora {int(hours[int(np.argmin(i0))])}) a {i0.max():.4f} A (hora "
        f"{int(hours[int(np.argmax(i0))])}), con promedio de {i0.mean():.4f} A.",
        f"Con Qc = {qc:g} kvar va de {i1.min():.4f} A (hora {int(hours[int(np.argmin(i1))])}) a {i1.max():.4f} A (hora "
        f"{int(hours[int(np.argmax(i1))])}); el máximo baja {100 * (1 - i1.max() / i0.max()):.1f} % y el promedio "
        f"{100 * (1 - i1.mean() / i0.mean()):.1f} % (queda en {i1.mean():.4f} A).",
        f"El perfil conserva la forma de la demanda: el banco reduce la corriente en las horas de mayor carga y la "
        f"aumenta en {len(up)} horas valle ({_hours(up)}), donde entrega más reactiva de la que pide la carga."
        if up
        else "El banco reduce la corriente en las 24 horas.",
    ]

    lead = [int(h) for h in hours[ec.circuit.leading_mask]]
    lag = ~ec.circuit.leading_mask
    pf = [
        f"Sin capacitor el fp neto es el de la carga: {nc.pf_net.min():.3f} a {nc.pf_net.max():.3f}, en atraso.",
        f"Con Qc = {qc:g} kvar hay {int(lag.sum())} horas en atraso con fp entre {ec.pf_net[lag].min():.3f} y "
        f"{ec.pf_net[lag].max():.3f}, y {len(lead)} horas en adelanto ({_hours(lead)}) con fp entre "
        f"{ec.pf_net[~lag].min():.3f} y {ec.pf_net[~lag].max():.3f}."
        if lead and lag.any()
        else f"Con Qc = {qc:g} kvar el fp neto queda entre {ec.pf_net.min():.3f} y {ec.pf_net.max():.3f}.",
        f"El adelanto aparece porque el banco es fijo: {qc:g} kvar superan la demanda reactiva de las horas valle "
        f"(mínimo {d.q_total_kvar.min():.1f} kvar). En las horas pico compensa {100 * qc / d.q_total_kvar.max():.0f} % "
        f"de la reactiva y el fp sube de {nc.pf_net[peak]:.3f} a {ec.pf_net[peak]:.3f}.",
    ]

    c1 = ec.circuit
    e0, e1 = nc.economics, ec.economics
    k_max, k_min = int(np.argmax(c1.p_loss_kw)), int(np.argmin(c1.p_loss_kw))
    days = p21.days_per_year
    payback = "no se recupera" if not np.isfinite(e1.payback_days) else f"{e1.payback_days:.1f} días"
    losses = [
        f"Con Qc = {qc:g} kvar las pérdidas van de {c1.p_loss_kw.min():.3f} kW (hora {int(hours[k_min])}) a "
        f"{c1.p_loss_kw.max():.3f} kW (hora {int(hours[k_max])}); en esa hora {c1.p_loss_gen_kw[k_max]:.3f} kW se disipan "
        f"en el generador y {c1.p_loss_line_kw[k_max]:.3f} kW en la línea. Las pérdidas reactivas de la línea van de "
        f"{c1.q_loss_kvar.min():.3f} a {c1.q_loss_kvar.max():.3f} kvar.",
        f"Energía perdida: **{e1.daily_loss_kwh:,.2f} kWh/día** ({c1.p_loss_gen_kw.sum():,.2f} en el generador y "
        f"{c1.p_loss_line_kw.sum():,.2f} en la línea) = {e1.daily_loss_kwh * days:,.0f} kWh/año, frente a "
        f"{e0.daily_loss_kwh:,.2f} kWh/día sin capacitor ({-e1.loss_reduction_pct:+.1f} %). Equivale al "
        f"{100 * e1.daily_loss_kwh / c1.daily_energy_served_kwh:.2f} % de la energía entregada.",
        f"Costo de las pérdidas: {format_cop(e1.daily_loss_kwh * p21.energy_price_cop_per_kwh)} por día y "
        f"**{format_cop(e1.annual_loss_cost_cop)} por año** (sin capacitor: {format_cop(e0.annual_loss_cost_cop)}).",
        f"El banco cuesta {format_cop(e1.capex_cop)} y ahorra {format_cop(e1.annual_savings_cop)} por año: payback de "
        f"**{payback}** y ROI de {e1.roi_pct(1):,.0f} % / {e1.roi_pct(3):,.0f} % / {e1.roi_pct(5):,.0f} % a 1, 3 y 5 años. "
        f"El costo total anual J queda en **{format_cop(e1.total_annual_cost_cop)}**.",
        f"Límite del nivel de tensión: como el {100 * c1.p_loss_gen_kw.sum() / c1.p_loss_kw.sum():.2f} % de las pérdidas "
        f"está en la resistencia del generador (lado de 1 kV), subir aún más la tensión de la línea solo podría "
        f"recuperar el {100 * c1.p_loss_line_kw.sum() / c1.p_loss_kw.sum():.2f} % restante.",
    ]
    return {
        f"Efecto de elevar la línea de {kv2} a {kv21}": change,
        "Banco capacitivo y tensión |Vgen(t)|": bank,
        "Corriente de línea |Iline(t)|": current,
        "Factor de potencia neto": pf,
        "Pérdidas Ploss(t) y costo": losses,
    }


def comparison_synthesis(b2: AnalysisBundle, b21: AnalysisBundle) -> list[str]:
    """Síntesis técnica de las diferencias entre el Problema 2 y el Problema 2.1."""
    kv2, kv21 = _kv(b2.params), _kv(b21.params)
    r2, r21 = b2.economic.result, b21.economic.result
    n2, n21 = b2.no_capacitor, b21.no_capacitor
    e2, e21 = r2.economics, r21.economics
    i2, i21 = np.abs(r2.circuit.i_line), np.abs(r21.circuit.i_line)
    i2_0, i21_0 = np.abs(n2.circuit.i_line), np.abs(n21.circuit.i_line)
    g2 = r2.circuit.p_loss_gen_kw.sum() / r2.circuit.p_loss_kw.sum()
    g21 = r21.circuit.p_loss_gen_kw.sum() / r21.circuit.p_loss_kw.sum()

    def pay(e: EconomicSummary) -> str:
        return "no se recupera" if not np.isfinite(e.payback_days) else f"se recupera en {e.payback_days:.0f} días"

    return [
        f"**Banco.** A {kv2} ningún banco fijo cumple las 24 horas y el de máximo cumplimiento es de "
        f"{r2.q_c_installed_kvar:g} kvar ({24 - r2.hours_out_of_band}/24 h). A {kv21} basta un banco de "
        f"**{r21.q_c_installed_kvar:g} kvar** ({r21.q_c_installed_kvar / r2.q_c_installed_kvar:.2f} veces el anterior) "
        f"para cumplir **{24 - r21.hours_out_of_band}/24 h**.",
        f"**Corriente de línea.** Para la misma carga se divide por {b21.params.a2 / b2.params.a2:g} "
        f"(sin capacitor: {i2_0.max():.3f} A → {i21_0.max():.3f} A). Con cada banco, el máximo pasa de {i2.max():.3f} A a "
        f"{i21.max():.3f} A (÷{i2.max() / i21.max():.1f}) y el promedio de {i2.mean():.3f} A a {i21.mean():.3f} A, "
        f"porque a {kv2} el banco sobrecompensa y a {kv21} no.",
        f"**Tensión del generador.** Sin capacitor el máximo baja de {n2.v_gen_mag.max():,.0f} V a "
        f"{n21.v_gen_mag.max():,.0f} V. Con banco, a {kv2} |Vgen| queda en {r2.v_gen_mag.min():,.0f}–"
        f"{r2.v_gen_mag.max():,.0f} V con {r2.hours_out_of_band} hora fuera; a {kv21} en {r21.v_gen_mag.min():,.0f}–"
        f"{r21.v_gen_mag.max():,.0f} V sin horas fuera.",
        f"**Pérdidas.** Con banco pasan de {e2.daily_loss_kwh:,.1f} a {e21.daily_loss_kwh:,.1f} kWh/día "
        f"(÷{e2.daily_loss_kwh / e21.daily_loss_kwh:.1f}). Sin capacitor la mejora es menor, de "
        f"{n2.economics.daily_loss_kwh:,.1f} a {n21.economics.daily_loss_kwh:,.1f} kWh/día "
        f"(÷{n2.economics.daily_loss_kwh / n21.economics.daily_loss_kwh:.2f}): elevar la tensión solo reduce la parte "
        f"de la línea, y la del generador pasa de {100 * g2:.1f} % a {100 * g21:.1f} % del total.",
        f"**Costo.** J anual baja de {format_cop(e2.total_annual_cost_cop)} a {format_cop(e21.total_annual_cost_cop)} "
        f"(÷{e2.total_annual_cost_cop / e21.total_annual_cost_cop:.1f}). A {kv2} el banco {pay(e2)} (ahorro "
        f"{format_cop(e2.annual_savings_cop)}/año); a {kv21} {pay(e21)} (ahorro {format_cop(e21.annual_savings_cop)}/año).",
        f"**Factor de potencia.** A {kv2} el banco deja el fp en adelanto las {r2.hours_leading} horas "
        f"({r2.pf_net.min():.3f}–{r2.pf_net.max():.3f}). A {kv21} quedan {24 - r21.hours_leading} horas en atraso y "
        f"{r21.hours_leading} en adelanto, con fp entre {r21.pf_net.min():.3f} y {r21.pf_net.max():.3f}.",
        f"**Conclusión.** Con la línea a {kv21} la regulación de tensión y el mínimo costo dejan de estar en conflicto: "
        f"el banco que cumple la banda está a {b21.economic.q_c_design_kvar - b21.economic.q_c_free_kvar:.2f} kvar del "
        f"mínimo de J. A {kv2} los separaban {b2.economic.q_c_design_kvar - b2.economic.q_c_free_kvar:.2f} kvar.",
    ]


__all__ = ["comparison_synthesis", "problem1_analysis", "problem2_analysis", "problem21_analysis"]
