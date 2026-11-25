"""Paleta y tokens visuales compartidos (Plotly + Matplotlib).

Paleta categórica validada (orden fijo, nunca ciclado) y colores de estado reservados.
El color sigue a la *entidad* (estrategia, carga, componente), nunca a su rango.
"""

from __future__ import annotations

from typing import Final

from src.domain.models import Strategy

# Categóricos (modo claro) en orden fijo
SERIES: Final[tuple[str, ...]] = (
    "#2a78d6",  # 1 azul
    "#eb6834",  # 2 naranja
    "#1baf7a",  # 3 aqua
    "#eda100",  # 4 amarillo
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 verde
    "#6250d6",  # 7 violeta
    "#e34948",  # 8 rojo
)

# Estados (reservados; siempre acompañados de ícono/etiqueta)
GOOD: Final[str] = "#0ca30c"
WARNING: Final[str] = "#fab219"
CRITICAL: Final[str] = "#d03b3b"

# Tinta y cromo (funcionan sobre fondo claro y oscuro con transparencia)
INK: Final[str] = "#0b0b0b"
INK_SECONDARY: Final[str] = "#52514e"
MUTED: Final[str] = "#898781"
GRID: Final[str] = "rgba(137,135,129,0.22)"
AXIS: Final[str] = "rgba(137,135,129,0.55)"
BAND_FILL: Final[str] = "rgba(12,163,12,0.12)"
SURFACE: Final[str] = "#fcfcfb"

# Las estrategias "100 % en atraso" (ranuras 4 y 6) llevan además trazo punto-raya / raya larga.
# Las 3 primeras ranuras validan "all-pairs" (líneas que se cruzan); las dos estrategias
# adicionales llevan codificación secundaria (trazo discontinuo/punteado) además del color.
STRATEGY_COLOR: Final[dict[Strategy, str]] = {
    Strategy.NO_CAPACITOR: SERIES[0],
    Strategy.FIXED_ECONOMIC: SERIES[1],
    Strategy.SWITCHED: SERIES[2],
    Strategy.FIXED_MIN_VIOLATION: SERIES[4],
    Strategy.FIXED_LAGGING: SERIES[3],
    Strategy.SWITCHED_LAGGING: SERIES[5],
    Strategy.MANUAL: SERIES[6],
}
STRATEGY_DASH: Final[dict[Strategy, str]] = {
    Strategy.NO_CAPACITOR: "solid",
    Strategy.FIXED_ECONOMIC: "solid",
    Strategy.SWITCHED: "solid",
    Strategy.FIXED_MIN_VIOLATION: "dash",
    Strategy.FIXED_LAGGING: "dashdot",
    Strategy.SWITCHED_LAGGING: "longdash",
    Strategy.MANUAL: "dot",
}

LOAD_COLOR: Final[dict[str, str]] = {"L1 Residencial": SERIES[0], "L2 Industrial": SERIES[1]}
LOSS_COLOR: Final[dict[str, str]] = {"Línea (80 Ω)": SERIES[0], "Generador (0.5 Ω)": SERIES[1]}

# Controles dibujados por Plotly (Reproducir / Pausa): botón claro con texto oscuro (contraste 14:1).
# Plotly colorea el botón activo y el :hover con un fondo claro fijo, de modo que esta combinación
# se mantiene legible en todos los estados y en ambos temas.
BUTTON_BG: Final[str] = "#E2E8F0"
BUTTON_INK: Final[str] = "#0F172A"
BUTTON_BORDER: Final[str] = "#94A3B8"

FONT_FAMILY: Final[str] = '"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif'
FONT_MONO: Final[str] = '"IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace'
