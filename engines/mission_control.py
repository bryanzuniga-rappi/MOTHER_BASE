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
    include_solidus: bool,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Prepara la cola secuencial que consumirá el ledger global."""
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
            or (solidus and include_solidus)
            or (no_recommendation and include_naked)
        )
        if accepted:
            selected.append(row)
        else:
            summary["omitted_by_loadout"] += 1
    return selected, summary

