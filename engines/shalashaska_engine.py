from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any
import math

import openpyxl

import modelo_abasto as engine


SHALASHASKA_REASON = "EVACUACIÓN · SHALASHASKA ENGINE"
SHALASHASKA_CUT = "ENVIADOS POR SHALASHASKA ENGINE"


def empty_shalashaska_summary(enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "candidate_origin_skus": 0,
        "origin_skus_sent": 0,
        "origin_skus_fully_evacuated": 0,
        "tasks_before": 0,
        "tasks_added": 0,
        "tasks_after": 0,
        "units_reported": 0,
        "units_at_risk": 0,
        "units_eligible_after_stock": 0,
        "units_evacuated": 0,
        "units_not_evacuated": 0,
        "units_capped_by_stock": 0,
        "value_at_risk": 0.0,
        "value_protected": 0.0,
        "m3_added": 0.0,
        "stores": 0,
        "products": 0,
        "skipped_origin_not_selected": 0,
        "skipped_excluded_sku": 0,
        "skipped_no_store": 0,
        "skipped_no_adu": 0,
        "skipped_no_capacity": 0,
        "skipped_task_limit": 0,
        "skipped_regional_block": 0,
    }


def _parse_date(value: Any, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = engine.clean_text(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{field_name}: fecha inválida {value!r}")


def load_expiring_inventory(database_path: Path) -> list[dict[str, Any]]:
    """Lee y consolida POR_MERMAR por origen-SKU sin usarla como stock mandante."""
    workbook = openpyxl.load_workbook(database_path, read_only=True, data_only=True)
    try:
        if "POR_MERMAR" not in workbook.sheetnames:
            raise ValueError(
                "Shalashaska Engine requiere la pestaña POR_MERMAR con las columnas "
                "WAREHOUSE_ID, PRODUCT_ID, STOCK_AVAILABLE, VALUE_STOCK, "
                "ARRIVAL_DATE y EXPIRATION_DATE."
            )
        consolidated: dict[tuple[int, int], dict[str, Any]] = {}
        for row in engine.iter_sheet_records(
            workbook,
            "POR_MERMAR",
            [
                "WAREHOUSE_ID",
                "PRODUCT_ID",
                "STOCK_AVAILABLE",
                "VALUE_STOCK",
                "ARRIVAL_DATE",
                "EXPIRATION_DATE",
            ],
        ):
            source = engine.to_id(
                row["WAREHOUSE_ID"], "POR_MERMAR.WAREHOUSE_ID", True
            )
            sku = engine.to_id(row["PRODUCT_ID"], "POR_MERMAR.PRODUCT_ID", True)
            if source is None or sku is None:
                continue
            stock = max(int(math.floor(engine.to_float(row["STOCK_AVAILABLE"], 0.0))), 0)
            if stock <= 0:
                continue
            value = max(engine.to_float(row["VALUE_STOCK"], 0.0), 0.0)
            arrival = _parse_date(row["ARRIVAL_DATE"], "POR_MERMAR.ARRIVAL_DATE")
            expiration = _parse_date(
                row["EXPIRATION_DATE"], "POR_MERMAR.EXPIRATION_DATE"
            )
            key = (source, sku)
            if key not in consolidated:
                consolidated[key] = {
                    "WAREHOUSE_SOURCE": source,
                    "RETAIL_ID": sku,
                    "STOCK_AVAILABLE": 0,
                    "VALUE_STOCK": 0.0,
                    "ARRIVAL_DATE": arrival,
                    "EXPIRATION_DATE": expiration,
                    "LOTS": 0,
                }
            item = consolidated[key]
            item["STOCK_AVAILABLE"] += stock
            item["VALUE_STOCK"] += value
            item["ARRIVAL_DATE"] = min(item["ARRIVAL_DATE"], arrival)
            item["EXPIRATION_DATE"] = min(item["EXPIRATION_DATE"], expiration)
            item["LOTS"] += 1
        return list(consolidated.values())
    finally:
        workbook.close()


def _priority_key(option: dict[str, Any]) -> tuple[Any, ...]:
    return (
        option["product_priority_rank"],
        0 if math.isfinite(option["current_doh"]) else 1,
        option["current_doh"],
        option["priority"],
        -option["share"],
        option["destination"],
    )


def _level_doh(
    total: int,
    options: list[dict[str, Any]],
    capacity_left: dict[int, int],
    target_doh: float,
) -> Counter[int]:
    """Reparte unidades una a una hacia el menor DOH hasta el objetivo seguro."""
    allocations: Counter[int] = Counter()
    remaining = int(total)
    while remaining > 0:
        eligible = [
            option
            for option in options
            if option["adu"] > 0
            and capacity_left[option["destination"]] > 0
            and (
                option["current_inventory"]
                + allocations[option["destination"]]
            )
            / option["adu"]
            < target_doh - 1e-9
        ]
        if not eligible:
            break
        selected = min(
            eligible,
            key=lambda option: (
                (
                    option["current_inventory"]
                    + allocations[option["destination"]]
                )
                / option["adu"],
                *_priority_key(option),
            ),
        )
        destination = selected["destination"]
        allocations[destination] += 1
        capacity_left[destination] -= 1
        remaining -= 1
    return allocations


def _share_distribution(
    total: int,
    options: list[dict[str, Any]],
    capacity_left: dict[int, int],
) -> Counter[int]:
    """Distribuye remanentes por share con enteros y reasignación de residuos."""
    allocations: Counter[int] = Counter()
    remaining = int(total)
    while remaining > 0:
        active = [
            option
            for option in options
            if capacity_left[option["destination"]] > 0
        ]
        if not active:
            break
        total_weight = sum(max(option["share"], 0.0) for option in active)
        if total_weight <= 0:
            weights = {option["destination"]: 1.0 for option in active}
            total_weight = float(len(active))
        else:
            weights = {
                option["destination"]: max(option["share"], 0.0)
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
        if remaining <= 0:
            break
        ranked = sorted(
            active,
            key=lambda option: (
                -(raw.get(option["destination"], 0.0) % 1),
                *_priority_key(option),
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
    return allocations


def apply_shalashaska_engine(
    result,
    catalogs,
    config: engine.Config,
    expiring_rows: list[dict[str, Any]],
    catalog_adu: dict[tuple[int, int], float],
    closed_store_ids: set[int],
    blocked_cities: tuple[str, ...],
    store_shares: dict[int, float],
    *,
    run_date: date,
    target_doh: float,
    reason_column: str = "PLANNING_REASON",
) -> dict[str, Any]:
    """Evacua inventario próximo a caducar sin rebasar restricciones globales."""
    summary = empty_shalashaska_summary(True)
    summary["tasks_before"] = result.tasks_used
    if target_doh <= 0:
        raise ValueError("Shalashaska: el DOH objetivo debe ser mayor a cero.")

    blocked_city_set = set(blocked_cities)

    consumed_stock: Counter[tuple[int, int]] = Counter()
    planned_incoming: Counter[tuple[int, int]] = Counter()
    natural_destinations_by_source: dict[int, set[int]] = {
        source: set() for source in config.origin_warehouses
    }
    for allocation in result.allocation_rows:
        consumed_stock[
            (int(allocation["WAREHOUSE_SOURCE"]), int(allocation["RETAIL_ID"]))
        ] += int(allocation["QUANTITY"])
        planned_incoming[
            (int(allocation["WAREHOUSE_DESTINATION"]), int(allocation["RETAIL_ID"]))
        ] += int(allocation["QUANTITY"])
        source = int(allocation["WAREHOUSE_SOURCE"])
        destination = int(allocation["WAREHOUSE_DESTINATION"])
        if (
            source in natural_destinations_by_source
            and destination not in closed_store_ids
            and catalogs.stores.get(destination, {}).get("city_norm", "")
            not in blocked_city_set
        ):
            natural_destinations_by_source[source].add(destination)

    candidates: list[dict[str, Any]] = []
    for row in expiring_rows:
        source = int(row["WAREHOUSE_SOURCE"])
        sku = int(row["RETAIL_ID"])
        risk_units = int(row["STOCK_AVAILABLE"])
        summary["units_reported"] += risk_units
        if source not in config.origin_warehouses:
            summary["skipped_origin_not_selected"] += 1
            continue
        if sku in catalogs.excluded_products:
            summary["skipped_excluded_sku"] += 1
            continue
        summary["units_at_risk"] += risk_units
        summary["value_at_risk"] += float(row["VALUE_STOCK"])
        stock_info = engine.source_stock_components(catalogs, source, sku)
        remaining_stock = max(
            int(stock_info["adjusted"]) - consumed_stock[(source, sku)], 0
        )
        eligible_units = min(risk_units, remaining_stock)
        summary["units_capped_by_stock"] += max(risk_units - eligible_units, 0)
        if eligible_units <= 0:
            continue
        candidate = dict(row)
        priority_rank = 4
        for destination in natural_destinations_by_source.get(source, set()):
            store = catalogs.stores.get(destination)
            if not store:
                continue
            city_norm = store.get("city_norm", "")
            priority_profile = engine.product_priority_profile(
                catalogs,
                destination,
                sku,
            )
            is_golden = priority_profile["is_golden"]
            if engine.is_regional_block(
                catalogs, source, destination, sku, city_norm, is_golden
            ):
                continue
            priority_rank = min(priority_rank, priority_profile["rank"])
        candidate.update(
            {
                "ELIGIBLE_UNITS": eligible_units,
                "STOCK_INFO": stock_info,
                "STOCK_REMAINING": remaining_stock,
                "PRIORITY_RANK": priority_rank,
            }
        )
        candidates.append(candidate)

    candidates.sort(
        key=lambda row: (
            row["PRIORITY_RANK"],
            row["EXPIRATION_DATE"],
            -float(row["VALUE_STOCK"]),
            row["ARRIVAL_DATE"],
            config.origin_warehouses.index(row["WAREHOUSE_SOURCE"]),
            row["RETAIL_ID"],
        )
    )
    summary["candidate_origin_skus"] = len(candidates)
    summary["units_eligible_after_stock"] = sum(
        row["ELIGIBLE_UNITS"] for row in candidates
    )

    capacity_by_store = {
        row["WAREHOUSE_DESTINATION"]: row for row in result.capacity_rows
    }
    existing_allocations = {
        (
            int(row["WAREHOUSE_SOURCE"]),
            int(row["WAREHOUSE_DESTINATION"]),
            int(row["RETAIL_ID"]),
        ): row
        for row in result.allocation_rows
    }
    stores_sent: set[int] = set()
    products_sent: set[int] = set()
    next_order = len(result.base_rows) + 1

    for candidate in candidates:
        source = candidate["WAREHOUSE_SOURCE"]
        sku = candidate["RETAIL_ID"]
        available = int(candidate["ELIGIBLE_UNITS"])
        if available <= 0:
            continue
        m3_per_unit = catalogs.volume_m3.get(sku, config.default_m3_per_unit)
        options: list[dict[str, Any]] = []
        for destination in natural_destinations_by_source.get(source, set()):
            if destination == source:
                continue
            store = catalogs.stores.get(destination)
            if not store or (destination, sku) in catalogs.route_cost_blocks:
                continue
            city_norm = store.get("city_norm", "")
            priority_profile = engine.product_priority_profile(
                catalogs,
                destination,
                sku,
            )
            is_golden = priority_profile["is_golden"]
            is_kvi = priority_profile["is_kvi"]
            if engine.is_regional_block(
                catalogs, source, destination, sku, city_norm, is_golden
            ):
                summary["skipped_regional_block"] += 1
                continue

            capacity = catalogs.store_capacity.get(
                destination, config.default_store_capacity_m3
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
                else available
            )
            if capacity_units <= 0:
                continue

            adu = max(float(catalog_adu.get((destination, sku), 0.0)), 0.0)
            if adu <= 0:
                summary["skipped_no_adu"] += 1
                continue
            current_inventory = max(
                float(catalogs.stock_base.get((destination, sku), 0.0)), 0.0
            ) + planned_incoming[(destination, sku)]
            current_doh = current_inventory / adu if adu > 0 else math.inf
            allocation_key = (source, destination, sku)
            options.append(
                {
                    "destination": destination,
                    "store": store,
                    "is_golden": is_golden,
                    "is_infaltable": priority_profile["is_infaltable"],
                    "is_anchor": priority_profile["is_anchor"],
                    "is_kvi": is_kvi,
                    "product_priority_type": priority_profile["type"],
                    "product_priority_rank": priority_profile["rank"],
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
        options.sort(key=_priority_key)
        existing_options = [option for option in options if option["existing_task"]]
        new_options = [option for option in options if not option["existing_task"]]
        task_slots = max(config.max_tasks - result.tasks_used, 0)
        selected_options = existing_options + new_options[:task_slots]
        if not selected_options:
            summary["skipped_task_limit"] += 1
            continue

        option_count = len(selected_options)
        capacity_left = {
            option["destination"]: int(option["capacity_units"])
            for option in selected_options
        }
        days_to_expiry = max((candidate["EXPIRATION_DATE"] - run_date).days, 1)
        safe_target_doh = min(target_doh, max(days_to_expiry - 1, 1))
        demand_allocations = _level_doh(
            available, selected_options, capacity_left, safe_target_doh
        )
        assigned_by_demand = sum(demand_allocations.values())

        # No se descarga todo en una sola tienda sin soporte de forecast.
        if option_count >= 2:
            share_allocations = _share_distribution(
                available - assigned_by_demand, selected_options, capacity_left
            )
        else:
            share_allocations = Counter()
        planned = Counter(demand_allocations)
        planned.update(share_allocations)
        planned = Counter(
            {destination: quantity for destination, quantity in planned.items() if quantity > 0}
        )
        if not planned:
            summary["skipped_no_capacity"] += 1
            continue

        option_by_destination = {
            option["destination"]: option for option in selected_options
        }
        assigned_total = 0
        candidate_tasks = 0
        for destination, quantity in planned.items():
            option = option_by_destination[destination]
            allocation_key = (source, destination, sku)
            allocation = existing_allocations.get(allocation_key)
            if allocation is None:
                if result.tasks_used >= config.max_tasks:
                    break
                allocation = {
                    "WAREHOUSE_DESTINATION": destination,
                    "WAREHOUSE_SOURCE": source,
                    "RETAIL_ID": sku,
                    "QUANTITY": int(quantity),
                    "PLANNED_DATE": "",
                    "ROUTE": 1,
                    "DELIVERY_PRIORITY": 1,
                    "CITY": option["store"].get("city", ""),
                    "STORAGE": engine.source_storage_type(catalogs, source, sku),
                    "VALUE": engine.source_value_category(catalogs, source, sku),
                    reason_column: SHALASHASKA_REASON,
                }
                result.allocation_rows.append(allocation)
                existing_allocations[allocation_key] = allocation
                result.tasks_used += 1
                candidate_tasks += 1
                is_new_task = True
            else:
                allocation["QUANTITY"] = int(allocation["QUANTITY"]) + int(quantity)
                previous_reason = engine.clean_text(allocation.get(reason_column))
                if SHALASHASKA_REASON not in previous_reason:
                    allocation[reason_column] = (
                        f"{previous_reason} + {SHALASHASKA_REASON}"
                        if previous_reason
                        else SHALASHASKA_REASON
                    )
                is_new_task = False

            quantity = int(quantity)
            assigned_total += quantity
            planned_incoming[(destination, sku)] += quantity
            assigned_m3 = quantity * m3_per_unit
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

            stock_info = candidate["STOCK_INFO"]
            stock_after = candidate["STOCK_REMAINING"] - assigned_total
            base_row = {
                "ORDEN_PLANIFICACION": next_order,
                "FILA_INPUT": "POR_MERMAR",
                "FILAS_INPUT_CONSOLIDADAS": "POR_MERMAR",
                "CANTIDAD_FILAS_INPUT": 0,
                "DUPLICADO_CONFLICTIVO": False,
                "WAREHOUSE_DESTINATION": destination,
                "WAREHOUSE_NAME": option["store"].get("warehouse_name", ""),
                "CITY": option["store"].get("city", ""),
                "RETAIL_ID": sku,
                "SKU_NAME": "",
                "PREDICTED_OPENING_INVENTORY": option["current_inventory"],
                "PREDICTED_DEMAND": 0,
                "ADU_CATALOGO": option["adu"],
                "CURRENT_INVENTORY": option["current_inventory"],
                "MOV_ORIGINAL": 0,
                "REGLA_DEMANDA": "SHALASHASKA_ENGINE",
                "CANTIDAD_OBJETIVO": quantity,
                "CANTIDAD_ASIGNADA": quantity,
                "CANTIDAD_FALTANTE": 0,
                "ES_INFALTABLE": option["is_infaltable"],
                "ES_GOLDEN": option["is_golden"],
                "ES_ANCHOR": option["is_anchor"],
                "TIPO_PRIORIDAD_PRODUCTO": option["product_priority_type"],
                "RANGO_PRIORIDAD_PRODUCTO": option["product_priority_rank"],
                "ES_GOLDEN_INFALTABLE": (
                    option["is_infaltable"] or option["is_golden"]
                ),
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
                "ORIGENES_USADOS": f"{source}:{quantity}",
                "STORAGE": engine.source_storage_type(catalogs, source, sku),
                "VALUE": engine.source_value_category(catalogs, source, sku),
                "TIPO_DE_CORTE": SHALASHASKA_CUT,
                "DETALLE_MOTIVO": (
                    "Inventario próximo a caducar distribuido por necesidad, DOH "
                    "y share de ventas entre rutas que ya salían desde el origen."
                ),
                "POR_MERMAR_ORIGEN": int(candidate["STOCK_AVAILABLE"]),
                "VALOR_POR_MERMAR": float(candidate["VALUE_STOCK"]),
                "FECHA_LLEGADA": candidate["ARRIVAL_DATE"].isoformat(),
                "FECHA_CADUCIDAD": candidate["EXPIRATION_DATE"].isoformat(),
                "DOH_OBJETIVO_EVACUACION": safe_target_doh,
            }
            for configured_source in config.origin_warehouses:
                configured_info = (
                    stock_info
                    if configured_source == source
                    else engine.source_stock_components(catalogs, configured_source, sku)
                )
                configured_remaining = max(
                    int(configured_info["adjusted"])
                    - consumed_stock[(configured_source, sku)]
                    - (assigned_total if configured_source == source else 0),
                    0,
                )
                base_row.update(
                    {
                        f"STOCK_BASE_{configured_source}": configured_info["base"],
                        f"NO_DISPONIBLE_{configured_source}": configured_info["unavailable"],
                        f"COPERNICO_NO_USABLE_{configured_source}": configured_info["copernico_unusable"],
                        f"RACKEADO_{configured_source}": configured_info["rackeado"],
                        f"STOCK_INICIAL_AJUSTADO_{configured_source}": configured_info["adjusted"],
                        f"STOCK_ANTES_{configured_source}": configured_remaining
                        + (quantity if configured_source == source else 0),
                        f"BLOQUEO_REGIONAL_{configured_source}": False,
                        f"ASIGNADO_{configured_source}": quantity
                        if configured_source == source
                        else 0,
                        f"STOCK_REMANENTE_{configured_source}": configured_remaining,
                    }
                )
            result.base_rows.append(base_row)
            next_order += 1
            stores_sent.add(destination)

        if assigned_total > 0:
            consumed_stock[(source, sku)] += assigned_total
            summary["origin_skus_sent"] += 1
            summary["origin_skus_fully_evacuated"] += int(assigned_total >= available)
            summary["tasks_added"] += candidate_tasks
            summary["units_evacuated"] += assigned_total
            summary["m3_added"] += assigned_total * m3_per_unit
            protected_ratio = assigned_total / max(int(candidate["STOCK_AVAILABLE"]), 1)
            summary["value_protected"] += min(
                float(candidate["VALUE_STOCK"]) * protected_ratio,
                float(candidate["VALUE_STOCK"]),
            )
            products_sent.add(sku)

    result.capacity_rows.sort(key=lambda row: row["WAREHOUSE_DESTINATION"])
    summary["tasks_after"] = result.tasks_used
    summary["units_not_evacuated"] = max(
        summary["units_at_risk"] - summary["units_evacuated"], 0
    )
    summary["m3_added"] = round(summary["m3_added"], 3)
    summary["value_at_risk"] = round(summary["value_at_risk"], 2)
    summary["value_protected"] = round(summary["value_protected"], 2)
    summary["stores"] = len(stores_sent)
    summary["products"] = len(products_sent)
    return summary
