"""Mission Control — cola secuencial de requerimientos.

Posición: antes de la asignación; decide qué filas entran a la pasada base de Naked
(recomendación natural y mínimos).
Entrada: filas consolidadas del Bulk.
Salida: cola ordenada y conteos por engine.
"""

from __future__ import annotations

from typing import Any

import modelo_abasto as engine

from engines.naked_engine import is_naked_requirement, is_no_recommendation
from engines.solidus_engine import is_solidus_requirement


def select_engine_rows(
    rows: list[dict[str, Any]],
    config: engine.Config,
    *,
    include_naked: bool,
    include_hardcodes: bool,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Arma la cola secuencial de requerimientos. include_hardcodes activa
    HARDCODE_4_CERO_TOTAL y HARDCODE_3_INVENTARIO_MENOR_DEMANDA (MOV <= 0 con
    objetivo armado por el modelo).
    """
    selected: list[dict[str, Any]] = []
    summary = {
        "naked_requirements": 0,
        "solidus_requirements": 0,
        "no_recommendation_rows": 0,
        "omitted_by_loadout": 0,
    }
    for row in rows:
        naked = is_naked_requirement(row, config)
        solidus = is_solidus_requirement(row, config)
        no_recommendation = is_no_recommendation(row, config)
        row["ES_MANUAL_FORECAST_ZERO"] = solidus
        if naked:
            summary["naked_requirements"] += 1
        elif solidus:
            summary["solidus_requirements"] += 1
        elif no_recommendation:
            summary["no_recommendation_rows"] += 1

        accepted = (
            (naked and include_naked)
            or (solidus and include_hardcodes)
            or (no_recommendation and include_naked)
        )
        if accepted:
            selected.append(row)
        else:
            summary["omitted_by_loadout"] += 1
    return selected, summary

