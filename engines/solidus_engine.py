"""Solidus Engine — protección manual sin ROQ positivo.

Posición: junto a Naked, sobre la misma fila consolidada del Bulk.
Entrada: fila con ROQ <= 0 pero con objetivo > 0 por reglas de mínimo/hardcode.
Salida: predicado is_solidus_requirement.
Las coberturas de catálogo de Solidus (AVL, Preventivo, Refuerzo, Cobertura
sin Fountain9) viven en modules/les_enfants_terribles.py (apply_avl_fill).
"""

from __future__ import annotations

from typing import Any

import modelo_abasto as engine


def is_solidus_requirement(
    row: dict[str, Any],
    config: engine.Config,
) -> bool:
    """Identifica una protección manual que no nació de un ROQ positivo."""
    original_roq = engine.to_float(
        row.get("ROQ_INPUT", row.get("MOV_ORIGINAL", 0.0)),
        0.0,
    )
    target, _ = engine.calculate_target_quantity(row, config)
    return original_roq <= 0 and target > 0

