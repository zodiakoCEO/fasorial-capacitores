"""Constantes físicas y económicas del caso de estudio (NO alterar: especificación oficial).

Todas las magnitudes eléctricas están en unidades SI (V, A, Ω) salvo que el nombre
indique explícitamente lo contrario (``_KW``, ``_KVAR``, ``_KVA``, ``_KWH``).
"""

from __future__ import annotations

from typing import Final

# --- Parámetros eléctricos ---------------------------------------------------------
V0_LOAD: Final[complex] = complex(120.0, 0.0)
"""Tensión fasorial RMS en la carga (referencia angular 0°)."""

R_GEN_OHM: Final[float] = 0.5
"""Resistencia serie junto al generador."""

Z_LINE_OHM: Final[complex] = complex(80.0, 900.0)
"""Impedancia de la línea de distribución."""

# --- Transformadores ideales (Problema 2) -----------------------------------------
T1_PRIMARY_V: Final[float] = 1_000.0
T1_SECONDARY_V: Final[float] = 13_200.0
T2_PRIMARY_V: Final[float] = 13_200.0
T2_SECONDARY_V: Final[float] = 120.0

# --- Economía ----------------------------------------------------------------------
ENERGY_PRICE_COP_PER_KWH: Final[float] = 960.0
DAYS_PER_YEAR: Final[int] = 365
CAPACITOR_COST_COP_PER_KVAR: Final[float] = 100_000.0

# --- Restricción operativa de tensión en el generador (Problema 2) -----------------
V_GEN_MIN_V: Final[float] = 950.0
V_GEN_MAX_V: Final[float] = 1_100.0

# --- Diseño adoptado: banco fijo del Problema 2 -----------------------------------
QC_FIXED_ECONOMIC_KVAR: Final[float] = 378.35
"""Q_C instalado del «Banco fijo — óptimo económico» (kvar).

Es el banco fijo de menor costo anual J entre los que mantienen |V_gen| dentro de [950, 1100] V
el mayor número posible de horas (23 de 24); ``fixed_economic_optimum`` lo deduce de los datos y
``tests/test_optimization.py`` comprueba que coincide con este valor.
"""

# --- Problema 2.1: misma red con la línea a 66 kV ---------------------------------
LINE_VOLTAGE_2_1_V: Final[float] = 66_000.0
"""Tensión de línea del Problema 2.1: T1 = 1 kV : 66 kV y T2 = 66 kV : 120 V."""

QC_FIXED_ECONOMIC_2_1_KVAR: Final[float] = 87.25
"""Q_C del «Banco fijo — óptimo económico» en el Problema 2.1 (kvar).

A 66 kV sí existe un banco fijo que cumple la banda las 24 h (Q_C ∈ [87.248, 1530.469] kvar). El mínimo
libre de J (85.76 kvar) queda justo fuera, así que el de menor costo es el extremo inferior de la ventana.
"""

# --- Horizonte ---------------------------------------------------------------------
HOURS_PER_DAY: Final[int] = 24
HOUR_DURATION_H: Final[float] = 1.0

# --- Límites numéricos de búsqueda ------------------------------------------------
QC_SEARCH_MAX_KVAR: Final[float] = 2_000.0
"""Cota superior del espacio de búsqueda de Q_C (holgada frente a la demanda reactiva)."""

# --- Tabla 1: perfil de demanda horaria (hour, P1_kW, pf1, P2_kW, pf2) -------------
DEMAND_TABLE: Final[tuple[tuple[int, float, float, float, float], ...]] = (
    (1, 70, 0.85, 0, 0.75),
    (2, 68, 0.85, 0, 0.75),
    (3, 60, 0.85, 0, 0.75),
    (4, 50, 0.85, 0, 0.75),
    (5, 54, 0.85, 0, 0.75),
    (6, 61, 0.85, 0, 0.75),
    (7, 64, 0.85, 0, 0.75),
    (8, 66, 0.70, 0, 0.75),
    (9, 73, 0.70, 80, 0.75),
    (10, 78, 0.70, 80, 0.75),
    (11, 83, 0.70, 80, 0.75),
    (12, 85, 0.70, 80, 0.75),
    (13, 80, 0.70, 80, 0.75),
    (14, 76, 0.70, 80, 0.75),
    (15, 73, 0.70, 80, 0.75),
    (16, 70, 0.70, 80, 0.75),
    (17, 80, 0.85, 56, 0.75),
    (18, 95, 0.85, 56, 0.75),
    (19, 100, 0.85, 56, 0.75),
    (20, 90, 0.85, 56, 0.75),
    (21, 80, 0.85, 56, 0.75),
    (22, 75, 0.85, 56, 0.75),
    (23, 73, 0.85, 56, 0.75),
    (24, 71, 0.85, 56, 0.75),
)

DEMAND_CSV_COLUMNS: Final[tuple[str, ...]] = ("hour", "P1_kW", "pf1", "P2_kW", "pf2")
