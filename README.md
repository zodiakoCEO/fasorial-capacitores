# Análisis Fasorial y Optimización de Bancos de Capacitores — Red de 24 h

Proyecto de grado: análisis fasorial de dos topologías de distribución, optimización técnico-económica del
banco de capacitores bajo la restricción `950 ≤ |V_gen| ≤ 1100 V` y laboratorio educativo interactivo.

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
| Análisis completo + entregables en `outputs/` | `.\.venv\Scripts\python.exe scripts\run_full_analysis.py` |
| Dashboard educativo | `.\.venv\Scripts\streamlit.exe run app\dashboard.py` |
| Pruebas | `.\.venv\Scripts\python.exe -m pytest -v` |
| Lint | `.\.venv\Scripts\ruff.exe check .` |

## Arquitectura

```
src/domain/          constantes del enunciado + dataclasses inmutables (NetworkParameters, DemandProfile, CircuitResult)
src/physics/         solucionador fasorial puro y vectorizado (Problema 1 y 2) + modelo afín V_gen = A + B·Q_C
src/optimization/    factibilidad exacta, óptimo económico, Pareto, banco por pasos, sensibilidad, economía
src/reporting/       figuras Plotly (dashboard), exportación Matplotlib 300 DPI, CSV y reporte Markdown
scripts/             orquestación por línea de comandos
app/dashboard.py     Streamlit: 5 pestañas (resumen, P1, P2, modo docente, what-if)
tests/               golden tests de física, optimización y humo del dashboard
```

## Fundamento clave

Con transformadores ideales, `V_gen(t, Q_C) = A(t) + B·Q_C` es afín en `Q_C`, de modo que
`|V_gen|² = a·Q_C² + b(t)·Q_C + c(t)` y cada restricción horaria se resuelve en forma cerrada.
Las pérdidas son `P_loss = κ·(P² + (Q − Q_C)²)` con `R_eq = 80 + 0.5·13.2² = 167.12 Ω`, lo que da el
óptimo económico cerrado `Q_C* = mean(Q) − c_cap / (2·c_e·κ·24)`.
