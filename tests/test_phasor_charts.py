"""Triángulo de potencias, diagrama fasorial y animación: cálculos y disposición visual (Problemas 2 y 2.1)."""

from __future__ import annotations

import numpy as np
import pytest

from src.optimization.pipeline import run_full_analysis, run_problem_2_1
from src.reporting import charts as CH

N_PHASORS = 7  # V₀ referida, caída R, caída X, caída total, V_gen, I sin Q_C, I_gen


@pytest.fixture(scope="module")
def b2():
    return run_full_analysis(include_sensitivity=False)


@pytest.fixture(scope="module")
def b21():
    return run_problem_2_1()


def _cases(b2, b21):
    return [(b, r) for b in (b2, b21) for r in b.strategies.values()]


def _has_detail(fig) -> bool:
    """True si la figura tiene el segundo panel (detalle ampliado)."""
    return "yaxis2" in fig.layout.to_plotly_json()


def _inside(z: complex, x_range, y_range) -> bool:
    return x_range[0] <= z.real <= x_range[1] and y_range[0] <= z.imag <= y_range[1]


# ----------------------------------------------------------------------------------
# Cálculos del diagrama fasorial
# ----------------------------------------------------------------------------------
def test_phasor_components_close_the_voltage_triangle(b2, b21) -> None:
    """V₀·a₂/n₁ + I·R_eq/n₁ + jI·X/n₁ = V_gen en las 24 horas de cada caso y estrategia."""
    for b, r in _cases(b2, b21):
        no_cap = b.no_capacitor.circuit
        for t in range(24):
            ph = CH.phasor_components(r.circuit, b.params, t, b.demand)
            assert ph["V0_ref"] == pytest.approx(1000.0)  # la misma referencia a 13.2 kV y a 66 kV
            assert ph["drop_R"] + ph["drop_X"] == pytest.approx(ph["drop"], rel=1e-12)
            assert ph["V0_ref"] + ph["drop_R"] + ph["drop_X"] == pytest.approx(ph["V_gen"], rel=1e-12)
            assert ph["V_gen"] == pytest.approx(r.circuit.v_gen[t], rel=1e-12)
            assert ph["I_gen"] == pytest.approx(r.circuit.i_gen[t], rel=1e-12)
            assert ph["I_load_sin_QC"] == pytest.approx(no_cap.i_gen[t], rel=1e-12)
            # las caídas, vistas desde el generador, son I_gen por la impedancia reflejada
            z = b.params.z_gen_side
            assert ph["drop_R"] == pytest.approx(ph["I_gen"] * z.real, rel=1e-12)
            assert ph["drop_X"] == pytest.approx(ph["I_gen"] * 1j * z.imag, rel=1e-12)


def test_reactive_drop_dominates_at_13kv_and_resistive_at_66kv(b2, b21) -> None:
    ph2 = CH.phasor_components(b2.no_capacitor.circuit, b2.params, 11, b2.demand)
    ph21 = CH.phasor_components(b21.no_capacitor.circuit, b21.params, 11, b21.demand)
    assert abs(ph2["drop_X"]) == pytest.approx(1177.4, abs=0.1) and abs(ph2["drop_R"]) == pytest.approx(218.6, abs=0.1)
    assert abs(ph21["drop_X"]) == pytest.approx(47.1, abs=0.1) and abs(ph21["drop_R"]) == pytest.approx(118.2, abs=0.1)
    assert abs(ph2["drop_X"]) / abs(ph21["drop_X"]) == pytest.approx(25.0)  # (66 / 13.2)²


# ----------------------------------------------------------------------------------
# Vista: rangos fijos para todo el día y detalle ampliado a 66 kV
# ----------------------------------------------------------------------------------
def test_view_contains_every_phasor_of_the_day(b2, b21) -> None:
    for b, r in _cases(b2, b21):
        all_ph = CH._day_phasors(r.circuit, b.params, b.demand)
        scale = CH._day_current_scale(all_ph)
        view = CH.phasor_view(all_ph, scale, b.params)
        for ph in all_ph:
            tip_r = ph["V0_ref"] + ph["drop_R"]
            for z in (0j, ph["V0_ref"], tip_r, ph["V_gen"], ph["I_gen"] * scale, ph["I_load_sin_QC"] * scale):
                assert _inside(z, view.x, view.y)
            if view.has_zoom:
                for z in (ph["V0_ref"], tip_r, ph["V_gen"]):
                    assert _inside(z, view.zoom_x, view.zoom_y)
        width, height = view.x[1] - view.x[0], view.y[1] - view.y[0]
        assert 0.44 <= height / width <= 1 / 0.44  # ni franja horizontal ni vertical


def test_detail_panel_only_when_drops_are_small(b2, b21) -> None:
    for r in b2.strategies.values():  # a 13.2 kV la caída es del orden de V₀: se ve a escala completa
        fig = CH.fig_phasor_diagram(r.circuit, b2.params, b2.demand, 11)
        assert not _has_detail(fig) and len(fig.data) == N_PHASORS + 2
        assert fig.layout.height == CH.PHASOR_HEIGHT
    for r in b21.strategies.values():  # a 66 kV la caída es ~10 % de V₀: hace falta el detalle
        fig = CH.fig_phasor_diagram(r.circuit, b21.params, b21.demand, 11)
        assert _has_detail(fig) and len(fig.data) == 2 * (N_PHASORS + 2)
        assert fig.layout.height == CH.PHASOR_ZOOM_HEIGHT
        zoom_x, zoom_y = fig.layout.xaxis2.range, fig.layout.yaxis2.range
        assert zoom_x[1] - zoom_x[0] < 0.25 * (fig.layout.xaxis.range[1] - fig.layout.xaxis.range[0])
        assert zoom_x[0] < 950 < 1100 < zoom_x[1]  # los dos límites de la banda entran en el detalle
        assert zoom_y[0] < 0 < zoom_y[1]
        labels = [a.text for a in fig.layout.annotations]
        assert "|V| = 950 V" in labels and "|V| = 1100 V" in labels
        assert any(t.startswith("Detalle ampliado del recuadro") for t in labels)
        assert len(fig.layout.shapes) == 1  # recuadro que marca la zona ampliada en la vista completa
        assert sum(t.showlegend is not False for t in fig.data) == N_PHASORS + 1  # la leyenda no se duplica


def test_axes_are_equal_scale_and_do_not_stretch(b2, b21) -> None:
    for b, r in _cases(b2, b21):
        fig = CH.fig_phasor_diagram(r.circuit, b.params, b.demand, 3)
        axes = [(fig.layout.xaxis, fig.layout.yaxis, "x")]
        if _has_detail(fig):
            axes.append((fig.layout.xaxis2, fig.layout.yaxis2, "x2"))
        for xaxis, yaxis, anchor in axes:
            assert yaxis.scaleanchor == anchor and yaxis.scaleratio == 1
            assert xaxis.constrain == "domain" and yaxis.constrain == "domain"  # el eje no se estira al ancho
            assert max(abs(v) for v in xaxis.range) < 2500 and max(abs(v) for v in yaxis.range) < 2500
        other = CH.fig_phasor_diagram(r.circuit, b.params, b.demand, 18)
        assert tuple(other.layout.xaxis.range) == tuple(fig.layout.xaxis.range)  # mismos ejes a cualquier hora
        assert tuple(other.layout.yaxis.range) == tuple(fig.layout.yaxis.range)
        assert [t.name for t in other.data] == [t.name for t in fig.data]  # y misma escala de corrientes


def test_legend_sits_under_the_title(b2, b21) -> None:
    """La leyenda va anclada al contenedor para que, al partirse en renglones, no tape el título."""
    for b, r in _cases(b2, b21):
        figures = [
            CH.fig_phasor_diagram(r.circuit, b.params, b.demand, 11),
            CH.fig_phasor_animation(r.circuit, b.params, b.demand),
            CH.fig_power_triangle(165.0, 157.27, float(r.q_c_profile_kvar[11])),
        ]
        for fig in figures:
            legend = fig.layout.legend
            assert legend.orientation == "h" and legend.yref == "container" and legend.yanchor == "top"
            assert 0.9 < legend.y < 1.0 and legend.x == 0.5 and legend.xanchor == "center"
            assert (1 - legend.y) * fig.layout.height == pytest.approx(CH._TITLE_BAND_PX)


def test_band_circles_are_complete(b21) -> None:
    fig = CH.fig_phasor_diagram(b21.no_capacitor.circuit, b21.params, b21.demand, 11)
    band = [t for t in fig.data if t.legendgroup == "banda"]
    assert len(band) == 4  # dos círculos por panel
    radii = sorted({round(float(np.hypot(t.x[0], t.y[0]))) for t in band})
    assert radii == [950, 1100]
    for t in band:  # círculo completo: V_gen queda bajo el eje real en las horas pico sin capacitor
        assert min(t.y) < -900 and max(t.y) > 900
    v_gen = b21.no_capacitor.circuit.v_gen[11]
    assert v_gen.imag < 0 and abs(v_gen) > 1100


# ----------------------------------------------------------------------------------
# Animación de las 24 horas
# ----------------------------------------------------------------------------------
def test_animation_has_one_frame_per_hour(b2, b21) -> None:
    for b, r in _cases(b2, b21):
        fig = CH.fig_phasor_animation(r.circuit, b.params, b.demand)
        static = CH.fig_phasor_diagram(r.circuit, b.params, b.demand, 0)
        n_dyn = len(fig.data) - len([t for t in fig.data if t.legendgroup == "banda"])
        assert [f.name for f in fig.frames] == [str(h) for h in range(1, 25)]
        assert all(len(f.data) == n_dyn and list(f.traces) == list(range(n_dyn)) for f in fig.frames)
        assert tuple(fig.layout.xaxis.range) == tuple(static.layout.xaxis.range)  # mismos ejes que el estático
        assert fig.layout.height == static.layout.height + CH.ANIMATION_EXTRA_HEIGHT
        for t, frame in enumerate(fig.frames):
            v_gen = r.circuit.v_gen[t]
            trace = next(tr for tr in frame.data if tr.name == "V_gen")
            assert (trace.x[1], trace.y[1]) == pytest.approx((v_gen.real, v_gen.imag))
            assert f"hora {t + 1}" in frame.layout.title.text and f"{abs(v_gen):,.1f} V" in frame.layout.title.text
        slider, menu = fig.layout.sliders[0], fig.layout.updatemenus[0]
        assert [s.label for s in slider.steps] == [str(h) for h in range(1, 25)]
        assert [btn.label for btn in menu.buttons] == ["Reproducir", "Pausa"]
        # controles separados de la gráfica en píxeles (no en fracción del alto) y sin encimarse entre sí
        assert menu.y == 0 and slider.y == 0 and menu.pad.t >= 60 and slider.pad.t >= 40
        assert slider.pad.l >= 150 and fig.layout.margin.b >= 110


# ----------------------------------------------------------------------------------
# Triángulo de potencias
# ----------------------------------------------------------------------------------
def test_power_triangle_values_and_fixed_axes(b2, b21) -> None:
    d = b21.demand
    p, q = float(d.p_total_kw[11]), float(d.q_total_kvar[11])
    fig = CH.fig_power_triangle(p, q, 87.25, p_day=d.p_total_kw, q_day=d.q_total_kvar)
    names = [t.name for t in fig.data]
    assert names == [
        "P = 165.00 kW",
        "Q_L = 157.27 kvar",
        "S antes = 227.95 kVA (fp 0.724 at.)",
        "−Q_C = −87.25 kvar",
        "S después = 179.24 kVA (fp 0.921 at.)",
    ]
    leading = CH.fig_power_triangle(p, q, 378.35, p_day=d.p_total_kw, q_day=d.q_total_kvar)
    assert leading.data[-1].name == "S después = 275.86 kVA (fp 0.598 ad.)"
    assert leading.data[-1].y[1] == pytest.approx(q - 378.35)
    assert len(CH.fig_power_triangle(p, q, 0.0).data) == 4  # sin banco no hay tramo −Q_C
    # ejes fijos para todo el día: al cambiar de hora no cambia la escala
    other = CH.fig_power_triangle(
        float(d.p_total_kw[3]), float(d.q_total_kvar[3]), 87.25, p_day=d.p_total_kw, q_day=d.q_total_kvar
    )
    assert tuple(other.layout.xaxis.range) == tuple(fig.layout.xaxis.range)
    assert tuple(other.layout.yaxis.range) == tuple(fig.layout.yaxis.range)
    for figure in (fig, leading, other):
        x_range, y_range = figure.layout.xaxis.range, figure.layout.yaxis.range
        assert figure.layout.yaxis.scaleanchor == "x" and figure.layout.xaxis.constrain == "domain"
        assert x_range[0] < 0 < 165 * 1.04 < x_range[1]
        for trace in figure.data:
            assert all(x_range[0] <= x <= x_range[1] for x in trace.x)
            assert all(y_range[0] <= y <= y_range[1] for y in trace.y)
        assert (x_range[1] - x_range[0]) >= 0.55 * (y_range[1] - y_range[0])  # el recuadro no es una franja


def test_triangle_height_matches_phasor_diagram(b2, b21) -> None:
    for b, r in _cases(b2, b21):
        phasor = CH.fig_phasor_diagram(r.circuit, b.params, b.demand, 11)
        triangle = CH.fig_power_triangle(165.0, 157.27, 0.0, height=int(phasor.layout.height))
        assert triangle.layout.height == phasor.layout.height  # las dos gráficas van lado a lado
