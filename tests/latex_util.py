"""Comprobaciones de higiene para LaTeX (KaTeX) y Markdown, compartidas por varias pruebas."""

from __future__ import annotations

import re

# Comandos LaTeX permitidos en las ecuaciones y en el Markdown del dashboard. Un comando pegado a una letra
# (p. ej. ``\quadP``, ``\cdotI``) se lee como un comando distinto que no está en esta lista.
LATEX_COMMANDS = frozenset({
    "Delta", "Omega", "angle", "approx", "begin", "cdot", "circ", "cos", "end", "frac", "ge", "in", "le", "left",
    "mathrm", "max", "min", "qquad", "quad", "right", "tan", "text", "times", "varepsilon",
})  # fmt: skip

LATEX_CMD = re.compile(r"\\([A-Za-z]+)")
INLINE_MATH = re.compile(r"(?<!\\)\$([^$]+)(?<!\\)\$")
UNESCAPED_DOLLAR = re.compile(r"(?<!\\)\$")
CURRENCY = re.compile(r"(?<!\\)\$\s\d")  # «$ 1.000»: signo de pesos sin escapar seguido de la cifra


def unknown_commands(source: str) -> set[str]:
    """Comandos LaTeX de ``source`` que no están en la lista permitida (incluye los pegados a una letra)."""
    return {f"\\{cmd}" for cmd in LATEX_CMD.findall(source) if cmd not in LATEX_COMMANDS}


def braces_balanced(source: str) -> bool:
    depth = 0
    for prev, char in zip(" " + source, source, strict=False):
        if prev == "\\":
            continue
        depth += char == "{"
        depth -= char == "}"
        if depth < 0:
            return False
    return depth == 0


def markdown_dollar_problems(text: str) -> list[str]:
    """Problemas con el signo ``$`` en un texto Markdown de Streamlit.

    Un ``$`` de moneda debe ir escapado (``\\$``); los que quedan sin escapar deben formar parejas ``$…$`` de
    LaTeX en línea, y su contenido solo puede usar comandos conocidos.
    """
    problems = []
    if CURRENCY.search(text):
        problems.append("moneda sin escapar")
    if len(UNESCAPED_DOLLAR.findall(text)) % 2:
        problems.append("número impar de $ sin escapar")
    for math in INLINE_MATH.findall(text):
        bad = unknown_commands(math)
        if bad:
            problems.append(f"comandos desconocidos en ${math}$: {sorted(bad)}")
    return problems
