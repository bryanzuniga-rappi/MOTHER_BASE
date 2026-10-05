"""Venom Engine — llenado DDMRP posterior a toda la planeación.

Posición: después de Liquid; antes de Kazuhira y de la partición por OWNER.
Entrada: stock remanente, lo ya asignado en la corrida y CATALOGO (ADU, LIST_TYPE).
Salida: filas NUEVAS en allocation_rows y base_rows; nunca consolida con
líneas existentes del mismo origen-destino-SKU (el reporte separa lo de Venom).

Modelo DDMRP simplificado, por tienda-SKU elegible:
    Red Zone      = ADU x LT x LTF x (1 + VF)
    Yellow Zone   = ADU x LT
    Green Zone    = max(ADU x LT x LTF, mínimo operativo)
    Top of Yellow = Red Zone + Yellow Zone
    Top of Green  = Top of Yellow + Green Zone
    NFP           = On-Hand + On-Order - ADU x LT
Si NFP < Top of Yellow se ordena ceil(Top of Green - NFP). LTF = VF = 0.5
(perfil medio; LTF_MEDIUM / VF_MEDIUM). On-Order = lo ya asignado en la corrida
si "considerar planeación actual" está activo; si no, 0.

Sin CAP_RECIBO: respeta stock por origen y MAX_TASKS, pero no usa ni cierra la
capacidad de tienda (es un "ontop manual").
OOWL: tienda-SKU sin ADU, con stock en origen y cero stock/incoming en destino.
Bloqueado a nivel motor: no se envía mínimo operativo sin pronóstico.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
import math

import modelo_abasto as engine


VENOM_REASON = "ENVIADO POR VENOM ENGINE"
VENOM_CUT = "ENVIADOS POR VENOM ENGINE"

# Perfil medio estándar de DDMRP: ni corto/largo lead time, ni baja/alta
# variabilidad.
LTF_MEDIUM = 0.5
VF_MEDIUM = 0.5

SECTION_TYPES = ("IS_INFALTABLE", "IS_GOLDEN", "IS_ANCHOR", "IS_KVI", "BL", "OOWL")

# Techo de la zona que dispara el reorden (estándar DDMRP: amarillo).
TRIGGER_ZONES = ("yellow", "red", "green")


def empty_venom_summary(enabled: bool) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "tasks_before": 0,
        "tasks_added": 0,
        "tasks_after": 0,
        "lead_time_days": 0.0,
        "consider_current_planning": True,
        "section_types": [],
        "candidates_ddmrp": 0,
        "candidates_oowl": 0,
        "lines_sent_ddmrp": 0,
        "lines_sent_oowl": 0,
        "units_sent_ddmrp": 0,
        "units_sent_oowl": 0,
        "units_sent": 0,
        "m3_added": 0.0,
        "stores": 0,
        "products": 0,
        "skipped_no_adu": 0,
        "skipped_buffer_healthy": 0,
        "skipped_no_stock": 0,
        "skipped_no_capacity": 0,
        "skipped_task_limit": 0,
        "skipped_regional_block": 0,
        "skipped_schedule_block": 0,
        "skipped_closed_store": 0,
        "skipped_blocked_city": 0,
        "skipped_route_cost": 0,
        "skipped_excluded_sku": 0,
        "skipped_capacity_cap": 0,
        "units_cut_by_capacity": 0,
        "manual_pairs": 0,
        "ltf": LTF_MEDIUM,
        "vf": VF_MEDIUM,
        "order_cycle_days": 0.0,
        "trigger_zone": "yellow",
        "subtract_lead_time_demand": True,
        "consider_incoming": False,
        "shipping_multiple": 1,
        "cap_to_store_capacity": False,
        "only_manual_skus": False,
    }


def compute_ddmrp_zones(
    adu: float,
    lead_time_days: float,
    ltf: float = LTF_MEDIUM,
    vf: float = VF_MEDIUM,
    minimum_green_units: float = 3.0,
    order_cycle_days: float = 0.0,
) -> dict[str, float]:
    """Calcula las zonas roja/amarilla/verde de un buffer DDMRP.

    Verde = máx(ADU × LT × LTF, mínimo de orden, ADU × ciclo de pedido)."""
    adu = max(float(adu), 0.0)
    lead_time_days = max(float(lead_time_days), 0.0)
    red_base = adu * lead_time_days * ltf
    red_safety = red_base * vf
    red_zone = red_base + red_safety
    yellow_zone = adu * lead_time_days
    green_zone = max(
        adu * lead_time_days * ltf,
        minimum_green_units,
        adu * max(float(order_cycle_days), 0.0),
    )
    top_of_red = red_zone
    top_of_yellow = red_zone + yellow_zone
    top_of_green = top_of_yellow + green_zone
    return {
        "adu": adu,
        "lead_time_days": lead_time_days,
        "ltf": ltf,
        "vf": vf,
        "order_cycle_days": float(order_cycle_days),
        "red_base": red_base,
        "red_safety": red_safety,
        "red_zone": red_zone,
        "yellow_zone": yellow_zone,
        "green_zone": green_zone,
        "top_of_red": top_of_red,
        "top_of_yellow": top_of_yellow,
        "top_of_green": top_of_green,
    }


def _destination_block_reason(
    catalogs: engine.Catalogs,
    destination: int,
    sku: int,
    closed_or_excluded_store_ids: set[int],
    blocked_city_set: set[str],
) -> str | None:
    if destination in closed_or_excluded_store_ids:
        return "closed_store"
    store = catalogs.stores.get(destination)
    if not store:
        return "closed_store"
    if store.get("city_norm", "") in blocked_city_set:
        return "blocked_city"
    if (destination, sku) in catalogs.route_cost_blocks:
        return "route_cost"
    return None


def _allocate_across_origins(
    catalogs: engine.Catalogs,
    config: engine.Config,
    result,
    *,
    source_candidates: tuple[int, ...],
    destination: int,
    sku: int,
    quantity_needed: int,
    consumed_by_origin_sku: Counter,
    summary: dict[str, Any],
) -> list[tuple[int, int]]:
    """Reparte ``quantity_needed`` entre ``source_candidates`` en orden."""
    remaining = quantity_needed
    picks: list[tuple[int, int]] = []
    tentative_tasks_used = result.tasks_used
    for source in source_candidates:
        if remaining <= 0:
            break
        if tentative_tasks_used >= config.max_tasks:
            summary["skipped_task_limit"] += 1
            break
        stock_info = engine.source_stock_components(catalogs, source, sku)
        already_consumed = consumed_by_origin_sku[(source, sku)]
        available = max(int(stock_info["adjusted"]) - already_consumed, 0)
        if available <= 0:
            continue
        take = min(available, remaining)
        if take <= 0:
            continue
        picks.append((source, take))
        consumed_by_origin_sku[(source, sku)] += take
        remaining -= take
        tentative_tasks_used += 1

    if not picks:
        summary["skipped_no_stock"] += 1
    return picks


def _new_base_row_template(
    *,
    order: int,
    destination: int,
    sku: int,
    store: dict[str, Any],
    catalogs: engine.Catalogs,
    config: engine.Config,
) -> dict[str, Any]:
    base_row: dict[str, Any] = {
        "ORDEN_PLANIFICACION": order,
        "FILA_INPUT": "VENOM",
        "FILAS_INPUT_CONSOLIDADAS": "VENOM",
        "CANTIDAD_FILAS_INPUT": 0,
        "DUPLICADO_CONFLICTIVO": False,
        "WAREHOUSE_DESTINATION": destination,
        "WAREHOUSE_NAME": store.get("warehouse_name", ""),
        "CITY": store.get("city", ""),
        "RETAIL_ID": sku,
        "SKU_NAME": "",
        "MOV_ORIGINAL": 0,
        "TIPO_DE_CORTE": VENOM_CUT,
    }
    for source in config.origin_warehouses:
        info = engine.source_stock_components(catalogs, source, sku)
        base_row.update(
            {
                f"STOCK_BASE_{source}": info["base"],
                f"NO_DISPONIBLE_{source}": info["unavailable"],
                f"COPERNICO_NO_USABLE_{source}": info["copernico_unusable"],
                f"RACKEADO_{source}": info["rackeado"],
                f"STOCK_INICIAL_AJUSTADO_{source}": info["adjusted"],
                f"BLOQUEO_REGIONAL_{source}": False,
                f"BLOQUEO_FRECUENCIA_{source}": False,
                f"VALUE_{source}": engine.source_value_category(
                    catalogs, source, sku
                ),
                f"STORAGE_{source}": engine.source_storage_type(
                    catalogs, source, sku
                ),
                f"ASIGNADO_{source}": 0,
            }
        )
    return base_row


def apply_venom_engine(
    result,
    catalogs: engine.Catalogs,
    config: engine.Config,
    *,
    venom_origins: tuple[int, ...],
    venom_destinations: tuple[int, ...],
    section_types: set[str],
    lead_time_days: float,
    consider_current_planning: bool,
    catalog_lookup: dict[tuple[int, int], dict[str, Any]],
    closed_or_excluded_store_ids: set[int],
    blocked_cities: tuple[str, ...],
    reason_column: str = "PLANNING_REASON",
    ltf: float = LTF_MEDIUM,
    vf: float = VF_MEDIUM,
    min_green_units: float | None = None,
    order_cycle_days: float = 0.0,
    trigger_zone: str = "yellow",
    subtract_lead_time_demand: bool = True,
    consider_incoming: bool = False,
    shipping_multiple: int = 1,
    cap_to_store_capacity: bool = False,
    manual_skus_by_origin: dict[int, set[int]] | None = None,
    only_manual_skus: bool = False,
) -> dict[str, Any]:
    """Corre el llenado DDMRP de Venom al final de toda la planeación.

    ltf/vf: factores de lead time y de variabilidad. min_green_units: mínimo de
    orden (None = mínimo de unidades de CODEC). order_cycle_days: ciclo de pedido
    para la zona verde. trigger_zone: techo que dispara el reorden (yellow,
    red o green; se ordena hasta el techo verde). subtract_lead_time_demand:
    resta ADU × LT en el NFP (apagado: NFP = on-hand + on-order).
    consider_incoming: suma STOCK.INCOMING_TR al on-order. shipping_multiple:
    redondea hacia arriba la cantidad a un múltiplo. cap_to_store_capacity: tope
    de m³ propio de Venom (capacidad completa de la tienda, aparte de lo que ya
    usaron los demás engines, que no se ve afectado). manual_skus_by_origin: SKUs
    concretos que se evalúan con DDMRP desde ese origen, sin importar el tipo de
    sección; only_manual_skus limita el universo a ellos.
    """
    # OOWL bloqueado a nivel motor: no se envía mínimo operativo sin
    # pronóstico, sin importar section_types.
    section_types = set(section_types) - {"OOWL"}

    summary = empty_venom_summary(True)
    summary["tasks_before"] = result.tasks_used
    summary["lead_time_days"] = float(lead_time_days)
    summary["consider_current_planning"] = bool(consider_current_planning)
    summary["section_types"] = sorted(section_types)

    if lead_time_days <= 0:
        raise ValueError("Venom Engine: el lead time debe ser mayor a cero.")
    if not 0 < ltf <= 1:
        raise ValueError("Venom Engine: el factor de lead time (LTF) debe estar en (0, 1].")
    if not 0 <= vf <= 1:
        raise ValueError("Venom Engine: el factor de variabilidad (VF) debe estar en [0, 1].")
    if order_cycle_days < 0:
        raise ValueError("Venom Engine: el ciclo de pedido no puede ser negativo.")
    if trigger_zone not in TRIGGER_ZONES:
        raise ValueError(f"Venom Engine: disparador inválido ({trigger_zone}).")
    if shipping_multiple < 1:
        raise ValueError("Venom Engine: el múltiplo de envío debe ser al menos 1.")
    green_minimum = (
        float(min_green_units)
        if min_green_units is not None
        else float(config.minimum_positive_quantity)
    )
    summary.update(
        ltf=float(ltf), vf=float(vf), order_cycle_days=float(order_cycle_days),
        trigger_zone=trigger_zone, subtract_lead_time_demand=bool(subtract_lead_time_demand),
        consider_incoming=bool(consider_incoming), shipping_multiple=int(shipping_multiple),
        cap_to_store_capacity=bool(cap_to_store_capacity), only_manual_skus=bool(only_manual_skus),
    )
    if not venom_origins:
        raise ValueError("Venom Engine: selecciona al menos un warehouse origen.")
    if not venom_destinations:
        raise ValueError("Venom Engine: selecciona al menos una tienda destino.")

    blocked_city_set = set(blocked_cities)
    destinations = set(venom_destinations)

    # On-order de esta corrida: lo que ya asignaron Naked/Solidus/AVL/
    # Preventivo/Shalashaska/Liquid/Insumos, antes de que Venom toque nada.
    on_order_by_destination_sku: Counter[tuple[int, int]] = Counter()
    consumed_by_origin_sku: Counter[tuple[int, int]] = Counter()
    for row in result.allocation_rows:
        quantity = int(row["QUANTITY"])
        on_order_by_destination_sku[
            (int(row["WAREHOUSE_DESTINATION"]), int(row["RETAIL_ID"]))
        ] += quantity
        consumed_by_origin_sku[
            (int(row["WAREHOUSE_SOURCE"]), int(row["RETAIL_ID"]))
        ] += quantity

    capacity_by_store = {
        row["WAREHOUSE_DESTINATION"]: row for row in result.capacity_rows
    }
    # Capacidad propia de Venom: arranca en cero por tienda y NO se suma a lo
    # que ya usaron los demás engines (ni se les resta a ellos después).
    venom_cap_used: Counter[int] = Counter()

    # SKUs concretos por origen: solo cuentan los orígenes que Venom usa.
    manual_origins_by_sku: dict[int, tuple[int, ...]] = {}
    for source in venom_origins:
        for manual_sku in (manual_skus_by_origin or {}).get(source, set()):
            manual_origins_by_sku[manual_sku] = (
                *manual_origins_by_sku.get(manual_sku, ()), source,
            )

    # --- 1) Universo de candidatos DDMRP (Infaltable/Golden/Anchor/KVI/BL) --
    dd_pairs: set[tuple[int, int]] = set()
    if only_manual_skus:
        section_types = set()
    if "IS_KVI" in section_types:
        dd_pairs |= {
            pair for pair in catalogs.kvi_products if pair[0] in destinations
        }
    if "IS_INFALTABLE" in section_types:
        dd_pairs |= {
            pair for pair in catalogs.infaltable_products if pair[0] in destinations
        }
    if "IS_GOLDEN" in section_types:
        dd_pairs |= {
            pair for pair in catalogs.golden_products if pair[0] in destinations
        }
    if "IS_ANCHOR" in section_types:
        dd_pairs |= {
            pair for pair in catalogs.anchor_products if pair[0] in destinations
        }
    if "BL" in section_types:
        dd_pairs |= {
            key
            for key, info in catalog_lookup.items()
            if key[0] in destinations
            and engine.clean_text(info.get("list_type")).upper() == "BL"
        }

    manual_pairs = {
        (destination, manual_sku)
        for manual_sku in manual_origins_by_sku
        for destination in destinations
    }
    summary["manual_pairs"] = len(manual_pairs)
    dd_pairs |= manual_pairs

    handled_pairs: set[tuple[int, int]] = set()
    no_adu_pairs: set[tuple[int, int]] = set()

    def _priority_sort_key(pair: tuple[int, int]) -> tuple[int, int, int]:
        destination, sku = pair
        profile = engine.product_priority_profile(catalogs, destination, sku)
        return (
            profile["rank"],
            catalogs.store_priority.get(destination, 100),
            sku,
        )

    next_order = len(result.base_rows) + 1

    for destination, sku in sorted(dd_pairs, key=_priority_sort_key):
        if sku in catalogs.excluded_products:
            summary["skipped_excluded_sku"] += 1
            continue
        adu = float(catalog_lookup.get((destination, sku), {}).get("adu", 0.0))
        if adu <= 0:
            no_adu_pairs.add((destination, sku))
            summary["skipped_no_adu"] += 1
            continue
        block_reason = _destination_block_reason(
            catalogs, destination, sku, closed_or_excluded_store_ids, blocked_city_set
        )
        if block_reason == "closed_store":
            summary["skipped_closed_store"] += 1
            continue
        if block_reason == "blocked_city":
            summary["skipped_blocked_city"] += 1
            continue
        if block_reason == "route_cost":
            summary["skipped_route_cost"] += 1
            continue

        store = catalogs.stores[destination]
        summary["candidates_ddmrp"] += 1
        zones = compute_ddmrp_zones(
            adu, lead_time_days, ltf=ltf, vf=vf,
            minimum_green_units=green_minimum, order_cycle_days=order_cycle_days,
        )
        on_hand = max(float(catalogs.stock_base.get((destination, sku), 0.0)), 0.0)
        on_order = (
            on_order_by_destination_sku[(destination, sku)]
            if consider_current_planning
            else 0
        )
        if consider_incoming:
            on_order += max(float(catalogs.incoming_stock.get((destination, sku), 0.0)), 0.0)
        qualified_demand = adu * lead_time_days if subtract_lead_time_demand else 0.0
        nfp = on_hand + on_order - qualified_demand
        trigger_level = zones[f"top_of_{trigger_zone}"]
        if nfp >= trigger_level:
            summary["skipped_buffer_healthy"] += 1
            continue
        quantity_needed = int(math.ceil(zones["top_of_green"] - nfp))
        if quantity_needed <= 0:
            summary["skipped_buffer_healthy"] += 1
            continue
        if shipping_multiple > 1:
            quantity_needed = int(math.ceil(quantity_needed / shipping_multiple) * shipping_multiple)

        # Origen preferido: el que ya tenga tarea abierta a esta tienda-SKU
        # queda primero (evita rutas nuevas cuando ya hay una activa), luego
        # el resto de venom_origins en el orden seleccionado.
        eligible_origins = [
            source
            for source in (manual_origins_by_sku.get(sku) or venom_origins)
            if not engine.is_regional_block(
                catalogs,
                source,
                destination,
                sku,
                store.get("city_norm", ""),
                engine.product_priority_profile(catalogs, destination, sku)[
                    "is_golden"
                ],
            )
            and not engine.is_schedule_blocked(catalogs, source, destination)
        ]
        blocked_origin_count = len(manual_origins_by_sku.get(sku) or venom_origins) - len(
            eligible_origins
        )
        if blocked_origin_count:
            summary["skipped_regional_block"] += blocked_origin_count

        if not eligible_origins:
            summary["skipped_regional_block"] += 1
            continue

        m3_per_unit = catalogs.volume_m3.get(sku, config.default_m3_per_unit)
        venom_cap_before = float(venom_cap_used[destination])
        quantity_to_send = quantity_needed
        capacity_capped = False
        if cap_to_store_capacity:
            venom_capacity = catalogs.store_capacity.get(
                destination, config.default_store_capacity_m3
            )
            remaining_m3 = max(venom_capacity - venom_cap_before, 0.0)
            cap_units = (
                int(math.floor(remaining_m3 / m3_per_unit + 1e-9))
                if m3_per_unit > 0
                else quantity_needed
            )
            if cap_units <= 0:
                summary["skipped_capacity_cap"] += 1
                summary["skipped_no_capacity"] += 1
                continue
            if cap_units < quantity_needed:
                summary["units_cut_by_capacity"] += quantity_needed - cap_units
                quantity_to_send = cap_units
                capacity_capped = True
        picks = _allocate_across_origins(
            catalogs,
            config,
            result,
            source_candidates=tuple(eligible_origins),
            destination=destination,
            sku=sku,
            quantity_needed=quantity_to_send,
            consumed_by_origin_sku=consumed_by_origin_sku,
            summary=summary,
        )
        if not picks:
            continue

        handled_pairs.add((destination, sku))
        assigned_total = sum(quantity for _, quantity in picks)
        tasks_before = result.tasks_used
        tasks_generated = len(picks)
        base_row = _new_base_row_template(
            order=next_order,
            destination=destination,
            sku=sku,
            store=store,
            catalogs=catalogs,
            config=config,
        )
        profile = engine.product_priority_profile(catalogs, destination, sku)
        origenes_usados = ", ".join(f"{source}:{qty}" for source, qty in picks)
        assigned_m3 = assigned_total * m3_per_unit
        venom_cap_used[destination] += assigned_m3
        # Venom no escribe en result.capacity_rows: no afecta el gasto real de
        # CAP_RECIBO que ven los demás engines (Kazuhira incluido). Con su tope
        # activo, las columnas de capacidad muestran el ledger propio de Venom.
        cap_row = capacity_by_store.get(destination)
        shared_cap_before = float(cap_row["M3_CONTABILIZADO_CAPACIDAD"]) if cap_row else 0.0
        cap_before = venom_cap_before if cap_to_store_capacity else shared_cap_before
        cap_after = float(venom_cap_used[destination]) if cap_to_store_capacity else shared_cap_before
        base_row.update(
            {
                "PREDICTED_OPENING_INVENTORY": on_hand,
                "PREDICTED_DEMAND": qualified_demand,
                "ADU_CATALOGO": adu,
                "CURRENT_INVENTORY": on_hand,
                "REGLA_DEMANDA": "VENOM_DDMRP",
                "CANTIDAD_OBJETIVO": quantity_needed,
                "CANTIDAD_ASIGNADA": assigned_total,
                "CANTIDAD_FALTANTE": max(quantity_needed - assigned_total, 0),
                "ES_INFALTABLE": profile["is_infaltable"],
                "ES_GOLDEN": profile["is_golden"],
                "ES_ANCHOR": profile["is_anchor"],
                "TIPO_PRIORIDAD_PRODUCTO": profile["type"],
                "RANGO_PRIORIDAD_PRODUCTO": profile["rank"],
                "ES_GOLDEN_INFALTABLE": profile["is_infaltable"] or profile["is_golden"],
                "ES_KVI": profile["is_kvi"],
                "PRIORIDAD_TIENDA": catalogs.store_priority.get(destination, 100),
                "ES_STOCKOUT": on_hand <= 0,
                "SIN_RUTA_COSTOS": False,
                "M3_POR_UNIDAD": m3_per_unit,
                "M3_OBJETIVO": quantity_needed * m3_per_unit,
                "M3_ASIGNADO": assigned_m3,
                "CAPACIDAD_TIENDA_M3": catalogs.store_capacity.get(
                    destination, config.default_store_capacity_m3
                ),
                "M3_CAPACIDAD_ANTES": cap_before,
                "M3_CAPACIDAD_DESPUES": cap_after,
                "EXCEDE_CAPACIDAD_EN_ESTA_LINEA": False,
                "PASA_CAPACIDAD": not capacity_capped,
                "TAREAS_ANTES": tasks_before,
                "TAREAS_GENERADAS": tasks_generated,
                "TAREAS_ACUMULADAS": tasks_before + tasks_generated,
                "PASA_TAREAS": True,
                "ORIGENES_USADOS": origenes_usados,
                "DETALLE_MOTIVO": (
                    "Venom DDMRP: ADU="
                    f"{adu:.4f}, Lead Time={lead_time_days:g}d, LTF={ltf:g}, "
                    f"VF={vf:g}, Top of Red={zones['top_of_red']:.2f}, "
                    f"Top of Yellow={zones['top_of_yellow']:.2f}, "
                    f"Top of Green={zones['top_of_green']:.2f}, NFP={nfp:.2f} "
                    f"(On-Hand={on_hand:.0f}, On-Order={on_order:.0f} "
                    f"{'considerado' if consider_current_planning else 'ignorado'}, "
                    f"Demanda calificada={qualified_demand:.2f}). "
                    f"Objetivo {quantity_needed}, asignado {assigned_total}. "
                    + (
                        "Tope de capacidad propio de Venom: usó "
                        f"{cap_after:.4f} m3 de {catalogs.store_capacity.get(destination, config.default_store_capacity_m3):.4f} "
                        "(no se suma a lo usado por los demás engines)."
                        if cap_to_store_capacity
                        else "Ontop manual: no cuenta contra CAP_RECIBO de la tienda."
                    )
                ),
            }
        )
        _append_allocations(
            result=result,
            picks=picks,
            destination=destination,
            sku=sku,
            store=store,
            catalogs=catalogs,
            reason_column=reason_column,
        )
        result.base_rows.append(base_row)
        next_order += 1

        summary["lines_sent_ddmrp"] += 1
        summary["units_sent_ddmrp"] += assigned_total
        summary["m3_added"] += assigned_m3

    # --- 2) OOWL: sin pronóstico, mínimo operativo -------------------------
    if "OOWL" in section_types:
        candidate_skus: set[int] = set()
        for source in venom_origins:
            candidate_skus |= {
                sku
                for (origin, sku), stock in catalogs.stock_base.items()
                if origin == source and stock > 0
            }
        for destination in sorted(destinations):
            store = catalogs.stores.get(destination)
            if not store:
                summary["skipped_closed_store"] += 1
                continue
            for sku in sorted(candidate_skus):
                pair = (destination, sku)
                if pair in handled_pairs:
                    continue
                if sku in catalogs.excluded_products:
                    summary["skipped_excluded_sku"] += 1
                    continue
                on_hand = max(
                    float(catalogs.stock_base.get((destination, sku), 0.0)), 0.0
                )
                on_order = (
                    on_order_by_destination_sku[(destination, sku)]
                    if consider_current_planning
                    else 0
                )
                if on_hand + on_order > 0:
                    continue  # sí tiene stock/incoming: no es caso OOWL.

                block_reason = _destination_block_reason(
                    catalogs,
                    destination,
                    sku,
                    closed_or_excluded_store_ids,
                    blocked_city_set,
                )
                if block_reason == "closed_store":
                    summary["skipped_closed_store"] += 1
                    continue
                if block_reason == "blocked_city":
                    summary["skipped_blocked_city"] += 1
                    continue
                if block_reason == "route_cost":
                    summary["skipped_route_cost"] += 1
                    continue

                summary["candidates_oowl"] += 1
                profile = engine.product_priority_profile(catalogs, destination, sku)
                eligible_origins = [
                    source
                    for source in venom_origins
                    if not engine.is_regional_block(
                        catalogs,
                        source,
                        destination,
                        sku,
                        store.get("city_norm", ""),
                        profile["is_golden"],
                    )
                    and not engine.is_schedule_blocked(catalogs, source, destination)
                ]
                if not eligible_origins:
                    summary["skipped_regional_block"] += 1
                    continue

                m3_per_unit = catalogs.volume_m3.get(sku, config.default_m3_per_unit)
                picks = _allocate_across_origins(
                    catalogs,
                    config,
                    result,
                    source_candidates=tuple(eligible_origins),
                    destination=destination,
                    sku=sku,
                    quantity_needed=config.minimum_positive_quantity,
                    consumed_by_origin_sku=consumed_by_origin_sku,
                    summary=summary,
                )
                if not picks:
                    continue

                handled_pairs.add(pair)
                assigned_total = sum(quantity for _, quantity in picks)
                tasks_before = result.tasks_used
                tasks_generated = len(picks)
                base_row = _new_base_row_template(
                    order=next_order,
                    destination=destination,
                    sku=sku,
                    store=store,
                    catalogs=catalogs,
                    config=config,
                )
                origenes_usados = ", ".join(
                    f"{source}:{qty}" for source, qty in picks
                )
                assigned_m3 = assigned_total * m3_per_unit
                # Informativo únicamente: Venom no escribe en
                # result.capacity_rows (ver _allocate_across_origins).
                cap_row = capacity_by_store.get(destination)
                cap_before = (
                    float(cap_row["M3_CONTABILIZADO_CAPACIDAD"]) if cap_row else 0.0
                )
                base_row.update(
                    {
                        "PREDICTED_OPENING_INVENTORY": on_hand,
                        "PREDICTED_DEMAND": 0,
                        "ADU_CATALOGO": 0,
                        "CURRENT_INVENTORY": on_hand,
                        "REGLA_DEMANDA": "VENOM_OOWL_MINIMO",
                        "CANTIDAD_OBJETIVO": config.minimum_positive_quantity,
                        "CANTIDAD_ASIGNADA": assigned_total,
                        "CANTIDAD_FALTANTE": max(
                            config.minimum_positive_quantity - assigned_total, 0
                        ),
                        "ES_INFALTABLE": profile["is_infaltable"],
                        "ES_GOLDEN": profile["is_golden"],
                        "ES_ANCHOR": profile["is_anchor"],
                        "TIPO_PRIORIDAD_PRODUCTO": profile["type"],
                        "RANGO_PRIORIDAD_PRODUCTO": profile["rank"],
                        "ES_GOLDEN_INFALTABLE": (
                            profile["is_infaltable"] or profile["is_golden"]
                        ),
                        "ES_KVI": profile["is_kvi"],
                        "PRIORIDAD_TIENDA": catalogs.store_priority.get(
                            destination, 100
                        ),
                        "ES_STOCKOUT": True,
                        "SIN_RUTA_COSTOS": False,
                        "M3_POR_UNIDAD": m3_per_unit,
                        "M3_OBJETIVO": config.minimum_positive_quantity * m3_per_unit,
                        "M3_ASIGNADO": assigned_m3,
                        "CAPACIDAD_TIENDA_M3": catalogs.store_capacity.get(
                            destination, config.default_store_capacity_m3
                        ),
                        "M3_CAPACIDAD_ANTES": cap_before,
                        "M3_CAPACIDAD_DESPUES": cap_before,
                        "EXCEDE_CAPACIDAD_EN_ESTA_LINEA": False,
                        "PASA_CAPACIDAD": True,
                        "TAREAS_ANTES": tasks_before,
                        "TAREAS_GENERADAS": tasks_generated,
                        "TAREAS_ACUMULADAS": tasks_before + tasks_generated,
                        "PASA_TAREAS": True,
                        "ORIGENES_USADOS": origenes_usados,
                        "DETALLE_MOTIVO": (
                            "Venom OOWL: hay stock en origen y cero stock/incoming "
                            "en destino, sin ADU en CATALOGO para construir un "
                            "buffer DDMRP. Se envía el mínimo operativo de "
                            f"{config.minimum_positive_quantity} unidades. "
                            f"Asignado {assigned_total}. Ontop manual: no cuenta "
                            "contra CAP_RECIBO de la tienda."
                        ),
                    }
                )
                _append_allocations(
                    result=result,
                    picks=picks,
                    destination=destination,
                    sku=sku,
                    store=store,
                    catalogs=catalogs,
                    reason_column=reason_column,
                )
                result.base_rows.append(base_row)
                next_order += 1

                summary["lines_sent_oowl"] += 1
                summary["units_sent_oowl"] += assigned_total
                summary["m3_added"] += assigned_m3

    summary["units_sent"] = summary["units_sent_ddmrp"] + summary["units_sent_oowl"]
    summary["tasks_after"] = result.tasks_used
    summary["tasks_added"] = summary["tasks_after"] - summary["tasks_before"]
    summary["stores"] = len(
        {
            row["WAREHOUSE_DESTINATION"]
            for row in result.base_rows
            if row.get("TIPO_DE_CORTE") == VENOM_CUT
        }
    )
    summary["products"] = len(
        {
            row["RETAIL_ID"]
            for row in result.base_rows
            if row.get("TIPO_DE_CORTE") == VENOM_CUT
        }
    )
    return summary


def _append_allocations(
    *,
    result,
    picks: list[tuple[int, int]],
    destination: int,
    sku: int,
    store: dict[str, Any],
    catalogs: engine.Catalogs,
    reason_column: str,
) -> None:
    """Agrega una fila NUEVA de allocation por cada origen usado."""
    for source, quantity in picks:
        result.allocation_rows.append(
            {
                "WAREHOUSE_DESTINATION": destination,
                "WAREHOUSE_SOURCE": source,
                "RETAIL_ID": sku,
                "QUANTITY": int(quantity),
                "PLANNED_DATE": "",
                "ROUTE": 1,
                "DELIVERY_PRIORITY": 1,
                "CITY": store.get("city", ""),
                "STORAGE": engine.source_storage_type(catalogs, source, sku),
                "VALUE": engine.source_value_category(catalogs, source, sku),
                reason_column: VENOM_REASON,
            }
        )
        result.tasks_used += 1
