from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import math

import openpyxl

import modelo_abasto as engine


LIQUID_REASON = "AGOTAMIENTO · LIQUID ENGINE"
LIQUID_CUT = "ENVIADOS POR LIQUID ENGINE"


def empty_liquid_summary(enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "manual_skus": 0,
        "automatic_tail_enabled": False,
        "candidate_origin_skus": 0,
        "origin_skus_sent": 0,
        "tasks_before": 0,
        "tasks_added": 0,
        "tasks_after": 0,
        "units_added": 0,
        "m3_added": 0.0,
        "stores": 0,
        "products": 0,
        "stock_exhausted_cases": 0,
        "skipped_no_store": 0,
        "skipped_no_capacity": 0,
        "skipped_task_limit": 0,
    }


def parse_manual_skus(raw_value: str) -> set[int]:
    skus: set[int] = set()
    for token in str(raw_value or "").replace("\n", ",").split(","):
        token = token.strip()
        if not token:
            continue
        skus.add(engine.to_id(token, "Liquid Engine.SKU"))
    return skus


def load_store_shares(database_path: Path) -> dict[int, float]:
    """Lee SHARE_VENTAS; acepta proporciones o porcentajes como ponderadores."""
    workbook = openpyxl.load_workbook(database_path, read_only=True, data_only=True)
    try:
        if "SHARE_VENTAS" not in workbook.sheetnames:
            raise ValueError(
                "Liquid Engine requiere la pestaña SHARE_VENTAS con las columnas "
                "WAREHOUSE_ID y SHARE."
            )
        shares: dict[int, float] = {}
        for row in engine.iter_sheet_records(
            workbook,
            "SHARE_VENTAS",
            ["WAREHOUSE_ID", "SHARE"],
        ):
            warehouse = engine.to_id(
                row["WAREHOUSE_ID"],
                "SHARE_VENTAS.WAREHOUSE_ID",
                True,
            )
            if warehouse is None:
                continue
            share = max(engine.to_float(row["SHARE"], 0.0), 0.0)
            if warehouse in shares and not math.isclose(
                shares[warehouse], share, abs_tol=1e-12
            ):
                raise ValueError(
                    "SHARE_VENTAS tiene valores distintos para el warehouse "
                    f"{warehouse}."
                )
            shares[warehouse] = share
        if not shares:
            raise ValueError("SHARE_VENTAS no contiene shares válidos.")
        return shares
    finally:
        workbook.close()


def _weighted_integer_allocation(
    total: int,
    options: list[dict[str, Any]],
    capacity_left: dict[int, int],
) -> dict[int, int]:
    """Distribuye enteros por share, reasignando sobrantes por residuo mayor."""
    allocations: Counter[int] = Counter()
    remaining = int(total)
    active = [option for option in options if capacity_left[option["destination"]] > 0]
    while remaining > 0 and active:
        total_weight = sum(max(float(option["share"]), 0.0) for option in active)
        if total_weight <= 0:
            weights = {option["destination"]: 1.0 for option in active}
            total_weight = float(len(active))
        else:
            weights = {
                option["destination"]: max(float(option["share"]), 0.0)
                for option in active
            }

        raw = {
            option["destination"]: remaining
            * weights[option["destination"]]
            / total_weight
            for option in active
        }
        placed = 0
        for option in active:
            destination = option["destination"]
            quantity = min(
                int(math.floor(raw[destination] + 1e-12)),
                capacity_left[destination],
            )
            if quantity > 0:
                allocations[destination] += quantity
                capacity_left[destination] -= quantity
                placed += quantity
        remaining -= placed
        active = [
            option
            for option in active
            if capacity_left[option["destination"]] > 0
        ]
        if remaining <= 0 or not active:
            break
        ranked = sorted(
            active,
            key=lambda option: (
                -(raw.get(option["destination"], 0.0) % 1),
                -float(option["share"]),
                option["priority"],
                option["destination"],
            ),
        )
        progressed = False
        for option in ranked:
            if remaining <= 0:
                break
            destination = option["destination"]
            if capacity_left[destination] <= 0:
                continue
            allocations[destination] += 1
            capacity_left[destination] -= 1
            remaining -= 1
            progressed = True
        if not progressed:
            break
        active = [
            option
            for option in active
            if capacity_left[option["destination"]] > 0
        ]
    return dict(allocations)


def _doh_level_allocation(
    total: int,
    options: list[dict[str, Any]],
    capacity_left: dict[int, int],
    max_doh: float,
) -> dict[int, int]:
    """Aproxima un DOH común con unidades enteras y un tope estricto."""
    allocations: Counter[int] = Counter()
    doh_options = [
        option
        for option in options
        if option["adu"] > 0
        and option["current_doh"] < max_doh
        and capacity_left[option["destination"]] > 0
    ]
    if total <= 0 or not doh_options:
        return {}

    def requirement(level: float) -> int:
        return sum(
            min(
                max(
                    int(
                        math.floor(
                            (level * option["adu"])
                            - option["current_inventory"]
                            + 1e-9
                        )
                    ),
                    0,
                ),
                capacity_left[option["destination"]],
            )
            for option in doh_options
        )

    low = min(option["current_doh"] for option in doh_options)
    high = max_doh
    for _ in range(48):
        middle = (low + high) / 2
        if requirement(middle) <= total:
            low = middle
        else:
            high = middle

    remaining = int(total)
    for option in doh_options:
        destination = option["destination"]
        quantity = min(
            max(
                int(
                    math.floor(
                        (low * option["adu"])
                        - option["current_inventory"]
                        + 1e-9
                    )
                ),
                0,
            ),
            capacity_left[destination],
            remaining,
        )
        if quantity > 0:
            allocations[destination] += quantity
            capacity_left[destination] -= quantity
            remaining -= quantity

    while remaining > 0:
        eligible = [
            option
            for option in doh_options
            if capacity_left[option["destination"]] > 0
            and (
                option["current_inventory"]
                + allocations[option["destination"]]
                + 1
            )
            / option["adu"]
            <= max_doh + 1e-9
        ]
        if not eligible:
            break
        option = min(
            eligible,
            key=lambda item: (
                (
                    item["current_inventory"]
                    + allocations[item["destination"]]
                )
                / item["adu"],
                item["priority"],
                -item["share"],
                item["destination"],
            ),
        )
        destination = option["destination"]
        allocations[destination] += 1
        capacity_left[destination] -= 1
        remaining -= 1
    return dict(allocations)


def apply_liquid_engine(
    result,
    catalogs,
    config: engine.Config,
    plan_rows: list[dict[str, Any]],
    closed_store_ids: set[int],
    blocked_cities: tuple[str, ...],
    store_shares: dict[int, float],
    manual_skus_by_origin: dict[int, set[int]],
    *,
    automatic_tail: bool,
    automatic_tail_origins: set[int] | None = None,
    forecast_horizon_days: int,
    max_doh: float = 14.0,
    reason_column: str = "PLANNING_REASON",
) -> dict[str, Any]:
    """Agota stock remanente sin rebasar stock, capacidad o tareas globales."""
    summary = empty_liquid_summary(True)
    unknown_origins = set(manual_skus_by_origin) - set(config.origin_warehouses)
    if unknown_origins:
        raise ValueError(
            "Liquid Engine recibió SKUs para orígenes no seleccionados: "
            + ", ".join(map(str, sorted(unknown_origins)))
        )
    summary["manual_skus"] = sum(
        len(skus) for skus in manual_skus_by_origin.values()
    )
    summary["automatic_tail_enabled"] = automatic_tail
    tail_origins = (
        set(config.origin_warehouses)
        if automatic_tail_origins is None
        else set(automatic_tail_origins)
    )
    unknown_tail_origins = tail_origins - set(config.origin_warehouses)
    if unknown_tail_origins:
        raise ValueError(
            "Liquid Engine recibió remanentes automáticos para orígenes no "
            "seleccionados: "
            + ", ".join(map(str, sorted(unknown_tail_origins)))
        )
    summary["tasks_before"] = result.tasks_used
    if forecast_horizon_days <= 0:
        raise ValueError("Los días del horizonte de forecast deben ser mayores a cero.")

    blocked_city_set = set(blocked_cities)
    plan_by_key = {
        (row["WAREHOUSE_DESTINATION"], row["RETAIL_ID"]): row
        for row in plan_rows
    }
    daily_destinations = {
        row["WAREHOUSE_DESTINATION"]
        for row in plan_rows
        if row["WAREHOUSE_DESTINATION"] not in closed_store_ids
        and catalogs.stores.get(row["WAREHOUSE_DESTINATION"], {}).get(
            "city_norm", ""
        )
        not in blocked_city_set
    }

    consumed_stock: Counter[tuple[int, int]] = Counter()
    planned_incoming: Counter[tuple[int, int]] = Counter()
    for allocation in result.allocation_rows:
        consumed_stock[
            (allocation["WAREHOUSE_SOURCE"], allocation["RETAIL_ID"])
        ] += int(allocation["QUANTITY"])
        planned_incoming[
            (allocation["WAREHOUSE_DESTINATION"], allocation["RETAIL_ID"])
        ] += int(allocation["QUANTITY"])

    source_info: dict[tuple[int, int], dict[str, Any]] = {}
    stock_remaining: dict[tuple[int, int], int] = {}
    candidates: list[dict[str, Any]] = []
    for source in config.origin_warehouses:
        source_manual_skus = set(manual_skus_by_origin.get(source, set()))
        source_skus = {
            sku
            for warehouse, sku in catalogs.stock_base
            if warehouse == source
        }
        for sku in source_skus | source_manual_skus:
            info = engine.source_stock_components(catalogs, source, sku)
            remaining = max(
                int(info["adjusted"])
                - consumed_stock.get((source, sku), 0),
                0,
            )
            source_info[(source, sku)] = info
            stock_remaining[(source, sku)] = remaining
            is_manual = sku in source_manual_skus
            is_tail = (
                automatic_tail
                and source in tail_origins
                and 0 < remaining < 10
            )
            if remaining > 0 and (is_manual or is_tail):
                priority_rank = 2
                for destination in daily_destinations:
                    store = catalogs.stores.get(destination)
                    if not store:
                        continue
                    city_norm = store.get("city_norm", "")
                    is_golden = bool(city_norm) and (
                        sku,
                        city_norm,
                    ) in catalogs.golden_infaltables
                    if engine.is_regional_block(
                        catalogs,
                        source,
                        destination,
                        sku,
                        city_norm,
                        is_golden,
                    ):
                        continue
                    if is_golden:
                        priority_rank = 0
                        break
                    if (destination, sku) in catalogs.kvi_products:
                        priority_rank = min(priority_rank, 1)
                candidates.append(
                    {
                        "source": source,
                        "sku": sku,
                        "remaining": remaining,
                        "manual": is_manual,
                        "priority_rank": priority_rank,
                    }
                )

    candidates.sort(
        key=lambda row: (
            row["priority_rank"],
            0 if row["manual"] else 1,
            -row["remaining"],
            config.origin_warehouses.index(row["source"]),
            row["sku"],
        )
    )
    summary["candidate_origin_skus"] = len(candidates)

    capacity_by_store = {
        row["WAREHOUSE_DESTINATION"]: row for row in result.capacity_rows
    }
    existing_allocations = {
        (
            row["WAREHOUSE_SOURCE"],
            row["WAREHOUSE_DESTINATION"],
            row["RETAIL_ID"],
        ): row
        for row in result.allocation_rows
    }
    stores_sent: set[int] = set()
    products_sent: set[int] = set()
    next_order = len(result.base_rows) + 1

    for candidate in candidates:
        source = candidate["source"]
        sku = candidate["sku"]
        available_stock = stock_remaining[(source, sku)]
        if available_stock <= 0:
            continue
        m3_per_unit = catalogs.volume_m3.get(sku, config.default_m3_per_unit)
        options: list[dict[str, Any]] = []
        for destination in daily_destinations:
            if destination == source:
                continue
            store = catalogs.stores.get(destination)
            if not store:
                continue
            city_norm = store.get("city_norm", "")
            if (destination, sku) in catalogs.route_cost_blocks:
                continue
            is_golden = bool(city_norm) and (
                sku,
                city_norm,
            ) in catalogs.golden_infaltables
            is_kvi = (destination, sku) in catalogs.kvi_products
            if engine.is_regional_block(
                catalogs,
                source,
                destination,
                sku,
                city_norm,
                is_golden,
            ):
                continue

            capacity = catalogs.store_capacity.get(
                destination,
                config.default_store_capacity_m3,
            )
            capacity_row = capacity_by_store.get(destination)
            used_m3 = (
                float(capacity_row["M3_CONTABILIZADO_CAPACIDAD"])
                if capacity_row
                else 0.0
            )
            remaining_m3 = max(capacity - used_m3, 0.0)
            capacity_units = (
                int(math.floor((remaining_m3 / m3_per_unit) + 1e-9))
                if m3_per_unit > 0
                else available_stock
            )
            if capacity_units <= 0:
                continue

            plan_row = plan_by_key.get((destination, sku), {})
            predicted_demand = max(
                engine.to_float(plan_row.get("PREDICTED_DEMAND", 0.0)),
                0.0,
            )
            adu = predicted_demand / forecast_horizon_days
            current_inventory = max(
                float(catalogs.stock_base.get((destination, sku), 0.0)),
                0.0,
            ) + planned_incoming.get((destination, sku), 0)
            current_doh = current_inventory / adu if adu > 0 else math.inf
            allocation_key = (source, destination, sku)
            options.append(
                {
                    "destination": destination,
                    "store": store,
                    "city_norm": city_norm,
                    "is_golden": is_golden,
                    "is_kvi": is_kvi,
                    "priority": catalogs.store_priority.get(destination, 100),
                    "share": max(store_shares.get(destination, 0.0), 0.0),
                    "adu": adu,
                    "current_inventory": current_inventory,
                    "current_doh": current_doh,
                    "capacity": capacity,
                    "capacity_units": capacity_units,
                    "existing_task": allocation_key in existing_allocations,
                }
            )

        if not options:
            summary["skipped_no_store"] += 1
            continue

        task_slots = max(config.max_tasks - result.tasks_used, 0)
        existing_options = [option for option in options if option["existing_task"]]
        new_options = sorted(
            (option for option in options if not option["existing_task"]),
            key=lambda option: (
                0 if option["is_golden"] else (1 if option["is_kvi"] else 2),
                0 if math.isfinite(option["current_doh"]) else 1,
                option["current_doh"],
                option["priority"],
                -option["share"],
                option["destination"],
            ),
        )[:task_slots]
        allowed_options = existing_options + new_options
        if not allowed_options:
            summary["skipped_task_limit"] += 1
            continue

        capacity_left = {
            option["destination"]: option["capacity_units"]
            for option in allowed_options
        }
        doh_allocations = _doh_level_allocation(
            available_stock,
            allowed_options,
            capacity_left,
            max_doh,
        )
        assigned_doh = sum(doh_allocations.values())
        share_allocations = _weighted_integer_allocation(
            available_stock - assigned_doh,
            allowed_options,
            capacity_left,
        )
        planned = Counter(doh_allocations)
        planned.update(share_allocations)
        planned = Counter(
            {
                destination: quantity
                for destination, quantity in planned.items()
                if quantity > 0
            }
        )
        if not planned:
            summary["skipped_no_capacity"] += 1
            continue

        option_by_destination = {
            option["destination"]: option for option in allowed_options
        }
        assigned_total = 0
        tasks_added_for_candidate = 0
        for destination, quantity in planned.items():
            option = option_by_destination[destination]
            allocation_key = (source, destination, sku)
            existing = existing_allocations.get(allocation_key)
            if existing is not None:
                existing["QUANTITY"] = int(existing["QUANTITY"]) + int(quantity)
                previous_reason = str(existing.get(reason_column, "")).strip()
                if LIQUID_REASON not in previous_reason:
                    existing[reason_column] = (
                        f"{previous_reason} + {LIQUID_REASON}"
                        if previous_reason
                        else LIQUID_REASON
                    )
                is_new_task = False
            else:
                if result.tasks_used >= config.max_tasks:
                    break
                existing = {
                    "WAREHOUSE_DESTINATION": destination,
                    "WAREHOUSE_SOURCE": source,
                    "RETAIL_ID": sku,
                    "QUANTITY": int(quantity),
                    "PLANNED_DATE": "",
                    "ROUTE": 1,
                    "DELIVERY_PRIORITY": 1,
                    "CITY": option["store"].get("city", ""),
                    "STORAGE": catalogs.storage.get(sku) or "Room Temperature",
                    "VALUE": catalogs.high_value.get(sku, "REGULAR"),
                    reason_column: LIQUID_REASON,
                }
                result.allocation_rows.append(existing)
                existing_allocations[allocation_key] = existing
                result.tasks_used += 1
                tasks_added_for_candidate += 1
                is_new_task = True

            assigned_total += int(quantity)
            stock_remaining[(source, sku)] -= int(quantity)
            planned_incoming[(destination, sku)] += int(quantity)
            assigned_m3 = int(quantity) * m3_per_unit
            capacity_row = capacity_by_store.get(destination)
            if capacity_row is None:
                capacity_row = {
                    "WAREHOUSE_DESTINATION": destination,
                    "WAREHOUSE_NAME": option["store"].get("warehouse_name", ""),
                    "CITY": option["store"].get("city", ""),
                    "CAPACIDAD_M3": option["capacity"],
                    "M3_CONTABILIZADO_CAPACIDAD": 0.0,
                    "M3_TOTAL_ASIGNADO_INCLUYE_GOLDEN": 0.0,
                    "CAPACIDAD_CERRADA": False,
                    "CAPACIDAD_SUPERADA_POR_LINEA": False,
                }
                result.capacity_rows.append(capacity_row)
                capacity_by_store[destination] = capacity_row
            cap_before = float(capacity_row["M3_CONTABILIZADO_CAPACIDAD"])
            cap_after = cap_before + assigned_m3
            capacity_row["M3_CONTABILIZADO_CAPACIDAD"] = cap_after
            capacity_row["M3_TOTAL_ASIGNADO_INCLUYE_GOLDEN"] = (
                float(capacity_row["M3_TOTAL_ASIGNADO_INCLUYE_GOLDEN"])
                + assigned_m3
            )
            capacity_row["CAPACIDAD_CERRADA"] = (
                cap_after >= float(capacity_row["CAPACIDAD_M3"]) - 1e-9
            )

            info = source_info[(source, sku)]
            base_row = {
                "ORDEN_PLANIFICACION": next_order,
                "FILA_INPUT": "LIQUID",
                "FILAS_INPUT_CONSOLIDADAS": "LIQUID",
                "CANTIDAD_FILAS_INPUT": 0,
                "DUPLICADO_CONFLICTIVO": False,
                "WAREHOUSE_DESTINATION": destination,
                "WAREHOUSE_NAME": option["store"].get("warehouse_name", ""),
                "CITY": option["store"].get("city", ""),
                "RETAIL_ID": sku,
                "SKU_NAME": "",
                "PREDICTED_OPENING_INVENTORY": option["current_inventory"],
                "PREDICTED_DEMAND": option["adu"] * forecast_horizon_days,
                "CURRENT_INVENTORY": option["current_inventory"],
                "MOV_ORIGINAL": 0,
                "REGLA_DEMANDA": "LIQUID_ENGINE",
                "CANTIDAD_OBJETIVO": int(quantity),
                "CANTIDAD_ASIGNADA": int(quantity),
                "CANTIDAD_FALTANTE": 0,
                "ES_GOLDEN_INFALTABLE": option["is_golden"],
                "ES_KVI": option["is_kvi"],
                "PRIORIDAD_TIENDA": option["priority"],
                "ES_STOCKOUT": option["current_inventory"] <= 0,
                "SIN_RUTA_COSTOS": False,
                "M3_POR_UNIDAD": m3_per_unit,
                "M3_OBJETIVO": assigned_m3,
                "M3_ASIGNADO": assigned_m3,
                "CAPACIDAD_TIENDA_M3": option["capacity"],
                "M3_CAPACIDAD_ANTES": cap_before,
                "M3_CAPACIDAD_DESPUES": cap_after,
                "EXCEDE_CAPACIDAD_EN_ESTA_LINEA": False,
                "PASA_CAPACIDAD": True,
                "TAREAS_ANTES": result.tasks_used - int(is_new_task),
                "TAREAS_GENERADAS": int(is_new_task),
                "TAREAS_ACUMULADAS": result.tasks_used,
                "PASA_TAREAS": True,
                "ORIGENES_USADOS": f"{source}:{int(quantity)}",
                "STORAGE": catalogs.storage.get(sku) or "Room Temperature",
                "VALUE": catalogs.high_value.get(sku, "REGULAR"),
                "TIPO_DE_CORTE": LIQUID_CUT,
                "DETALLE_MOTIVO": (
                    "Liquid Engine distribuyó inventario remanente por nivelación "
                    "de DOH y share general, respetando el presupuesto global."
                ),
            }
            for configured_source in config.origin_warehouses:
                configured_info = source_info.get((configured_source, sku))
                if configured_info is None:
                    configured_info = engine.source_stock_components(
                        catalogs,
                        configured_source,
                        sku,
                    )
                    source_info[(configured_source, sku)] = configured_info
                    stock_remaining.setdefault(
                        (configured_source, sku),
                        max(
                            int(configured_info["adjusted"])
                            - consumed_stock.get((configured_source, sku), 0),
                            0,
                        ),
                    )
                base_row.update(
                    {
                        f"STOCK_BASE_{configured_source}": configured_info["base"],
                        f"NO_DISPONIBLE_{configured_source}": configured_info["unavailable"],
                        f"COPERNICO_NO_USABLE_{configured_source}": configured_info[
                            "copernico_unusable"
                        ],
                        f"RACKEADO_{configured_source}": configured_info["rackeado"],
                        f"STOCK_INICIAL_AJUSTADO_{configured_source}": configured_info[
                            "adjusted"
                        ],
                        f"STOCK_ANTES_{configured_source}": (
                            stock_remaining[(configured_source, sku)]
                            + (int(quantity) if configured_source == source else 0)
                        ),
                        f"BLOQUEO_REGIONAL_{configured_source}": False,
                        f"ASIGNADO_{configured_source}": (
                            int(quantity) if configured_source == source else 0
                        ),
                        f"STOCK_REMANENTE_{configured_source}": stock_remaining[
                            (configured_source, sku)
                        ],
                    }
                )
            result.base_rows.append(base_row)
            next_order += 1
            stores_sent.add(destination)

        if assigned_total > 0:
            summary["origin_skus_sent"] += 1
            summary["tasks_added"] += tasks_added_for_candidate
            summary["units_added"] += assigned_total
            summary["m3_added"] += assigned_total * m3_per_unit
            summary["stock_exhausted_cases"] += int(
                stock_remaining[(source, sku)] <= 0
            )
            products_sent.add(sku)

    result.capacity_rows.sort(key=lambda row: row["WAREHOUSE_DESTINATION"])
    summary["tasks_after"] = result.tasks_used
    summary["stores"] = len(stores_sent)
    summary["products"] = len(products_sent)
    summary["m3_added"] = round(summary["m3_added"], 3)
    return summary
