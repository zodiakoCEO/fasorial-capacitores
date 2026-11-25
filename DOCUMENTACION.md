# Guía para todos: qué hace este proyecto y cómo funciona su código

Esta guía explica el proyecto **desde cero**. No necesitas saber electricidad ni programación:
cada idea viene con una comparación de la vida diaria, un ejemplo con números reales y el
pedazo de código que la calcula.

**Abrir el dashboard interactivo en línea:** [fasorial-capacitores.streamlit.app](https://fasorial-capacitores.streamlit.app/)

Todos los números de esta guía salen de ejecutar el código del proyecto, no están inventados.

**Cómo leerla**

| Si quieres… | Lee |
|---|---|
| Entender de qué trata, sin código | Partes 1, 2 y 6 |
| Estudiar el código | Partes 3, 4 y 5 |
| Ejecutarlo en tu computador | Parte 7 |
| Buscar una palabra rara | Parte 9 (glosario) |

---

## Parte 1 — La historia en un minuto

Hay un **generador** (una fábrica de electricidad) y, lejos de él, unas **cargas** (casas y una
industria) que consumen electricidad. Entre los dos hay un **cable muy largo**.

El problema: el cable **desperdicia energía** en forma de calor. La pregunta del proyecto es:

> ¿Cómo llevamos la electricidad gastando lo menos posible, sin que el generador
> tenga que trabajar a un voltaje peligroso, y cuánto cuesta lograrlo?

El proyecto responde eso para **cada una de las 24 horas del día**, en tres pasos:

1. **Problema 1:** mandar la electricidad directamente a 120 V. Resultado: un desastre
   (se pierde 1.287 veces más energía de la que se entrega).
2. **Problema 2:** poner dos **transformadores** y un **banco de capacitores**. Resultado: las
   pérdidas bajan muchísimo.
3. **Optimización:** decidir **de qué tamaño** debe ser el banco de capacitores para que el
   voltaje del generador quede entre **950 V y 1100 V** el mayor número de horas posible,
   al menor costo. Resultado: un banco fijo de **378,35 kvar**.

---

## Parte 2 — Las ideas, explicadas con cosas de la casa

### 2.1 Voltaje, corriente y resistencia: el agua en una manguera

| Electricidad | Agua | Unidad |
|---|---|---|
| **Voltaje** (V) | La presión que empuja el agua | voltios (V) |
| **Corriente** (I) | Cuánta agua pasa por segundo | amperios (A) |
| **Resistencia** (R) | Qué tan estrecha es la manguera | ohmios (Ω) |

Una manguera estrecha y larga **roza** con el agua y la frena. En un cable ese roce se vuelve
**calor**: eso son las **pérdidas**.

La regla más importante de todo el proyecto:

```
Pérdidas = Corriente × Corriente × Resistencia        (P = I² · R)
```

Como la corriente va **al cuadrado**, si pasas el doble de corriente pierdes **cuatro** veces
más. Por eso todo el proyecto gira alrededor de una sola meta: **que por el cable pase la menor
corriente posible**.

### 2.2 Potencia útil y potencia "de relleno": el vaso de cerveza

Cuando sirves una cerveza, el vaso trae **líquido** y **espuma**. Pagas el vaso completo, pero
solo te tomas el líquido.

| En el vaso | En electricidad | Símbolo | Unidad |
|---|---|---|---|
| El líquido | **Potencia activa**: la que hace trabajo real (luz, movimiento) | P | kW |
| La espuma | **Potencia reactiva**: no hace trabajo, pero los motores la necesitan para funcionar | Q | kvar |
| El vaso entero | **Potencia aparente**: lo que el cable tiene que transportar | S | kVA |

El **factor de potencia (fp)** dice qué parte del vaso es líquido:

```
fp = P / S          fp = 1    → todo líquido, perfecto
                    fp = 0,70 → solo 70 % líquido, mucha espuma
```

**El punto clave:** el cable tiene que cargar con el vaso entero (líquido + espuma). La espuma
no sirve para nada útil, pero **sí ocupa corriente** y por tanto **sí produce pérdidas**.

### 2.3 El capacitor: una máquina de espuma al lado del cliente

Un **capacitor** es un aparato que **fabrica potencia reactiva** (espuma). Si lo pones junto a
las cargas, la espuma se produce ahí mismo y **ya no tiene que viajar por el cable**.

- Menos espuma viajando → menos corriente → menos pérdidas.
- Un **banco de capacitores** son varios capacitores juntos. Su tamaño se llama **Q_C** y se
  mide en kvar.
- Cuesta dinero: en este proyecto, **100.000 pesos por cada kvar** instalado.

Lo que viaja por el cable es la **espuma neta**:

```
Q_neta = Q de las cargas − Q_C del banco
```

¿Y si pones demasiado capacitor? Sobra espuma y ahora viaja **en sentido contrario**. A eso se
le dice estar **en adelanto**. Si falta o queda justa, se dice **en atraso**. (Esto importa en
la Parte 6.)

### 2.4 El transformador: cambiar presión por caudal

Un **transformador** sube el voltaje y, a cambio, baja la corriente (o al revés). La potencia
que pasa es la misma.

Es como cambiar de marcha en una bicicleta: no creas energía, solo cambias fuerza por velocidad.

En este proyecto hay dos:

| Nombre | Qué hace | Relación |
|---|---|---|
| **T1** (elevador) | Sube de 1.000 V a 13.200 V a la salida del generador | n1 = 13,2 |
| **T2** (reductor) | Baja de 13.200 V a 120 V junto a las cargas | a2 = 110 |

Como el cable ahora trabaja a 13.200 V en vez de 120 V, la corriente por el cable es **110 veces
menor**, y las pérdidas en el cable son 110 × 110 = **12.100 veces menores**.

### 2.5 El fasor: una flecha

En corriente alterna, el voltaje y la corriente suben y bajan como olas, y no siempre van
sincronizadas. Para describir una ola se necesitan dos datos: **qué tan grande es** y **qué tan
adelantada o atrasada va**.

Un **fasor** es una **flecha** que guarda esos dos datos: su **largo** (la magnitud) y su
**ángulo** (el desfase). Por ejemplo `686 A ∠ −31,8°` es una flecha de largo 686 que apunta
31,8° hacia abajo.

En el computador una flecha así se guarda como un **número complejo** (un número con dos
partes). En Python se escribe con una `j`:

```python
voltaje = complex(120.0, 0.0)  # flecha de largo 120 apuntando a la derecha (ángulo 0°)
linea = complex(80.0, 900.0)  # 80 de resistencia + 900 de reactancia
abs(voltaje)  # el largo de la flecha → 120.0
```

De ahí viene el nombre del proyecto: **análisis fasorial** = hacer las cuentas con flechas.

### 2.6 El dibujo del circuito

**Problema 1 — todo a 120 V:**

```
 Generador ──[ R_gen 0,5 Ω ]──[ Cable 80 + j900 Ω ]──┬── L1 (casas)
                                                     └── L2 (industria)
```

**Problema 2 — con transformadores y capacitor:**

```
 Generador ──[ R_gen ]──( T1 sube )──[ Cable ]──( T2 baja )──┬── L1 (casas)
   ~1.000 V              13.200 V                  120 V     ├── L2 (industria)
                                                             └── Banco Q_C
```

---

## Parte 3 — Cómo está organizado el proyecto

Piensa en una cocina: ingredientes, recetas, el chef que decide, y el plato servido.

```
fasorial-capacitores/
├── src/
│   ├── domain/          ← LOS INGREDIENTES: datos del problema
│   │   ├── constants.py        números del enunciado (120 V, 80+j900 Ω, tabla de demanda…)
│   │   └── models.py           "cajas" para guardar datos y resultados
│   ├── physics/         ← LAS RECETAS: las leyes de la electricidad
│   │   ├── circuit_solver.py   resuelve el circuito de los Problemas 1 y 2
│   │   └── step_by_step.py     tabla con todos los pasos intermedios
│   ├── optimization/    ← EL CHEF: decide el mejor banco de capacitores
│   │   ├── capacitor_optimizer.py   factibilidad y tamaño del banco
│   │   ├── economics.py             cuentas de plata (costos, ahorro, payback)
│   │   └── pipeline.py              ejecuta todo en orden
│   └── reporting/       ← EL PLATO SERVIDO: gráficas, tablas y reporte
│       ├── charts.py                gráficas interactivas y dibujo del circuito
│       ├── analysis_text.py         texto de las secciones "Análisis"
│       ├── presentation_export.py   imágenes PNG, CSV y reporte Markdown
│       └── theme.py                 colores
├── scripts/             ← BOTONES para ejecutar desde la terminal (incluye la auditoría)
├── app/dashboard.py     ← PÁGINA WEB interactiva (Streamlit)
├── tests/               ← PRUEBAS automáticas que revisan que todo esté bien
├── data/                ← la tabla de demanda en CSV
└── outputs/             ← todo lo que el programa genera
```

**El viaje de los datos**, de principio a fin:

```
constants.py ─► DemandProfile ─► solve_problem1 / solve_problem2 ─► CircuitResult
 (los números)   (24 horas de      (calcula corrientes, voltajes        (resultado
                  consumo)          y pérdidas)                          de 24 horas)
                                              │
                                              ▼
                     capacitor_optimizer.py prueba distintos Q_C
                                              │
                                              ▼
                     run_full_analysis() junta todo en un AnalysisBundle
                                              │
                          ┌───────────────────┼───────────────────┐
                          ▼                   ▼                   ▼
                     consola            outputs/ (PNG, CSV)    dashboard web
```

---

## Parte 4 — Cinco cosas de Python que verás en el código

No hace falta ser programador. Con estas cinco ideas puedes leer casi todo.

**1. Una función es una receta.** Recibe ingredientes y devuelve un resultado.

```python
def capacitor_capex_cop(q_c_installed_kvar, params):
    return q_c_installed_kvar * params.capacitor_cost_cop_per_kvar


#          └── kvar instalados ──┘   └── 100.000 pesos por kvar ──┘
```

`def` = "defino una receta". `return` = "este es el resultado".

**2. Una `dataclass` es una caja con etiquetas.** Sirve para guardar varios datos juntos.
`NetworkParameters` es la caja con los datos de la red; `CircuitResult` es la caja con los
resultados. `frozen=True` significa que la caja queda **sellada**: nadie puede cambiar un dato
por accidente después de crearla.

**3. Una `@property` es un dato que se calcula solo.** No se guarda; se calcula al pedirlo.

```python
@property
def n1(self) -> float:
    return self.t1_secondary_v / self.t1_primary_v  # 13.200 / 1.000 = 13,2
```

Escribes `params.n1` (sin paréntesis) y obtienes `13.2`.

**4. Los arreglos de NumPy hacen 24 cuentas de una sola vez.** En vez de repetir la cuenta hora
por hora, se guarda una lista de 24 números y se opera con toda la lista a la vez.

```python
p1_kw + p2_kw  # suma las 24 horas de L1 con las 24 de L2 → 24 resultados
```

A esto se le llama código **vectorizado**. Por eso casi no verás ciclos `for` en la física.

**5. Las anotaciones de tipo son solo etiquetas informativas.** `-> float` quiere decir
"esto devuelve un número decimal". No cambian el cálculo; ayudan a quien lee.

---

## Parte 5 — Las funciones principales, una por una

### 5.1 Los datos del problema — [constants.py](src/domain/constants.py)

Aquí están los números del enunciado. `Final` significa "esto no se cambia".

```python
V0_LOAD = complex(120.0, 0.0)  # voltaje en las cargas: 120 V
R_GEN_OHM = 0.5  # resistencia junto al generador
Z_LINE_OHM = complex(80.0, 900.0)  # el cable: 80 Ω de resistencia, 900 Ω de reactancia

ENERGY_PRICE_COP_PER_KWH = 960.0  # cada kWh perdido cuesta 960 pesos
CAPACITOR_COST_COP_PER_KVAR = 100_000.0  # cada kvar de capacitor cuesta 100.000 pesos

V_GEN_MIN_V = 950.0  # el generador no puede bajar de 950 V…
V_GEN_MAX_V = 1_100.0  # …ni subir de 1.100 V
```

Y la **tabla de demanda**: cuánto consumen las cargas en cada hora.

```python
DEMAND_TABLE = (
    # hora, P1 (kW), fp1, P2 (kW), fp2
    (1, 70, 0.85, 0, 0.75),  # madrugada: solo casas
    ...(12, 85, 0.70, 80, 0.75),  # mediodía: casas + industria
    ...,
)
```

- **L1** son las casas (residencial). **L2** es la industria, que solo trabaja de la hora 9 a la 24.

### 5.2 La caja de la demanda — `DemandProfile` en [models.py](src/domain/models.py:101)

Guarda las 24 horas y **calcula sola** la potencia reactiva (la espuma):

```python
@property
def q1_kvar(self):
    return self.p1_kw * np.tan(np.arccos(self.pf1))
```

**Ejemplo, hora 1:** las casas consumen P = 70 kW con fp = 0,85.

```
Q = 70 × tan(arccos(0,85)) = 43,38 kvar      ← la espuma
S = √(70² + 43,38²)        = 82,35 kVA       ← el vaso entero
```

Otras propiedades útiles: `p_total_kw` (P1 + P2), `q_total_kvar` (Q1 + Q2) y `s_total_kva`
(las dos juntas en una flecha: `P + jQ`).

Al crearse, la caja **revisa los datos** (`__post_init__`): si un factor de potencia no está
entre 0 y 1, se detiene con un error en vez de calcular basura.

### 5.3 La corriente — `load_current` en [circuit_solver.py](src/physics/circuit_solver.py:42)

```python
def load_current(s_kva, v_load):
    return np.conj(np.asarray(s_kva, complex) * KILO / v_load)
```

Es la fórmula **I = (S / V)\***. Paso a paso:

- `s_kva * KILO` → pasa de kVA a VA (multiplica por 1.000).
- `/ v_load` → divide por el voltaje.
- `np.conj(...)` → voltea el signo del ángulo (así lo exige la fórmula de potencia).

**Ejemplo, hora 1:** S = 70 + j43,38 kVA y V = 120 V.

```
(70.000 + j43.382) / 120 = 583,33 + j361,52
voltear el signo         = 583,33 − j361,52 A
largo de la flecha       = 686,27 A      ángulo = −31,79°
```

¡686 amperios! Una casa normal usa unos 30. Esa corriente enorme es el origen del desastre del
Problema 1.

### 5.4 Problema 1 — `solve_problem1` en [circuit_solver.py](src/physics/circuit_solver.py:59)

```python
s_load = demand.s_total_kva  # 1. cuánto piden las cargas
i_load = load_current(s_load, params.v_load)  # 2. la corriente que eso exige
i_line = i_load  # 3. sin transformadores, la misma va por el cable
v_line_send = v_load + i_line * params.z_line  # 4. voltaje al inicio del cable (ley de Ohm)
v_gen = v_line_send + i_line * params.r_gen  # 5. voltaje en el generador

i2 = np.abs(i_line) ** 2  # corriente al cuadrado
p_loss_line = i2 * params.r_line / KILO  # 6. pérdidas en el cable   (I²·R)
p_loss_gen = i2 * params.r_gen / KILO  #    pérdidas junto al generador
```

Se lee de derecha (las cargas) a izquierda (el generador): partimos de lo que sabemos (120 V en
las cargas) y vamos **sumando lo que se cae** en cada tramo.

**Ejemplo, hora 1:**

```
Pérdidas cable     = 686,27² × 80  = 37.678 kW
Pérdidas generador = 686,27² × 0,5 =    235 kW
Total              =                 37.913 kW   ← ¡para entregar solo 70 kW!
```

**En todo el día:** se pierden **3.684.396 kWh** para entregar **2.863 kWh**. Se pierde
**1.287 veces** lo que se entrega, y costaría unos **3.537 millones de pesos diarios**. El
generador necesitaría hasta 1.716.505 V. Conclusión: a 120 V directos **no se puede**.

### 5.5 Problema 2 — `solve_problem2` en [circuit_solver.py](src/physics/circuit_solver.py:99)

Igual que antes, pero ahora con el banco `q_c` y los dos transformadores:

```python
s_net = demand.p_total_kw + 1j * (demand.q_total_kvar - q_c)  # 1. el capacitor resta espuma
i_load = load_current(s_net, params.v_load)  # 2. corriente en las cargas
i_line = i_load / params.a2  # 3. T2: la corriente baja 110 veces
i_gen = i_line * params.n1  # 4. T1: en el generador es 13,2 veces mayor

v_recv = v_load * params.a2  # 5. 120 V × 110 = 13.200 V
v_send = v_recv + i_line * params.z_line  # 6. caída en el cable
v_t1_prim = v_send / params.n1  # 7. T1 lo baja 13,2 veces
v_gen = v_t1_prim + i_gen * params.r_gen  # 8. voltaje del generador
```

La línea 1 es **todo el truco del capacitor**: `Q − Q_C`. Menos espuma que transportar.

**Ejemplo, hora 1, sin capacitor (Q_C = 0):**

| Magnitud | Problema 1 | Problema 2 |
|---|---|---|
| Corriente en el cable | 686,27 A | **6,24 A** (686,27 ÷ 110) |
| Pérdidas en el cable | 37.678 kW | **3,11 kW** |
| Pérdidas junto al generador | 235 kW | 3,39 kW |
| **Pérdidas totales** | **37.913 kW** | **6,5 kW** |

Las pérdidas del día bajan de 3.684.396 kWh a **632 kWh**. Los transformadores resolvieron el
desastre.

**Pero queda un problema:** el voltaje del generador da **1.330 V** en la hora 1 y llega a
**2.092 V** en la hora 12. El límite es 1.100 V. Sin capacitor, **las 24 horas están fuera del
rango permitido**. Ahí entra el banco de capacitores.

`q_c` puede ser **un solo número** (banco fijo, igual todo el día) o **24 números** (banco
automático, distinto cada hora). La función auxiliar `_as_hourly` convierte los dos casos al
mismo formato.

### 5.6 La caja de resultados — `CircuitResult` en [models.py](src/domain/models.py:190)

Guarda todo lo calculado para las 24 horas: corrientes (`i_line`, `i_gen`), voltajes (`v_gen`),
pérdidas (`p_loss_line_kw`, `p_loss_gen_kw`)… y calcula solas cosas como:

| Propiedad | Qué da |
|---|---|
| `p_loss_kw` | Pérdidas totales por hora |
| `daily_energy_loss_kwh` | Energía perdida en el día |
| `q_net_kvar` | La espuma neta (Q − Q_C) |
| `pf_net` | El factor de potencia neto |
| `leading_mask` | En qué horas hay demasiado capacitor (adelanto) |
| `to_dataframe()` | Todo convertido en una tabla |

### 5.7 El atajo matemático — `affine_voltage_model` en [circuit_solver.py](src/physics/circuit_solver.py:171)

Probar miles de tamaños de banco resolviendo el circuito entero cada vez sería lento. El código
aprovecha que el voltaje del generador sigue una **línea recta** respecto a Q_C:

```
V_gen = A + B × Q_C
```

- **A** = el voltaje sin capacitor (una flecha distinta cada hora).
- **B** = cuánto se mueve la flecha por cada kvar que agregas (siempre el mismo paso).

**Ejemplo, hora 1:** A = 1291,2 + j320,0 y B = −5,165 + j0,959 (voltios por cada kvar).

```
Con Q_C = 0  kvar:  V_gen = A               → largo 1.330 V   (fuera, muy alto)
Con Q_C = 50 kvar:  V_gen = A + B × 50
                          = 1033,0 + j367,9 → largo 1.096,5 V (¡dentro del rango!)
```

Como es una recta de flechas, el **largo al cuadrado** es una **parábola** (una curva en forma
de U): `|V_gen|² = a·Q_C² + b·Q_C + c`. La propiedad `quadratic` entrega esos tres coeficientes.
Y una parábola se resuelve con la fórmula del colegio, sin tanteos.

De la misma forma, `daily_loss_quadratic` da las pérdidas con una fórmula directa:

```
Pérdidas = κ × ( P² + (Q − Q_C)² )          con κ = 0,000959
```

**Ejemplo, hora 1:**

```
Sin capacitor:        0,000959 × (70² + 43,38²)      = 6,50 kW
Con Q_C = 43,38 kvar: 0,000959 × (70² + 0²)          = 4,70 kW   ← toda la espuma eliminada
```

### 5.8 ¿Qué tamaños de banco sirven en cada hora? — `feasibility_analysis` en [capacitor_optimizer.py](src/optimization/capacitor_optimizer.py:253)

"Factible" significa **"cumple la regla"**: el voltaje queda entre 950 y 1.100 V.

Para cada hora la función resuelve la parábola y devuelve los **intervalos** de Q_C que sirven.
Un intervalo es un rango "desde–hasta", guardado en la cajita `Interval(lo, hi)`.

```
Hora 1:  Q_C entre  49,2 y  83,1   o   entre 377,9 y 411,8
Hora 8:  Q_C entre  70,9 y 104,3   o   entre 404,6 y 438,0
Hora 19: Q_C entre 212,2 y 384,8
```

(Salen dos rangos porque la parábola tiene forma de U: hay una zona buena a cada lado del fondo.)

Luego busca un tamaño que sirva **las 24 horas a la vez**, cruzando todos los rangos con
`intersect_many`. Ejemplo sencillo de cruzar rangos, tomado de las pruebas:

```python
a = (Interval(0, 10), Interval(20, 30))
b = (Interval(5, 25),)
intersect_many([a, b])  # → (Interval(5, 10), Interval(20, 25))   lo que tienen en común
```

**El hallazgo más importante del proyecto:** el cruce de las 24 horas queda **vacío**.

```
La hora 8 necesita  Q_C ≤ 104,3  (o ≥ 404,6)
La hora 19 necesita Q_C entre 212,2 y 384,8
→ No existe ningún número que cumpla las dos.
```

Es decir: **ningún banco de tamaño fijo cumple la regla de voltaje todo el día**. Las horas en
conflicto son la 8 contra la 18, 19 y 20.

Para estar seguros, la función lo comprueba **por un segundo camino independiente**
(`numeric_hour_feasible_set`, que tantea con 40.001 puntos). Los dos caminos coinciden con una
diferencia de 0,000000000002 kvar.

### 5.9 Evaluar una opción — `evaluate_strategy` en [capacitor_optimizer.py](src/optimization/capacitor_optimizer.py:378)

Es la función "comodín": le das un banco (fijo o por horas) y te devuelve **todo** sobre él en
una caja `StrategyResult`:

```python
circuit = solve_problem2(demand, q_c_profile, params)  # 1. resuelve el circuito
econ = build_economic_summary(...)  # 2. hace las cuentas de plata
violation_v = voltage_violation(np.abs(circuit.v_gen), params)  # 3. mide cuánto se sale del rango
```

`voltage_violation` mide **cuántos voltios se sale** del rango (0 si está dentro):

```
1.330 V → se pasa del máximo (1.100) por 230 V  → violación = 230
1.000 V → está dentro                           → violación = 0
  900 V → le faltan 50 para el mínimo (950)     → violación = 50
```

### 5.10 Las cuentas de plata — [economics.py](src/optimization/economics.py)

| Palabra | Significado sencillo | Fórmula |
|---|---|---|
| **CAPEX** | Lo que pagas **una vez** por comprar el banco | Q_C × 100.000 |
| **OPEX** | Lo que pagas **cada año** por la energía perdida | kWh perdidos al día × 960 × 365 |
| **J** (costo total) | Lo que queremos que sea lo más pequeño posible | OPEX + CAPEX |
| **Ahorro anual** | Lo que dejas de perder frente a no tener banco | OPEX sin banco − OPEX con banco |
| **Payback** | En cuánto tiempo el ahorro paga la compra | CAPEX ÷ ahorro anual |
| **ROI** | Cuánto ganas por cada peso invertido | (ahorro acumulado − CAPEX) ÷ CAPEX |

```python
@property
def payback_years(self) -> float:
    if self.capex_cop == 0:
        return 0.0  # no compraste nada: no hay nada que recuperar
    if self.annual_savings_cop <= 0:
        return math.inf  # no ahorras: nunca se recupera (infinito)
    return self.capex_cop / self.annual_savings_cop
```

**Ejemplo 1 (banco de 91,03 kvar, el más barato si no importara el voltaje):**

```
CAPEX   = 91,03 × 100.000          =  9.102.971 pesos
Ahorro  = 221,5 M − 145,6 M        = 75.940.783 pesos al año
Payback = 9.102.971 ÷ 75.940.783   = 0,12 años ≈ 44 días
```

**Ejemplo 2 (banco de 378,35 kvar, el que usa el proyecto):**

```
CAPEX   = 378,35 × 100.000         =  37.835.000 pesos
Ahorro  = 221,5 M − 782,7 M        = −561.195.727 pesos al año   ← negativo: se pierde más
Payback = no se recupera           (la rama `math.inf` del código de arriba)
```

`format_cop` solo sirve para escribir bonito: convierte `9102971` en `$ 9.102.971 COP`.

### 5.11 El banco elegido: 378,35 kvar — `fixed_economic_optimum` en [capacitor_optimizer.py](src/optimization/capacitor_optimizer.py:513)

Como ningún banco fijo cumple el voltaje las 24 horas, la pregunta cambia a:

> De los bancos fijos que cumplen el voltaje **la mayor cantidad de horas posible**,
> ¿cuál es el más barato?

La función lo resuelve en tres pasos:

```python
band = max_band_window(feas)  # 1. ¿cuántas horas se pueden cumplir, y con qué tamaños?
candidates = [iv.clip(q_free) for iv in band.window]  # 2. el más barato dentro de esa ventana
q_design = _design_value(q_band, band.window, 0.01)  # 3. se redondea a dos decimales
```

**Paso 1 — contar horas.** `max_band_window` revisa, para cada tamaño de banco, en cuántas horas
el voltaje queda dentro del rango. Es como buscar la hora de reunión en la que puede asistir más
gente:

```
Con 300,00 kvar cumplen 11 horas
Con 378,34 kvar cumplen 21 horas
Con 378,35 kvar cumplen 23 horas   ← el máximo posible
Con 390,00 kvar cumplen 22 horas
```

El máximo es **23 de 24 horas**, y se logra con cualquier banco entre **378,349 y 384,847 kvar**.

**Paso 2 — el más barato de esa ventana.** Dentro de la ventana, cada kvar adicional cuesta más
(unos 4,6 millones de pesos al año por kvar), así que el más barato es el **extremo de abajo**:
378,349059 kvar.

**Paso 3 — redondear.** Se adopta **378,35 kvar**. Una prueba automática comprueba que el código
llega exactamente a ese número.

**Qué pasa con 378,35 kvar:**

| Dato | Sin capacitor | Con 378,35 kvar |
|---|---|---|
| Voltaje del generador | 1.229 a 2.092 V | 839 a 1.086 V |
| Horas dentro de 950–1.100 V | 0 de 24 | **23 de 24** (falla la hora 8) |
| Corriente en el cable | 4,5 a 17,3 A | 20,9 a 26,6 A |
| Pérdidas al día | 632 kWh | 2.234 kWh |
| Costo total al año | 221,5 millones | 820,5 millones |

**Lo que hay que entender:** este banco es **más grande de lo que la carga necesita**. La carga
pide como máximo 157 kvar de "espuma" y el banco fabrica 378. La espuma sobrante viaja por el
cable en sentido contrario (factor de potencia **en adelanto** las 24 horas), y por eso la
corriente y las pérdidas **suben**. A cambio, esa corriente "al revés" es justo lo que baja el
voltaje del generador hasta el rango permitido.

Es decir: **este banco arregla el voltaje, no ahorra plata.**

La función guarda también, solo como referencia, el **mínimo libre de costo** (`free`): el banco
más barato si a nadie le importara el voltaje. Es de 91,03 kvar y cuesta 154,7 millones al año,
pero deja 23 horas fuera del rango.

```
Mínimo libre = promedio(Q) − corrección = 97,23 − 6,20 = 91,03 kvar
```

### 5.12 Funciones que quedaron de reserva

En [capacitor_optimizer.py](src/optimization/capacitor_optimizer.py) siguen existiendo, con sus
pruebas, funciones para otros tipos de banco. **Ya no aparecen en el dashboard ni en el
reporte**, que solo muestran "Sin capacitor" y "Banco fijo — óptimo económico":

| Función | Qué calcula |
|---|---|
| [`fixed_voltage_pareto`](src/optimization/capacitor_optimizer.py:631) | Bancos fijos que equilibran costo y salida de voltaje |
| [`switched_capacitor_bank`](src/optimization/capacitor_optimizer.py:749) | Banco automático que cambia de tamaño cada hora |
| [`fixed_lagging_optimum`](src/optimization/capacitor_optimizer.py:846) | Banco fijo que nunca fabrica más espuma de la necesaria |
| [`switched_lagging_bank`](src/optimization/capacitor_optimizer.py:917) | Lo mismo, pero automático por pasos |
| [`lagging_voltage_limit`](src/optimization/capacitor_optimizer.py:1025) | Hasta dónde baja el voltaje sin pasarse de capacitor |

### 5.13 ¿Y si el cable fuera distinto? — `line_reactance_sensitivity` en [capacitor_optimizer.py](src/optimization/capacitor_optimizer.py:1089)

"Sensibilidad" = cambiar un dato y ver qué pasa. Aquí se cambia la **reactancia del cable**
(el 900 de `80 + j900`) desde 0 hasta 1.350 Ω.

**Resultado:** un banco fijo cumpliría las 24 horas si la reactancia estuviera entre **66,2 y
777,5 Ω**. El cable real tiene 900 Ω, por eso el máximo son 23 horas. Para hallar los bordes
exactos usa **bisección** (`_bisect_transition`): partir el rango por la mitad una y otra vez,
como adivinar un número con "más alto / más bajo".

### 5.14 El director de orquesta — `run_full_analysis` en [pipeline.py](src/optimization/pipeline.py:50)

Llama a las funciones anteriores en orden y guarda todo en una sola caja, `AnalysisBundle`:

```python
return AnalysisBundle(
    problem1=solve_problem1(demand, params),  # Problema 1
    no_capacitor=evaluate_strategy(demand, params, 0.0, ...),  # Problema 2 sin banco
    feasibility=feas,  # qué tamaños sirven por hora
    economic=fixed_economic_optimum(demand, params, feasibility=feas),  # el banco de 378,35 kvar
    scan=fixed_bank_scan(demand, params, feas),  # costo y horas en banda para cada tamaño
    sensitivity=line_reactance_sensitivity(demand, params),  # qué pasa si cambia el cable
)
```

`strategies` devuelve las **dos** opciones que se muestran y `comparison_table()` arma la tabla
que las compara (la de la Parte 6).

### 5.15 El análisis escrito y la auditoría

**[analysis_text.py](src/reporting/analysis_text.py)** escribe las secciones "Análisis" del
dashboard y del reporte. No tiene números escritos a mano: cada frase se arma con los
resultados. Si cambian los datos, el texto cambia solo.

```python
f"Con Qc = {qc:g} kvar, |Vgen| queda entre {v1.min():,.2f} V y {v1.max():,.2f} V y "
f"**{24 - len(out)} de 24 horas** entran en la banda ..."
```

**[auditoria_independiente.py](scripts/auditoria_independiente.py:239)** es un **segundo
programa que no usa nada del primero**. Vuelve a hacer todas las cuentas de las 24 horas con
378,35 kvar, por dos caminos distintos, y compara. Es como pedirle a otra persona que resuelva
el mismo ejercicio sin mirar tu cuaderno: si los dos llegan al mismo resultado, es muy difícil
que ambos estén mal.

Revisa 12 cosas (por ejemplo, que la energía que sale del generador sea igual a la que llega a
las cargas más la que se pierde) y las 12 pasan. La mayor diferencia frente al programa
principal es de 0,000000000000005.

### 5.16 Mostrar los resultados

| Archivo | Qué hace |
|---|---|
| [scripts/diagnostics.py](scripts/diagnostics.py) | `print_report`: imprime el resumen en la terminal |
| [presentation_export.py](src/reporting/presentation_export.py:1417) | `export_all`: guarda 23 imágenes, 20 tablas CSV y un reporte en `outputs/` |
| [charts.py](src/reporting/charts.py) | Funciones `fig_…`: cada una dibuja una gráfica interactiva |
| [charts.py](src/reporting/charts.py:928) | `circuit_svg`: dibuja el circuito igual a la Figura 2 del enunciado |
| [step_by_step.py](src/physics/step_by_step.py) | `hourly_step_table`: tabla con cada paso intermedio, como hecho a mano |
| [step_by_step.py](src/physics/step_by_step.py) | `algebraic_development`: el desarrollo de una hora en 8 pasos, con sus ecuaciones, para la Fase 1, la Fase 2 y la Fase 2.1 |
| [app/dashboard.py](app/dashboard.py) | La página web con 6 pestañas |

`power_balance_error` (en `step_by_step.py`) es un **autochequeo**: revisa que la energía que
sale del generador sea igual a la que llega a las cargas más la que se pierde. Si la física
está bien, la diferencia es prácticamente cero.

---

## Parte 6 — Los resultados y qué significan

El proyecto compara dos opciones para el Problema 2:

| | Sin capacitor | Banco fijo de 378,35 kvar |
|---|---|---|
| Voltaje del generador | 1.229 a 2.092 V | 839 a 1.086 V |
| Horas dentro de 950–1.100 V | 0 de 24 | **23 de 24** |
| Corriente máxima en el cable | 17,3 A | 26,6 A |
| Pérdidas al día | 632 kWh | 2.234 kWh |
| Costo de las pérdidas al año | 221,5 M | 782,7 M |
| Costo del banco | 0 | 37,8 M |
| **Costo total al año** | **221,5 M** | **820,5 M** |
| Factor de potencia | 0,70 a 0,85 en atraso | 0,14 a 0,60 en adelanto |

(M = millones de pesos colombianos.)

**Lo que hay que llevarse:**

1. **A 120 V directos es imposible:** se pierde 1.287 veces lo que se entrega.
2. **Los transformadores arreglan las pérdidas**, pero dejan el voltaje del generador demasiado
   alto las 24 horas.
3. **Ningún banco fijo cumple el voltaje las 24 horas.** Está demostrado, no es un tanteo. Lo
   máximo son 23 horas.
4. **El banco de 378,35 kvar es el más barato de los que logran esas 23 horas.** Solo falla la
   hora 8, donde el voltaje baja a 839 V (111 V por debajo del mínimo).
5. **Ese banco no ahorra plata.** Las pérdidas se multiplican por 3,5 y el costo total al año
   pasa de 221,5 a 820,5 millones. La inversión nunca se recupera con ahorro de energía.
6. **¿Por qué se pierde más?** El banco fabrica más "espuma" (378 kvar) de la que la carga pide
   (157 kvar como máximo). La que sobra viaja por el cable y calienta igual que la otra.
7. **Si solo importara la plata**, el mejor banco sería de 91,03 kvar (154,7 millones al año),
   pero dejaría 23 horas con el voltaje fuera del rango.
8. **El diseño queda muy justo.** En las horas de madrugada el voltaje está a milésimas de
   voltio del mínimo: un banco apenas más pequeño ya no cumple.

No hay una opción que gane en todo: con este cable hay que escoger entre **voltaje correcto** o
**costo bajo**.

---

## Parte 6.1 — El Problema 2.1: ¿y si el cable trabajara a 66.000 V?

El Problema 2.1 es **la misma red** con una sola diferencia: los transformadores suben el voltaje del
cable a **66.000 V** en vez de 13.200 V. Todo lo demás (cargas, cable, precios, rango permitido) no cambia.

| | Problema 2 | Problema 2.1 |
|---|---|---|
| T1 (elevador) | 1.000 V → 13.200 V | 1.000 V → 66.000 V |
| T2 (reductor) | 13.200 V → 120 V | 66.000 V → 120 V |
| La corriente del cable se divide por | 110 | 550 |

En el código es **una línea**: se pide la misma caja de parámetros con otro voltaje de línea, y todas las
funciones de la Parte 5 se vuelven a ejecutar solas.

```python
def params_2_1(base=None):
    return (base or NetworkParameters()).with_line_voltage(66_000.0)
```

**Qué cambia en la física.** Volviendo a la bicicleta: es una marcha todavía más larga. Por el cable pasa
**5 veces menos corriente**, y el "estorbo" del cable visto desde el generador es **25 veces menor**
(5 × 5). Por eso el voltaje del generador ya casi no se dispara: sin capacitor queda entre 1.032 y 1.119 V
(antes llegaba a 2.092 V).

**El banco nuevo.** Ahora **sí existe** un banco fijo que cumple el voltaje las 24 horas. El más barato
que lo logra es de **87,25 kvar** (antes hacían falta 378,35 kvar y aun así fallaba una hora).

| | Problema 2 | Problema 2.1 |
|---|---|---|
| Banco | 378,35 kvar | **87,25 kvar** |
| Horas dentro de 950–1.100 V | 23 de 24 | **24 de 24** |
| Corriente máxima en el cable | 26,6 A | 2,7 A |
| Pérdidas al día | 2.234 kWh | 225 kWh |
| Costo total al año | 820,5 M | 87,7 M |
| ¿El banco se paga solo? | No | **Sí, en 78 días** |

**Una sorpresa que vale la pena entender.** Subir el voltaje 5 veces **no** baja las pérdidas 25 veces.
Sin capacitor solo bajan de 632 a 342 kWh al día. ¿Por qué? Porque hay dos resistencias: la del cable
(80 Ω) y la que está pegada al generador (0,5 Ω). Subir el voltaje del cable solo ayuda con la primera.
A 66.000 V, el **96,5 %** de lo que se pierde ya está en la resistencia del generador, y esa no se
arregla subiendo más el voltaje del cable.

Dónde verlo: en la pestaña **Problema 2.1** del dashboard (con su "Análisis" y, debajo, la "Comparación"
contra el Problema 2) y en la sección 7 del reporte. El archivo
[comparison.py](src/optimization/comparison.py) arma la tabla que pone los dos casos lado a lado.

---

## Parte 7 — Cómo ejecutarlo

Abre una terminal en la carpeta `fasorial-capacitores`.

**Instalar (una sola vez):**

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

**Ver el análisis en la terminal, generar todo en `outputs/` y correr la auditoría:**

```powershell
.\.venv\Scripts\python.exe scripts\run_full_analysis.py
```

**Abrir la página web interactiva:**

```powershell
.\.venv\Scripts\streamlit.exe run app\dashboard.py
```

Tiene seis pestañas: *Resumen ejecutivo*, *Problema 1 — 120 V*, *Problema 2 — Optimización
de Qc*, *Problema 2.1 — Línea a 66 kV*, *Modo docente* (los cálculos paso a paso de la Fase 1, la Fase 2 y la
Fase 2.1) y *Simulador what-if* (mover controles y ver
qué pasa).

**Probar con tus propias manos.** Guarda esto como `prueba.py` en la carpeta del proyecto y
ejecútalo con `.\.venv\Scripts\python.exe prueba.py`:

```python
import numpy as np
from src.domain.models import DemandProfile
from src.physics.circuit_solver import solve_problem2

demanda = DemandProfile.default()  # la tabla de 24 horas

sin_banco = solve_problem2(demanda, 0.0)  # sin capacitor
con_banco = solve_problem2(demanda, 50.0)  # con un banco fijo de 50 kvar

print("Hora 1, voltaje sin banco:", round(abs(sin_banco.v_gen[0]), 1), "V")
print("Hora 1, voltaje con banco:", round(abs(con_banco.v_gen[0]), 1), "V")
print("Perdidas del dia sin banco:", round(sin_banco.daily_energy_loss_kwh, 1), "kWh")
print("Perdidas del dia con banco:", round(con_banco.daily_energy_loss_kwh, 1), "kWh")
```

Debe imprimir:

```
Hora 1, voltaje sin banco: 1330.3 V
Hora 1, voltaje con banco: 1096.5 V
Perdidas del dia sin banco: 632.1 kWh
Perdidas del dia con banco: 465.9 kWh
```

Cambia el `50.0` por otros valores y mira cómo se mueven el voltaje y las pérdidas.

---

## Parte 8 — Las pruebas: cómo sabemos que está bien

En la carpeta `tests/` hay **272 pruebas automáticas**. Cada una es una pregunta con respuesta
conocida; si el código responde otra cosa, la prueba falla y avisa.

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

Ejemplo real, de [test_physics_golden.py](tests/test_physics_golden.py:68):

```python
def test_problem1_golden_hour_1(demand):
    r = solve_problem1(demand)
    i1 = r.i_line[0]
    assert abs(i1) == pytest.approx(686.2745098, abs=TOL)  # la corriente debe ser 686,27 A
    assert r.p_loss_kw[0] == pytest.approx(37_913.30258, abs=TOL)  # las pérdidas, 37.913 kW
```

`assert` significa "exijo que esto sea cierto". Es el mismo ejemplo de la hora 1 que hicimos a
mano en la Parte 5.

| Archivo | Qué revisa |
|---|---|
| `test_physics_golden.py` | Que la física dé los valores correctos y que la energía se conserve |
| `test_optimization.py` | Que los óptimos, los intervalos y las cuentas de plata estén bien |
| `test_dashboard_smoke.py` | Que la página web abra sin errores, con solo dos estrategias, botones legibles y el circuito de la Figura 2 |
| `test_audit.py` | Que la auditoría independiente coincida con el programa principal |
| `test_problem_2_1.py` | Los cálculos del Problema 2.1 (66.000 V), su banco y la comparación con el Problema 2 |
| `test_step_by_step.py` | Que el desarrollo paso a paso (Fases 1, 2 y 2.1) dé lo mismo que el programa en las 24 horas |
| `test_dashboard_teaching.py` | Que el Modo docente muestre las tres fases con los números correctos |
| `test_phasor_charts.py` | Que el triángulo de potencias y el diagrama fasorial estén bien calculados y dibujados |

---

## Parte 9 — Glosario

| Palabra | Significado sencillo |
|---|---|
| **Adelanto / atraso** | Adelanto: hay más capacitor del necesario. Atraso: hay justo o menos |
| **Afín** | Que sigue una línea recta: `A + B × algo` |
| **Banco de capacitores** | Grupo de capacitores que fabrican potencia reactiva cerca de la carga |
| **Banda de tensión** | El rango permitido de voltaje del generador: 950 a 1.100 V |
| **CAPEX** | Costo de compra, se paga una vez |
| **Carga** | Lo que consume electricidad (casas, industria) |
| **Conjugado** (`conj`) | Voltear el signo del ángulo de una flecha |
| **COP** | Pesos colombianos |
| **Dataclass** | Caja con etiquetas para guardar datos en Python |
| **Demanda** | Cuánta potencia piden las cargas en cada hora |
| **Factible** | Que cumple las reglas |
| **Factor de potencia (fp)** | Qué parte de lo transportado es útil (de 0 a 1) |
| **Fasor** | Flecha con largo y ángulo que representa una onda eléctrica |
| **Impedancia (Z)** | La oposición total del cable: resistencia + reactancia |
| **Intervalo** | Un rango "desde–hasta" |
| **kW / kvar / kVA** | Unidades de potencia útil / reactiva / total |
| **kWh** | Unidad de energía: 1 kW durante 1 hora. Es lo que se cobra |
| **Minimax** | Hacer lo más pequeño posible el peor caso |
| **OPEX** | Costo de operación, se paga todos los años |
| **Óptimo** | El mejor valor posible |
| **Pareto** | Conjunto de opciones donde mejorar una cosa obliga a empeorar otra |
| **Payback** | Tiempo en que el ahorro paga la inversión |
| **Pérdidas** | Energía que se vuelve calor en el cable y no llega a nadie |
| **Q_C** | Tamaño del banco de capacitores, en kvar |
| **Reactancia (X)** | Oposición del cable que no gasta energía pero sí desfasa y cambia el voltaje |
| **ROI** | Ganancia por cada peso invertido |
| **Transformador** | Aparato que sube o baja el voltaje (y hace lo contrario con la corriente) |
| **V_gen** | Voltaje en el generador |
| **Vectorizado** | Código que calcula las 24 horas de una sola vez |

---

## Parte 10 — Ruta de estudio sugerida

1. Lee las Partes 1 y 2 de esta guía.
2. Abre [constants.py](src/domain/constants.py): son solo números con nombre.
3. Abre [circuit_solver.py](src/physics/circuit_solver.py) y sigue `solve_problem1` con el
   ejemplo de la hora 1 (Parte 5.4), calculadora en mano.
4. Sigue `solve_problem2` igual (Parte 5.5).
5. Ejecuta el `prueba.py` de la Parte 7 y cambia el tamaño del banco.
6. Abre el dashboard y juega con la pestaña *Simulador what-if*.
7. Lee [economics.py](src/optimization/economics.py): son sumas, restas y divisiones.
8. Por último, [capacitor_optimizer.py](src/optimization/capacitor_optimizer.py), en el orden
   de las Partes 5.8 a 5.13.
