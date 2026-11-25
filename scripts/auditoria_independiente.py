"""Auditoría independiente (clean-room) del Problema 2 y del Problema 2.1 con banco fijo.

No importa nada de ``src/``: solo la biblioteca estándar (``math``, ``cmath``, ``csv``). Para cada caso
recalcula las 24 horas por dos caminos distintos, comprueba la conservación de potencia compleja y las
cuentas económicas, **deduce por su cuenta el banco fijo** (ventana de máximo cumplimiento de tensión y
mínimo de J dentro de ella) y compara todo con los CSV que genera el proyecto.

    Problema 2:   T1 = 1 kV : 13.2 kV,  T2 = 13.2 kV : 120 V  →  Q_C = 378.35 kvar
    Problema 2.1: T1 = 1 kV : 66 kV,    T2 = 66 kV : 120 V    →  Q_C = 87.25 kvar

Uso:
    python scripts/auditoria_independiente.py [--caso 2|2.1|todos] [--out outputs]
"""

from __future__ import annotations

import argparse
import cmath
import csv
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --- Datos del enunciado (transcritos aquí a propósito, sin leerlos de src/) ---------------
V0 = 120.0  # V, referencia angular 0°
R_GEN = 0.5  # Ω
Z_LINE = complex(80.0, 900.0)  # Ω
V_GEN_NOMINAL = 1_000.0  # V, primario de T1
TARIFF = 960.0  # COP/kWh
DAYS = 365
CAP_COST = 100_000.0  # COP/kvar
V_MIN, V_MAX = 950.0, 1_100.0
Q_SCAN_MAX = 2_000.0  # kvar, cota del barrido de Q_C
Q_SCAN_STEP = 0.1  # kvar

# hora, P1 [kW], fp1, P2 [kW], fp2 (Tabla 1; ambas cargas en atraso)
TABLE = (
    (1, 70, 0.85, 0, 0.75), (2, 68, 0.85, 0, 0.75), (3, 60, 0.85, 0, 0.75), (4, 50, 0.85, 0, 0.75),
    (5, 54, 0.85, 0, 0.75), (6, 61, 0.85, 0, 0.75), (7, 64, 0.85, 0, 0.75), (8, 66, 0.70, 0, 0.75),
    (9, 73, 0.70, 80, 0.75), (10, 78, 0.70, 80, 0.75), (11, 83, 0.70, 80, 0.75), (12, 85, 0.70, 80, 0.75),
    (13, 80, 0.70, 80, 0.75), (14, 76, 0.70, 80, 0.75), (15, 73, 0.70, 80, 0.75), (16, 70, 0.70, 80, 0.75),
    (17, 80, 0.85, 56, 0.75), (18, 95, 0.85, 56, 0.75), (19, 100, 0.85, 56, 0.75), (20, 90, 0.85, 56, 0.75),
    (21, 80, 0.85, 56, 0.75), (22, 75, 0.85, 56, 0.75), (23, 73, 0.85, 56, 0.75), (24, 71, 0.85, 56, 0.75),
)  # fmt: skip


@dataclass(frozen=True)
class Net:
    """Un caso de red: solo cambia la tensión de la línea (y con ella las relaciones de T1 y T2)."""

    name: str
    v_line: float  # V
    q_c: float  # kvar del banco fijo auditado
    csv_prefix: str  # prefijo de los CSV horarios del proyecto
    report_stem: str  # nombre base de los archivos de salida de la auditoría

    @property
    def n1(self) -> float:
        """T1 elevador: secundario / primario."""
        return self.v_line / V_GEN_NOMINAL

    @property
    def a2(self) -> float:
        """T2 reductor: primario / secundario."""
        return self.v_line / V0

    @property
    def z_ref(self) -> complex:
        """Impedancia serie vista por el generador: R_gen + Z_line / n1²."""
        return R_GEN + Z_LINE / self.n1**2

    @property
    def r_eq_line(self) -> float:
        """Resistencia total referida al lado de línea: R_line + R_gen·n1²."""
        return Z_LINE.real + R_GEN * self.n1**2

    @property
    def kappa(self) -> float:
        """P_loss [kW] = κ·(P² + Q_neto²) con P y Q en kW y kvar."""
        return self.r_eq_line * 1e3 / self.v_line**2

    @property
    def kv(self) -> str:
        return f"{self.v_line / 1e3:g} kV"


NET_P2 = Net("Problema 2", 13_200.0, 378.35, "p2", "auditoria_qc_fijo")
NET_P21 = Net("Problema 2.1", 66_000.0, 87.25, "p21", "auditoria_p21")
NETS = {"2": NET_P2, "2.1": NET_P21}
QC_AUDITED = NET_P2.q_c
QC_AUDITED_2_1 = NET_P21.q_c


@dataclass(frozen=True)
class Hour:
    """Resultado de una hora (potencias en kW/kvar/kVA, corrientes en A, tensiones en V)."""

    hour: int
    p_kw: float
    q_load_kvar: float
    q_net_kvar: float
    pf_net: float
    leading: bool
    i_load: complex
    i_line: complex
    i_gen: complex
    v_send: complex
    v_t1_prim: complex
    v_gen: complex
    p_loss_line_kw: float
    p_loss_gen_kw: float
    q_loss_kvar: float
    s_gen_kva: complex
    balance_error: float
    path_error: float

    @property
    def p_loss_kw(self) -> float:
        return self.p_loss_line_kw + self.p_loss_gen_kw

    @property
    def in_band(self) -> bool:
        return V_MIN <= abs(self.v_gen) <= V_MAX


def load_powers(p1: float, pf1: float, p2: float, pf2: float) -> tuple[float, float]:
    """P total y Q total de L1 + L2: Q_k = P_k·tan(arccos(fp_k)) (cargas en atraso ⇒ Q > 0)."""
    q1 = p1 * math.tan(math.acos(pf1))
    q2 = p2 * math.tan(math.acos(pf2))
    return p1 + p2, q1 + q2


LOADS = tuple((row[0], *load_powers(*row[1:])) for row in TABLE)  # (hora, P, Q)


def solve_hour(row: tuple[int, float, float, float, float], q_c: float, net: Net = NET_P2) -> Hour:
    hour, p1, pf1, p2, pf2 = row
    p, q = load_powers(p1, pf1, p2, pf2)
    s_net = complex(p, q - q_c)  # kVA; el banco entrega Q_C en la barra de 120 V

    # Camino A — de la carga hacia el generador, tramo por tramo
    i_load = (s_net * 1e3 / V0).conjugate()  # S = V·I*  ⇒  I = (S/V)*
    i_line = i_load / net.a2  # T2 ideal: la corriente baja a2 veces
    i_gen = i_line * net.n1  # T1 ideal: en el lado de 1 kV es n1 veces mayor
    v_recv = V0 * net.a2  # tensión de la línea en el extremo de la carga
    v_send = v_recv + i_line * Z_LINE
    v_t1 = v_send / net.n1
    v_gen = v_t1 + i_gen * R_GEN

    # Camino B — todo reflejado al lado del generador (1 kV)
    v0_ref = V0 * net.a2 / net.n1  # 1000∠0° V
    i_gen_b = (s_net * 1e3 / v0_ref).conjugate()
    v_gen_b = v0_ref + i_gen_b * net.z_ref
    path_error = max(abs(v_gen - v_gen_b) / abs(v_gen), abs(i_gen - i_gen_b) / abs(i_gen))

    p_loss_line = abs(i_line) ** 2 * Z_LINE.real / 1e3
    p_loss_gen = abs(i_gen) ** 2 * R_GEN / 1e3
    q_loss = abs(i_line) ** 2 * Z_LINE.imag / 1e3
    s_gen = v_gen * i_gen.conjugate() / 1e3  # potencia que entrega la fuente
    s_sum = s_net + complex(p_loss_line + p_loss_gen, q_loss)
    return Hour(
        hour=hour,
        p_kw=p,
        q_load_kvar=q,
        q_net_kvar=s_net.imag,
        pf_net=p / abs(s_net),
        leading=s_net.imag < 0,
        i_load=i_load,
        i_line=i_line,
        i_gen=i_gen,
        v_send=v_send,
        v_t1_prim=v_t1,
        v_gen=v_gen,
        p_loss_line_kw=p_loss_line,
        p_loss_gen_kw=p_loss_gen,
        q_loss_kvar=q_loss,
        s_gen_kva=s_gen,
        balance_error=abs(s_gen - s_sum) / abs(s_gen),
        path_error=path_error,
    )


def solve_day(q_c: float, net: Net = NET_P2) -> list[Hour]:
    return [solve_hour(row, q_c, net) for row in TABLE]


def daily_loss_kwh(q_c: float, net: Net = NET_P2) -> float:
    """Energía perdida en el día: suma horaria de κ·(P² + (Q − Q_C)²); cada hora dura 1 h."""
    return net.kappa * sum(p * p + (q - q_c) ** 2 for _, p, q in LOADS)


def annual_cost(q_c: float, net: Net = NET_P2) -> float:
    """J(Q_C) = OPEX anual de pérdidas + CAPEX del banco [COP]."""
    return daily_loss_kwh(q_c, net) * TARIFF * DAYS + CAP_COST * q_c


def hours_in_band(q_c: float, net: Net = NET_P2) -> int:
    """Horas con V_MIN ≤ |V_gen| ≤ V_MAX (cálculo con la impedancia reflejada al generador)."""
    v0_ref, z = V0 * net.a2 / net.n1, net.z_ref
    count = 0
    for _, p, q in LOADS:
        i_gen = complex(p, -(q - q_c)) * 1e3 / v0_ref
        count += V_MIN <= abs(v0_ref + i_gen * z) <= V_MAX
    return count


def golden_min(f, lo: float, hi: float, tol: float = 1e-9) -> float:
    """Mínimo de una función unimodal por sección áurea (sin SciPy)."""
    g = (math.sqrt(5.0) - 1.0) / 2.0
    c, d = hi - g * (hi - lo), lo + g * (hi - lo)
    while hi - lo > tol:
        if f(c) < f(d):
            hi, d = d, c
            c = hi - g * (hi - lo)
        else:
            lo, c = c, d
            d = lo + g * (hi - lo)
    return 0.5 * (lo + hi)


def _edge(net: Net, best: int, inside: float, outside: float, tol: float = 1e-10) -> float:
    """Frontera de la ventana entre un Q_C con ``best`` horas en banda y otro con menos (bisección)."""
    while abs(outside - inside) > tol:
        mid = 0.5 * (inside + outside)
        if hours_in_band(mid, net) == best:
            inside = mid
        else:
            outside = mid
    return inside


@dataclass(frozen=True)
class Design:
    """Banco fijo deducido de forma independiente."""

    best_hours: int
    windows: tuple[tuple[float, float], ...]
    q_free: float
    q_exact: float
    q_design: float


def derive_design(net: Net) -> Design:
    """Banco fijo de menor J entre los Q_C con el máximo de horas en banda (resolución 0.01 kvar)."""
    n = round(Q_SCAN_MAX / Q_SCAN_STEP)
    grid = [k * Q_SCAN_STEP for k in range(n + 1)]
    counts = [hours_in_band(x, net) for x in grid]
    best = max(counts)
    windows: list[tuple[float, float]] = []
    k = 0
    while k <= n:
        if counts[k] != best:
            k += 1
            continue
        j = k
        while j + 1 <= n and counts[j + 1] == best:
            j += 1
        lo = grid[k] if k == 0 else _edge(net, best, grid[k], grid[k - 1])
        hi = grid[j] if j == n else _edge(net, best, grid[j], grid[j + 1])
        windows.append((lo, hi))
        k = j + 1
    q_free = golden_min(lambda x: annual_cost(x, net), 0.0, Q_SCAN_MAX)
    # J es una parábola convexa: su mínimo en cada ventana es el punto de la ventana más cercano a q_free
    q_exact = min((min(max(q_free, lo), hi) for lo, hi in windows), key=lambda x: annual_cost(x, net))
    q_design = q_exact
    for candidate in (round(q_exact, 2), math.ceil(q_exact * 100 - 1e-9) / 100, math.floor(q_exact * 100 + 1e-9) / 100):
        if any(lo <= candidate <= hi for lo, hi in windows):
            q_design = candidate
            break
    return Design(best, tuple(windows), q_free, q_exact, q_design)


@dataclass
class AuditReport:
    net: Net
    q_c: float
    lines: list[str] = field(default_factory=list)
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    hours: list[Hour] = field(default_factory=list)
    design: Design | None = None

    @property
    def ok(self) -> bool:
        return all(passed for _, passed, _ in self.checks)

    def say(self, text: str = "") -> None:
        self.lines.append(text)

    def check(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append((name, passed, detail))
        self.say(f"  [{'OK' if passed else 'FALLA'}] {name}: {detail}")

    @property
    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def cop(value: float) -> str:
    if not math.isfinite(value):
        return "infinito"
    body = f"{abs(value):,.0f}".replace(",", ".")
    return f"{'-' if value < 0 else ''}$ {body} COP"


def polar(z: complex, unit: str, d: int = 3) -> str:
    return f"{abs(z):,.{d}f} {unit} ∠ {math.degrees(cmath.phase(z)):+.3f}°"


def compare_with_csv(path: Path, hours: list[Hour]) -> float | None:
    """Mayor diferencia relativa entre la auditoría y un CSV horario del proyecto (None si no existe)."""
    if not path.exists():
        return None
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    worst = 0.0
    for row, h in zip(rows, hours, strict=True):
        pairs = (
            ("Q_load_net_kvar", h.q_net_kvar),
            ("pf_net", h.pf_net),
            ("I_load_A", abs(h.i_load)),
            ("I_line_A", abs(h.i_line)),
            ("I_gen_A", abs(h.i_gen)),
            ("V_gen_V", abs(h.v_gen)),
            ("V_gen_deg", math.degrees(cmath.phase(h.v_gen))),
            ("P_loss_line_kW", h.p_loss_line_kw),
            ("P_loss_gen_kW", h.p_loss_gen_kw),
            ("P_loss_kW", h.p_loss_kw),
            ("Q_loss_kvar", h.q_loss_kvar),
            ("P_gen_kW", h.s_gen_kva.real),
            ("Q_gen_kvar", h.s_gen_kva.imag),
        )
        for column, mine in pairs:
            theirs = float(row[column])
            worst = max(worst, abs(theirs - mine) / max(abs(mine), 1e-12))
    return worst


def run_audit(q_c: float | None = None, out_dir: Path | None = None, net: Net = NET_P2) -> AuditReport:
    """Audita un caso. ``q_c`` es el banco que usa el proyecto (por defecto, el registrado en ``net``)."""
    q_c = net.q_c if q_c is None else q_c
    rep = AuditReport(net, q_c)
    base, day = solve_day(0.0, net), solve_day(q_c, net)
    rep.hours = day
    say = rep.say

    say("=" * 100)
    say(f"  AUDITORÍA INDEPENDIENTE — {net.name} con banco fijo Q_C = {q_c:g} kvar (sin importar src/)")
    say("=" * 100)
    say(f"  T1 1 kV : {net.kv} → n1 = {net.n1:g}   |   T2 {net.kv} : 120 V → a2 = {net.a2:g}")
    say(f"  Tensión de la carga referida al generador: 120·a2/n1 = {V0 * net.a2 / net.n1:,.4f} V")
    say(
        f"  Línea reflejada al generador: Z_line/n1² = {(Z_LINE / net.n1**2).real:.6f} + j{(Z_LINE / net.n1**2).imag:.6f} Ω"
    )
    say(f"  Impedancia vista por el generador: R_gen + Z_line/n1² = {net.z_ref.real:.6f} + j{net.z_ref.imag:.6f} Ω")
    say(f"  Resistencia total referida a {net.kv}: 80 + 0.5·{net.n1:g}² = {net.r_eq_line:,.2f} Ω")
    say(f"  Corrientes: I_line = I_load / {net.a2:g}   ·   I_gen = {net.n1:g} · I_line = I_load / {net.a2 / net.n1:g}")
    say()
    say("  Hora |   P    Q_carga   Q_neto  fp_neto     | I_load     I_line   I_gen    | |V_gen|    áng     banda | "
        "P_loss (línea + gen)      Q_loss   |S_gen|")  # fmt: skip
    say("       |  [kW]  [kvar]    [kvar]              | [A]        [A]      [A]      | [V]        [°]           | "
        "[kW]                      [kvar]   [kVA]")  # fmt: skip
    for h in day:
        say(
            f"  {h.hour:>4} | {h.p_kw:5.0f} {h.q_load_kvar:8.3f} {h.q_net_kvar:9.3f}  {h.pf_net:.4f} "
            f"{'ad.' if h.leading else 'at.'} | {abs(h.i_load):9.3f} {abs(h.i_line):8.4f} {abs(h.i_gen):8.3f} | "
            f"{abs(h.v_gen):9.4f} {math.degrees(cmath.phase(h.v_gen)):+8.3f}  "
            f"{'sí' if h.in_band else 'NO':>3}  | {h.p_loss_kw:8.4f} ({h.p_loss_line_kw:.4f} + {h.p_loss_gen_kw:.4f}) "
            f"{h.q_loss_kvar:8.3f} {abs(h.s_gen_kva):8.3f}"
        )

    say()
    say("  Verificaciones físicas (24 horas)")
    worst_balance = max(h.balance_error for h in day)
    rep.check("Conservación de potencia compleja", worst_balance < 1e-12,
              f"máx |V_gen·I_gen* − (S_neto + S_pérdidas)| / |S_gen| = {worst_balance:.2e}")  # fmt: skip
    worst_path = max(h.path_error for h in day)
    rep.check("Dos caminos de cálculo coinciden", worst_path < 1e-12,
              f"tramo a tramo vs. impedancia reflejada al generador: {worst_path:.2e}")  # fmt: skip
    t1 = max(abs(h.v_t1_prim * h.i_gen.conjugate() - h.v_send * h.i_line.conjugate()) / abs(h.s_gen_kva * 1e3)
             for h in day)  # fmt: skip
    t2 = max(abs(V0 * net.a2 * h.i_line.conjugate() - V0 * h.i_load.conjugate()) / abs(h.s_gen_kva * 1e3) for h in day)
    rep.check("Transformadores ideales no crean ni pierden potencia", max(t1, t2) < 1e-12,
              f"T1: {t1:.2e} · T2: {t2:.2e}")  # fmt: skip
    kappa = net.kappa
    worst_formula = max(abs(h.p_loss_kw - kappa * (h.p_kw**2 + h.q_net_kvar**2)) / h.p_loss_kw for h in day)
    rep.check("Pérdidas = κ·(P² + Q_neto²)", worst_formula < 1e-12,
              f"κ = R_eq·1000/V_línea² = {kappa:.9e} kW/kVA² · desviación {worst_formula:.2e}")  # fmt: skip
    share = sum(h.p_loss_gen_kw for h in day) / sum(h.p_loss_kw for h in day)
    r_gen_ref = R_GEN * net.n1**2
    rep.check("Reparto de pérdidas generador/línea", abs(share - r_gen_ref / net.r_eq_line) < 1e-12,
              f"R_gen referida = {r_gen_ref:,.2f} Ω ⇒ {100 * share:.2f} % en el generador y "
              f"{100 * (1 - share):.2f} % en la línea")  # fmt: skip
    n_lead = sum(h.leading for h in day)
    expected_lead = sum(q_c > h.q_load_kvar for h in day)
    rep.check("Signo del factor de potencia", n_lead == expected_lead,
              f"{n_lead}/24 h en adelanto: las horas con Q_carga < Q_C = {q_c:g} kvar "
              f"(Q_carga entre {min(h.q_load_kvar for h in day):.3f} y {max(h.q_load_kvar for h in day):.3f} kvar)")  # fmt: skip

    say()
    say("  Horas clave")
    for k in (1, 4, 8, 12, 19):
        h = day[k - 1]
        say(f"    h{k:02d}: S_neto = {h.p_kw:.2f} {h.q_net_kvar:+.3f}j kVA · I_line = {polar(h.i_line, 'A', 4)} · "
            f"V_gen = {polar(h.v_gen, 'V')} · P_loss = {h.p_loss_kw:.4f} kW · "
            f"{'en banda' if h.in_band else 'FUERA de banda'}")  # fmt: skip

    e0, e1 = sum(h.p_loss_kw for h in base), sum(h.p_loss_kw for h in day)
    served = sum(h.p_kw for h in day)
    opex0, opex1 = e0 * TARIFF * DAYS, e1 * TARIFF * DAYS
    capex = CAP_COST * q_c
    saving = opex0 - opex1
    payback = capex / saving if saving > 0 else math.inf
    payback_txt = "no se recupera" if math.isinf(payback) else f"{payback * 365:.2f} días"
    say()
    say("  Totales diarios y anuales")
    say(f"    Energía servida                 = {served:,.1f} kWh/día")
    say(f"    Pérdidas con Q_C = 0            = {e0:,.4f} kWh/día = {e0 * DAYS:,.1f} kWh/año → "
        f"{cop(e0 * TARIFF)}/día → {cop(opex0)}/año")  # fmt: skip
    say(f"    Pérdidas con Q_C = {q_c:g}       = {e1:,.4f} kWh/día = {e1 * DAYS:,.1f} kWh/año → "
        f"{cop(e1 * TARIFF)}/día → {cop(opex1)}/año")  # fmt: skip
    say(f"      en la línea (80 Ω)            = {sum(h.p_loss_line_kw for h in day):,.4f} kWh/día")
    say(f"      junto al generador (0.5 Ω)    = {sum(h.p_loss_gen_kw for h in day):,.4f} kWh/día")
    say(f"    CAPEX = {q_c:g} kvar × 100 000    = {cop(capex)}")
    say(f"    J = OPEX + CAPEX                = {cop(opex1 + capex)}   (con Q_C = 0: {cop(opex0)})")
    say(f"    Ahorro anual frente a Q_C = 0   = {cop(saving)}")
    say(f"    Payback                         = {payback_txt}")
    for years in (1, 3, 5):
        say(f"    ROI a {years} año(s)                  = {100 * (saving * years - capex) / capex:,.1f} %")
    rep.check("Costo anual coherente", abs(annual_cost(q_c, net) - (opex1 + capex)) < 1e-4,
              f"J({q_c:g}) por la fórmula κ = {cop(annual_cost(q_c, net))}")  # fmt: skip

    say()
    say("  Dimensionamiento independiente del banco fijo")
    design = derive_design(net)
    rep.design = design
    q_mean = sum(q for _, _, q in LOADS) / 24
    q_closed = q_mean - CAP_COST / (2 * TARIFF * DAYS * kappa * 24)
    rep.check("Mínimo libre de J", abs(design.q_free - q_closed) < 1e-4,
              f"sección áurea {design.q_free:.5f} kvar = fórmula cerrada {q_closed:.5f} kvar → "
              f"J = {cop(annual_cost(design.q_free, net))}, {hours_in_band(design.q_free, net)}/24 h en banda")  # fmt: skip
    slope = (annual_cost(q_c + 1e-3, net) - annual_cost(q_c - 1e-3, net)) / 2e-3
    say(f"    dJ/dQ_C en {q_c:g} kvar = {slope:,.0f} COP por kvar")
    say(f"    J({q_c:g}) / J(mínimo libre) = {annual_cost(q_c, net) / annual_cost(design.q_free, net):.4f}  ·  "
        f"J({q_c:g}) / J(0) = {annual_cost(q_c, net) / annual_cost(0.0, net):.4f}")  # fmt: skip
    windows = " ∪ ".join(f"[{lo:.4f}, {hi:.4f}]" for lo, hi in design.windows)
    say(f"    Máximo de horas en banda con un banco fijo (barrido 0–{Q_SCAN_MAX:g} kvar cada {Q_SCAN_STEP:g}): "
        f"{design.best_hours}/24")  # fmt: skip
    say(f"    Se alcanza para Q_C en {windows} kvar.")
    say(
        f"    Mínimo de J dentro de esa ventana: {design.q_exact:.6f} kvar → banco deducido {design.q_design:.2f} kvar."
    )
    n_in = sum(h.in_band for h in day)
    in_window = any(lo - 1e-9 <= q_c <= hi + 1e-9 for lo, hi in design.windows)
    rep.check("El banco del proyecto está en la ventana de máximo cumplimiento", in_window and n_in == design.best_hours,
              f"{n_in}/24 h en banda; fuera: {[h.hour for h in day if not h.in_band]}")  # fmt: skip
    rep.check("El banco del proyecto coincide con el deducido aquí", abs(q_c - design.q_design) < 1e-9,
              f"proyecto {q_c:g} kvar · auditoría {design.q_design:.2f} kvar")  # fmt: skip
    margins = [(min(abs(h.v_gen) - V_MIN, V_MAX - abs(h.v_gen)), h) for h in day if h.in_band]
    if margins:
        margin, tight = min(margins, key=lambda m: m[0])
        limit = "950 V" if abs(tight.v_gen) - V_MIN < V_MAX - abs(tight.v_gen) else "1100 V"
        say(f"    Margen mínimo dentro de la banda: hora {tight.hour}, |V_gen| = {abs(tight.v_gen):.4f} V "
            f"({margin:.4f} V respecto a {limit})")  # fmt: skip
    for h in day:
        if not h.in_band:
            low = abs(h.v_gen) < V_MIN
            gap = V_MIN - abs(h.v_gen) if low else abs(h.v_gen) - V_MAX
            say(f"    Hora {h.hour} fuera de banda: |V_gen| = {abs(h.v_gen):.3f} V ({gap:.3f} V "
                f"{'por debajo de 950 V' if low else 'por encima de 1100 V'})")  # fmt: skip
    n_base = sum(h.in_band for h in base)
    say(f"    Sin capacitor: {n_base}/24 h en banda, |V_gen| entre {min(abs(h.v_gen) for h in base):.3f} y "
        f"{max(abs(h.v_gen) for h in base):.3f} V")  # fmt: skip

    out = out_dir if out_dir is not None else ROOT / "outputs"
    say()
    say("  Contraste con los CSV generados por el proyecto")
    for name, hours in (
        (f"{net.csv_prefix}_sin_capacitor_horario.csv", base),
        (f"{net.csv_prefix}_fijo_economico_horario.csv", day),
    ):
        worst = compare_with_csv(out / name, hours)
        if worst is None:
            say(f"    {name}: no existe todavía (ejecute scripts/run_full_analysis.py)")
        else:
            rep.check(f"{name} coincide con la auditoría", worst < 1e-9, f"mayor diferencia relativa {worst:.2e}")

    say()
    say(f"  RESULTADO: {'todas las verificaciones pasan' if rep.ok else 'HAY VERIFICACIONES QUE FALLAN'} "
        f"({sum(p for _, p, _ in rep.checks)}/{len(rep.checks)})")  # fmt: skip
    return rep


def write_outputs(rep: AuditReport, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    txt = out_dir / f"{rep.net.report_stem}.txt"
    txt.write_text(rep.text, encoding="utf-8")
    table = out_dir / f"{rep.net.report_stem}_24h.csv"
    with table.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            ["hour", "P_kW", "Q_carga_kvar", "Q_C_kvar", "Q_neto_kvar", "fp_neto", "fp_estado", "I_load_A", "I_line_A",
             "I_line_deg", "I_gen_A", "V_gen_V", "V_gen_deg", "en_banda", "P_loss_line_kW", "P_loss_gen_kW",
             "P_loss_kW", "Q_loss_kvar", "P_gen_kW", "Q_gen_kvar", "S_gen_kVA", "error_conservacion_rel"]
        )  # fmt: skip
        for h in rep.hours:
            w.writerow(
                [h.hour, h.p_kw, h.q_load_kvar, rep.q_c, h.q_net_kvar, h.pf_net, "adelanto" if h.leading else "atraso",
                 abs(h.i_load), abs(h.i_line), math.degrees(cmath.phase(h.i_line)), abs(h.i_gen), abs(h.v_gen),
                 math.degrees(cmath.phase(h.v_gen)), h.in_band, h.p_loss_line_kw, h.p_loss_gen_kw, h.p_loss_kw,
                 h.q_loss_kvar, h.s_gen_kva.real, h.s_gen_kva.imag, abs(h.s_gen_kva), h.balance_error]
            )  # fmt: skip
    return [txt, table]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--caso", choices=["2", "2.1", "todos"], default="todos", help="Caso a auditar")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs", help="Carpeta con los CSV y de salida")
    args = parser.parse_args(argv)
    ok = True
    for key in ("2", "2.1") if args.caso == "todos" else (args.caso,):
        rep = run_audit(out_dir=args.out, net=NETS[key])
        print(rep.text)
        write_outputs(rep, args.out)
        ok = ok and rep.ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    raise SystemExit(main())
