# Análisis Fasorial y Optimización de Bancos de Capacitores — Red de 24 h

Proyecto de grado: análisis fasorial de dos topologías de distribución, optimización técnico-económica del
banco de capacitores bajo la restricción `950 ≤ |V_gen| ≤ 1100 V` y laboratorio educativo interactivo.

**Dashboard interactivo:** [fasorial-capacitores.streamlit.app](https://fasorial-capacitores.streamlit.app/)

El Problema 2 se presenta con dos estrategias: **Sin capacitor (Q_C = 0)** y **Banco fijo — óptimo económico
(Q_C = 378.35 kvar)**, el banco fijo de menor costo anual entre los que mantienen `|V_gen|` en banda el máximo
de horas posible (23 de 24).

El **Problema 2.1** repite el análisis completo con **T1 = 1 kV : 66 kV** y **T2 = 66 kV : 120 V** (lo demás no
cambia). A 66 kV sí existe un banco fijo que cumple la banda las 24 h: **Q_C = 87.25 kvar**, con payback de 78 días.
El dashboard y el reporte incluyen su «Análisis» y la «Comparación» 2 vs. 2.1.

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Uso

| Acción | Comando |
|---|---|
| Generar el CSV de demanda | `.\.venv\Scripts\python.exe scripts\generate_demand_csv.py` |
| Diagnóstico en consola | `.\.venv\Scripts\python.exe scripts\diagnostics.py` |
| Análisis completo + entregables en `outputs/` + auditoría | `.\.venv\Scripts\python.exe scripts\run_full_analysis.py` |
| Auditoría independiente de los Problemas 2 y 2.1 (sin `src/`) | `.\.venv\Scripts\python.exe scripts\auditoria_independiente.py` |
| Dashboard educativo | `.\.venv\Scripts\streamlit.exe run app\dashboard.py` |
| Pruebas | `.\.venv\Scripts\python.exe -m pytest -v` |
| Lint | `.\.venv\Scripts\ruff.exe check .` |

## Arquitectura

```
src/domain/          constantes del enunciado + dataclasses inmutables (NetworkParameters, DemandProfile, CircuitResult)
src/physics/         solucionador fasorial puro y vectorizado (Problema 1 y 2) + modelo afín V_gen = A + B·Q_C
                     + desarrollo algebraico paso a paso de una hora (Fase 1, Fase 2 y Fase 2.1)
src/optimization/    factibilidad exacta, banco fijo óptimo sujeto a la banda, comparación 2 vs. 2.1, economía
src/reporting/       figuras Plotly y esquema del circuito (Figura 2), texto de «Análisis», PNG 300 DPI, CSV y reporte
scripts/             orquestación por línea de comandos y auditoría independiente (solo biblioteca estándar)
app/dashboard.py     Streamlit: 6 pestañas (resumen, P1, P2, P2.1 a 66 kV, modo docente, what-if)
tests/               golden tests de física, optimización, Problema 2.1, auditoría, desarrollo paso a paso,
                     gráficas fasoriales y dashboard (humo y Modo docente)
```

## Fundamento clave

Con transformadores ideales, `V_gen(t, Q_C) = A(t) + B·Q_C` es afín en `Q_C`, de modo que
`|V_gen|² = a·Q_C² + b(t)·Q_C + c(t)` y cada restricción horaria se resuelve en forma cerrada.
Las pérdidas son `P_loss = κ·(P² + (Q − Q_C)²)` con `R_eq = 80 + 0.5·13.2² = 167.12 Ω`, lo que da el
mínimo libre de costo `Q_C = mean(Q) − c_cap / (2·c_e·κ·24) = 91.03 kvar`.

Ningún `Q_C` fijo cumple la banda las 24 h (los intervalos de las horas 8 y 18–20 son disjuntos). El máximo es
23/24 h, para `Q_C ∈ [378.349, 384.847] kvar`; como `J` crece en ese tramo, el de menor costo es su extremo
inferior, que se adopta como **378.35 kvar**. Con ese banco el factor de potencia neto queda en adelanto las
24 h y las pérdidas pasan de 632 a 2 234 kWh/día: se justifica por regulación de tensión, no por ahorro.

## Problema 2 vs. Problema 2.1

| | Problema 2 (13.2 kV) | Problema 2.1 (66 kV) |
|---|---:|---:|
| Relaciones | n₁ = 13.2, a₂ = 110 | n₁ = 66, a₂ = 550 |
| Banco fijo | 378.35 kvar | 87.25 kvar |
| Horas en [950, 1100] V | 23/24 | 24/24 |
| \|I_line\| máx | 26.59 A | 2.72 A |
| Pérdidas | 2 233.73 kWh/día | 225.27 kWh/día |
| Costo total anual J | $ 820.532.716 | $ 87.660.102 |
| Ahorro frente a Q_C = 0 | −$ 561.195.727/año | $ 40.775.643/año |
| Payback | no se recupera | 78.1 días |

Con la línea a 66 kV su impedancia vista desde el generador se divide por 25 y la caída reactiva deja de sacar a
`|V_gen|` de la banda. Las pérdidas quedan dominadas por `R_gen` (96.5 %), que no depende de la tensión de línea.
