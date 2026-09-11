"""Venom Engine — llenado DDMRP posterior a toda la planeación.

Venom se ejecuta al final de la secuencia (después de Naked, Solidus, AVL,
Preventivo, Shalashaska, Liquid e Insumos, y antes de la partición por
OWNER). Toma los remanentes de stock post-allocation y lo ya incoming de
esta misma corrida, y aplica un modelo DDMRP (Demand Driven MRP) simplificado
para decidir si hace falta un envío adicional de "llenado de buffer".

A diferencia de Liquid/Shalashaska, Venom **nunca consolida** con líneas ya
existentes del mismo trío origen-destino-SKU: siempre agrega una fila nueva a
``allocation_rows`` y a ``base_rows``, aunque el trío ya tuviera cantidad
asignada por otro engine. Esto es intencional: el reporte debe mostrar por
separado cuánto mandó la planeación original y cuánto Venom encima de eso.

## Modelo DDMRP simplificado

Para cada combinación tienda-SKU elegible (según TIPO DE SECCIÓN):

    ADU          = CATALOGO.ADU de esa tienda-SKU
    Red Base     = ADU x Lead Time x LTF
    Red Safety   = Red Base x VF
    Red Zone     = Red Base + Red Safety
    Yellow Zone  = ADU x Lead Time
    Green Zone   = max(ADU x Lead Time x LTF, mínimo operativo)
    Top of Red   = Red Zone
    Top of Yellow= Red Zone + Yellow Zone
    Top of Green = Top of Yellow + Green Zone

    On-Hand      = STOCK_DISPONIBLE_FINAL remanente en la tienda destino
    On-Order     = unidades ya asignadas a esa tienda-SKU en esta misma
                   corrida (Naked+Solidus+AVL+Preventivo+Shalashaska+Liquid+
                   Insumos), solo si "considerar planeación actual" está
                   activo; si no, On-Order = 0.
    Demanda Calif.= ADU x Lead Time
    NFP          = On-Hand + On-Order - Demanda Calificada

Si NFP >= Top of Yellow, el buffer está sano y no se genera envío. Si NFP <
Top of Yellow, Venom ordena hasta el techo de la zona verde:

    Cantidad = ceil(Top of Green - NFP)

LTF (Factor de Lead Time) y VF (Factor de Variabilidad) usan el perfil medio
estándar de DDMRP (0.5 cada uno) — ver ``LTF_MEDIUM``/``VF_MEDIUM``.

## Ontop manual: sin restricción de CAP_RECIBO

Venom es, en la práctica, un "ontop manual" sobre la planeación normal: sí
respeta el stock remanente por origen y el presupuesto compartido de tareas
(``MAX_TASKS``), pero **no** se limita por la capacidad de recibo de la
tienda (``CAP_RECIBO``). Sus unidades nunca se descuentan de
``result.capacity_rows`` ni cuentan para "capacidad cerrada"; los campos
informativos ``M3_CAPACIDAD_ANTES``/``M3_CAPACIDAD_DESPUES`` del reporte
reflejan lo que otros engines ya usaron, no lo que Venom decide agregar.

## OOWL — sin pronóstico

"OOWL" no es una clasificación estática: son combinaciones tienda-SKU con
stock disponible en alguno de los orígenes de Venom, CERO stock/incoming en
la tienda destino, y sin ADU en CATALOGO (por lo que no se puede construir un
buffer DDMRP real). En ese caso Venom no calcula zonas: manda directamente
``config.minimum_positive_quantity`` unidades (el mismo mínimo operativo de
3 que usa el resto del proyecto), sujeto a stock, capacidad y tareas.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
import math

import modelo_abasto as engine


VENOM_REASON = "ENVIADO POR VENOM ENGINE"
VENOM_CUT = "ENVIADOS POR VENOM ENGINE"

# Perfil medio estándar de DDMRP: ni corto/largo lead time, ni baja/alta
# variabilidad. Ver README §17 para la justificación de este default.
LTF_MEDIUM = 0.5
VF_MEDIUM = 0.5

SECTION_TYPES = ("IS_INFALTABLE", "IS_GOLDEN", "IS_ANCHOR", "BL", "OOWL")


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
    }


def compute_ddmrp_zones(
    adu: float,
    lead_time_days: float,
    ltf: float = LTF_MEDIUM,
    vf: float = VF_MEDIUM,
    minimum_green_units: float = 3.0,
) -> dict[str, float]:
    """Calcula las zonas roja/amarilla/verde de un buffer DDMRP.

    ``minimum_green_units`` evita zonas verdes en cero cuando ADU x Lead Time
    x LTF es muy pequeño, siguiendo el mismo mínimo operativo (3 unidades)
    que ya usa el resto del proyecto (MOV_MINIMO_3, OOWL, etc.).
    """
    adu = max(float(adu), 0.0)
    lead_time_days = max(float(lead_time_days), 0.0)
    red_base = adu * lead_time_days * ltf
    red_safety = red_base * vf
    red_zone = red_base + red_safety
    yellow_zone = adu * lead_time_days
    green_zone = max(adu * lead_time_days * ltf, minimum_green_units)
    top_of_red = red_zone
    top_of_yellow = red_zone + yellow_zone
    top_of_green = top_of_yellow + green_zone
    return {
        "adu": adu,
        "lead_time_days": lead_time_days,
        "ltf": ltf,
        "vf": vf,
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
    """Reparte ``quantity_needed`` entre ``source_candidates`` en orden.

    No valida bloqueos de tienda/ciudad/ruta/regional/frecuencia: eso ya se
    resolvió antes de llamar esta función (por SKU-tienda, no por origen).
    Venom es un "ontop manual": respeta el stock remanente por origen y el
    presupuesto compartido de tareas, pero **no** se limita por CAP_RECIBO —
    a propósito no cuenta contra la capacidad de recibo de la tienda.
    Devuelve la lista de (origen, cantidad) realmente asignada; puede ser
    menor a lo pedido o vacía.
    """
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
) -> dict[str, Any]:
    """Corre el llenado DDMRP de Venom al final de toda la planeación.

    ``catalog_lookup`` es ``(destino, sku) -> {"adu": float, "list_type": str}``
    y debe incluir TODAS las filas de CATALOGO (sin filtrar por ADU > 0), a
    diferencia del loader que usan AVL/Preventivo/Shalashaska.
    """
    # OOWL bloqueado a nivel motor, a pedido de negocio: no se calcula ningún
    # envío de mínimo operativo sin pronóstico, sin importar lo que llegue en
    # section_types. Es la tercera capa de defensa (la UI ya no lo ofrece y
    # el llamador en les_enfants_terribles.py ya lo filtra antes de llegar
    # aquí), para que ninguna ruta de código pueda reactivarlo por accidente.
    section_types = set(section_types) - {"OOWL"}

    summary = empty_venom_summary(True)
    summary["tasks_before"] = result.tasks_used
    summary["lead_time_days"] = float(lead_time_days)
    summary["consider_current_planning"] = bool(consider_current_planning)
    summary["section_types"] = sorted(section_types)

    if lead_time_days <= 0:
        raise ValueError("Venom Engine: el lead time debe ser mayor a cero.")
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

    # --- 1) Universo de candidatos DDMRP (Infaltable/Golden/Anchor/BL) -----
    dd_pairs: set[tuple[int, int]] = set()
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
            adu, lead_time_days, minimum_green_units=config.minimum_positive_quantity
        )
        on_hand = max(float(catalogs.stock_base.get((destination, sku), 0.0)), 0.0)
        on_order = (
            on_order_by_destination_sku[(destination, sku)]
            if consider_current_planning
            else 0
        )
        qualified_demand = adu * lead_time_days
        nfp = on_hand + on_order - qualified_demand
        if nfp >= zones["top_of_yellow"]:
            summary["skipped_buffer_healthy"] += 1
            continue
        quantity_needed = int(math.ceil(zones["top_of_green"] - nfp))
        if quantity_needed <= 0:
            summary["skipped_buffer_healthy"] += 1
            continue

        # Origen preferido: el que ya tenga tarea abierta a esta tienda-SKU
        # queda primero (evita rutas nuevas cuando ya hay una activa), luego
        # el resto de venom_origins en el orden seleccionado.
        eligible_origins = [
            source
            for source in venom_origins
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
        blocked_origin_count = len(venom_origins) - len(eligible_origins)
        if blocked_origin_count:
            summary["skipped_regional_block"] += blocked_origin_count

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
            quantity_needed=quantity_needed,
            consumed_by_origin_sku=consumed_by_origin_sku,
            summary=summary,
        )
        if not picks:
            continue

        handled_pairs.add((destination, sku))
        assigned_total = sum(quantity for _, quantity in picks)
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
        # Informativo únicamente: Venom no escribe en result.capacity_rows,
        # así que esto no refleja ni afecta ningún gasto real de CAP_RECIBO.
        cap_row = capacity_by_store.get(destination)
        cap_before = float(cap_row["M3_CONTABILIZADO_CAPACIDAD"]) if cap_row else 0.0
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
                "M3_CAPACIDAD_DESPUES": cap_before,
                "EXCEDE_CAPACIDAD_EN_ESTA_LINEA": False,
                "PASA_CAPACIDAD": True,
                "ORIGENES_USADOS": origenes_usados,
                "DETALLE_MOTIVO": (
                    "Venom DDMRP: ADU="
                    f"{adu:.4f}, Lead Time={lead_time_days:g}d, LTF={LTF_MEDIUM:g}, "
                    f"VF={VF_MEDIUM:g}, Top of Red={zones['top_of_red']:.2f}, "
                    f"Top of Yellow={zones['top_of_yellow']:.2f}, "
                    f"Top of Green={zones['top_of_green']:.2f}, NFP={nfp:.2f} "
                    f"(On-Hand={on_hand:.0f}, On-Order={on_order:.0f} "
                    f"{'considerado' if consider_current_planning else 'ignorado'}, "
                    f"Demanda calificada={qualified_demand:.2f}). "
                    f"Objetivo {quantity_needed}, asignado {assigned_total}. "
                    "Ontop manual: no cuenta contra CAP_RECIBO de la tienda."
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
    """Agrega una fila NUEVA de allocation por cada origen usado.

    A propósito nunca busca ni reutiliza una fila existente del mismo trío
    origen-destino-SKU: Venom siempre queda como una línea separada y
    adicional, nunca consolidada con lo que ya había planeado.

    A propósito tampoco toca ``result.capacity_rows``/CAP_RECIBO: Venom es
    un "ontop manual" que no cuenta contra la capacidad de recibo de la
    tienda, aunque sí cuenta contra el presupuesto compartido de tareas.
    """
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
