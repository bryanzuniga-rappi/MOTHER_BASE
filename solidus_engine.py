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

