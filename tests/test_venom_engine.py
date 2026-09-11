"""Pruebas del Venom Engine (llenado DDMRP posterior a toda la planeación)."""

from pathlib import Path
from types import SimpleNamespace

import openpyxl

import modelo_abasto as engine
from engines.venom_engine import (
    VENOM_CUT,
    VENOM_REASON,
    apply_venom_engine,
    compute_ddmrp_zones,
    empty_venom_summary,
)

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as les_enfants_terribles  # noqa: E402


def make_catalogs(**overrides) -> engine.Catalogs:
    base = dict(
        volume_m3={10: 0.01, 20: 0.01},
        blocked_products=set(),
        route_cost_blocks=set(),
        store_priority={100: 1},
        high_value={},
        rackeados_444=set(),
        store_capacity={100: 50.0},
        copernico_unusable_444={},
        unavailable_stock={},
        stock_base={(444, 10): 100.0, (100, 10): 5.0, (444, 20): 50.0},
        golden_infaltables=set(),
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            831: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O831"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "Tienda Test"},
        },
        storage={},
        warnings=[],
        golden_products={(100, 10)},
    )
    base.update(overrides)
    return engine.Catalogs(**base)


def make_result(**overrides) -> SimpleNamespace:
    base = dict(
        base_rows=[], allocation_rows=[], capacity_rows=[], tasks_used=0,
        max_tasks=100, warnings=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --- Matemática DDMRP pura -------------------------------------------------

def test_compute_ddmrp_zones_matches_formulas():
    zones = compute_ddmrp_zones(adu=2.0, lead_time_days=5, minimum_green_units=3)
    assert zones["red_base"] == 5.0        # ADU x LT x LTF = 2*5*0.5
    assert zones["red_safety"] == 2.5      # Red Base x VF = 5*0.5
    assert zones["red_zone"] == 7.5        # Red Base + Red Safety
    assert zones["yellow_zone"] == 10.0    # ADU x LT
    assert zones["green_zone"] == 5.0      # max(ADU*LT*LTF, minimo) = max(5,3)
    assert zones["top_of_red"] == 7.5
    assert zones["top_of_yellow"] == 17.5
    assert zones["top_of_green"] == 22.5


def test_compute_ddmrp_zones_green_floor_applies_for_low_adu():
    zones = compute_ddmrp_zones(adu=0.1, lead_time_days=2, minimum_green_units=3)
    # ADU*LT*LTF = 0.1*2*0.5 = 0.1, muy por debajo del mínimo operativo.
    assert zones["green_zone"] == 3.0


# --- Comportamiento central: no consolidar ---------------------------------

def test_venom_creates_separate_line_without_prior_allocation():
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert len(result.allocation_rows) == 1
    assert result.allocation_rows[0]["QUANTITY"] == 28
    assert result.allocation_rows[0]["PLANNING_REASON"] == VENOM_REASON
    assert result.base_rows[0]["TIPO_DE_CORTE"] == VENOM_CUT
    assert summary["lines_sent_ddmrp"] == 1
    assert summary["tasks_added"] == 1


def test_venom_never_merges_into_existing_allocation_row():
    """El caso exacto pedido: 10 ya asignadas + Venom decide 18 más -> 2 filas."""
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result(
        base_rows=[{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "TIPO_DE_CORTE": "OK"}],
        allocation_rows=[{
            "WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 10,
            "QUANTITY": 10, "PLANNED_DATE": "", "ROUTE": 1, "DELIVERY_PRIORITY": 1,
            "CITY": "CDMX", "STORAGE": "Room Temperature", "VALUE": "REGULAR",
            "PLANNING_REASON": "MOV_MINIMO_3",
        }],
        tasks_used=1,
    )
    apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert len(result.allocation_rows) == 2, "no debe consolidar en una sola fila"
    quantities = sorted(row["QUANTITY"] for row in result.allocation_rows)
    assert quantities == [10, 18]
    original = next(r for r in result.allocation_rows if r["PLANNING_REASON"] == "MOV_MINIMO_3")
    assert original["QUANTITY"] == 10, "la fila original no debe modificarse"
    venom_row = next(r for r in result.allocation_rows if r["PLANNING_REASON"] == VENOM_REASON)
    assert venom_row["QUANTITY"] == 18
    assert result.tasks_used == 2, "cada fila (incluso duplicando el trío) cuenta como tarea"


def test_venom_shares_max_tasks_budget_and_stops_when_exhausted():
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=1)
    result = make_result(tasks_used=1)  # presupuesto ya agotado por otro engine
    summary = apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert result.allocation_rows == []
    assert summary["lines_sent_ddmrp"] == 0
    assert summary["skipped_task_limit"] >= 1


def test_venom_ignores_store_capacity_ceiling():
    """Venom es un 'ontop manual': no se limita por CAP_RECIBO."""
    catalogs = make_catalogs(store_capacity={100: 0.001})  # capacidad casi nula
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert len(result.allocation_rows) == 1
    assert result.allocation_rows[0]["QUANTITY"] == 28  # no se recorta por capacidad
    assert summary["skipped_no_capacity"] == 0
    assert result.capacity_rows == [], "Venom no debe escribir en el ledger de CAP_RECIBO"


def test_venom_does_not_pollute_capacity_ledger_used_by_other_engines():
    """Una fila previa de otro engine ya reservó capacidad; Venom no la toca."""
    catalogs = make_catalogs(store_capacity={100: 1.0})
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result(
        capacity_rows=[{
            "WAREHOUSE_DESTINATION": 100, "WAREHOUSE_NAME": "Tienda Test",
            "CITY": "CDMX", "CAPACIDAD_M3": 1.0,
            "M3_CONTABILIZADO_CAPACIDAD": 0.9, "M3_TOTAL_ASIGNADO_INCLUYE_GOLDEN": 0.9,
            "CAPACIDAD_CERRADA": False, "CAPACIDAD_SUPERADA_POR_LINEA": False,
        }],
    )
    apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert len(result.allocation_rows) == 1  # sí envía, aunque la capacidad ya esté casi al tope
    # El ledger de capacidad queda exactamente igual que antes de correr Venom.
    assert result.capacity_rows[0]["M3_CONTABILIZADO_CAPACIDAD"] == 0.9
    assert len(result.capacity_rows) == 1


def test_venom_toggle_off_ignores_on_order():
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result(
        allocation_rows=[{
            "WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 10,
            "QUANTITY": 10, "PLANNED_DATE": "", "ROUTE": 1, "DELIVERY_PRIORITY": 1,
            "CITY": "CDMX", "STORAGE": "Room Temperature", "VALUE": "REGULAR",
            "PLANNING_REASON": "MOV_MINIMO_3",
        }],
        tasks_used=1,
    )
    apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=False,  # <-- apagado
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    venom_row = next(r for r in result.allocation_rows if r["PLANNING_REASON"] == VENOM_REASON)
    assert venom_row["QUANTITY"] == 28, "con el toggle apagado debe ignorar el on_order"


def test_venom_skips_when_buffer_is_healthy():
    catalogs = make_catalogs(stock_base={(444, 10): 100.0, (100, 10): 500.0})
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert result.allocation_rows == []
    assert summary["skipped_buffer_healthy"] == 1


# --- Alcance: TIPO DE SECCIÓN y WAREHOUSE DESTINO ---------------------------

def test_venom_ignores_destinations_outside_selection():
    catalogs = make_catalogs()
    catalogs.golden_products = {(100, 10), (200, 10)}
    catalogs.stores[200] = {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "Otra"}
    catalogs.store_capacity[200] = 50.0
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),  # 200 NO seleccionada
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={
            (100, 10): {"adu": 2.0, "list_type": ""},
            (200, 10): {"adu": 2.0, "list_type": ""},
        },
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    destinations_served = {row["WAREHOUSE_DESTINATION"] for row in result.allocation_rows}
    assert destinations_served == {100}


def test_venom_respects_section_type_filter():
    """Un par Golden no debe generar línea si solo se seleccionó Anchor."""
    catalogs = make_catalogs()  # (100, 10) está en golden_products, no en anchor
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_ANCHOR"},  # <-- no incluye Golden
        lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert result.allocation_rows == []
    assert summary["candidates_ddmrp"] == 0


def test_venom_bl_uses_catalogo_list_type():
    catalogs = make_catalogs(golden_products=set())  # (100,10) ya no es Golden
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"BL"},
        lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": "BL"}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert summary["candidates_ddmrp"] == 1
    assert len(result.allocation_rows) == 1


# --- OOWL --------------------------------------------------------------

def test_venom_oowl_is_blocked_at_engine_level():
    """OOWL está bloqueado a pedido de negocio: aunque se pida explícitamente
    en section_types, apply_venom_engine no debe generar ninguna línea OOWL."""
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"OOWL"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert result.allocation_rows == []
    assert summary["lines_sent_oowl"] == 0
    assert summary["candidates_oowl"] == 0
    assert "OOWL" not in summary["section_types"]


def test_venom_oowl_skips_sku_with_destination_stock():
    """SKU 10 sí tiene stock en destino (5) -> no es caso OOWL."""
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"OOWL"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    skus_served = {row["RETAIL_ID"] for row in result.allocation_rows}
    assert 10 not in skus_served


# --- Restricciones heredadas -------------------------------------------

def test_venom_respects_closed_store_exclusion():
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids={100},  # tienda cerrada/excluida
        blocked_cities=(),
    )
    assert result.allocation_rows == []
    assert summary["skipped_closed_store"] == 1


def test_venom_respects_regional_block():
    catalogs = make_catalogs(
        blocked_products={10},
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "Guadalajara", "city_norm": "GDL", "warehouse_name": "Tienda GDL"},
        },
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    result = make_result()
    summary = apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert result.allocation_rows == []
    assert summary["skipped_regional_block"] >= 1


# --- Integración con un engine real (Naked vía plan_transfers) --------

def test_venom_after_real_plan_transfers_keeps_lines_separate():
    catalogs = make_catalogs()
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    naked_rows = [{
        "WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "SKU_NAME": "",
        "PREDICTED_OPENING_INVENTORY": 0.0, "PREDICTED_DEMAND": 0.0,
        "CURRENT_INVENTORY": 0, "MOV_ORIGINAL": 10, "INPUT_ROW": 1,
        "ES_MANUAL_FORECAST_ZERO": False,
    }]
    result = engine.plan_transfers(naked_rows, catalogs, config)
    assert len(result.allocation_rows) == 1
    assert result.allocation_rows[0]["QUANTITY"] == 10

    apply_venom_engine(
        result, catalogs, config,
        venom_origins=(444,), venom_destinations=(100,),
        section_types={"IS_GOLDEN"}, lead_time_days=5,
        consider_current_planning=True,
        catalog_lookup={(100, 10): {"adu": 2.0, "list_type": ""}},
        closed_or_excluded_store_ids=set(), blocked_cities=(),
    )
    assert len(result.allocation_rows) == 2
    assert len(result.base_rows) == 2
    venom_base_rows = [r for r in result.base_rows if r["TIPO_DE_CORTE"] == VENOM_CUT]
    assert len(venom_base_rows) == 1


# --- Loader de CATALOGO con LIST_TYPE -----------------------------------

def _build_catalogo_workbook(path: Path, with_list_type: bool) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CATALOGO"
    if with_list_type:
        ws.append(["WAREHOUSE_ID", "PRODUCT_ID", "ADU", "LIST_TYPE"])
        ws.append([100, 10, 2.0, "BL"])
        ws.append([100, 11, 0.0, "REGULAR"])
    else:
        ws.append(["WAREHOUSE_ID", "PRODUCT_ID", "ADU"])
        ws.append([100, 10, 2.0])
    wb.save(path)


def test_load_venom_catalog_lookup_reads_list_type(tmp_path):
    path = tmp_path / "catalogo.xlsx"
    _build_catalogo_workbook(path, with_list_type=True)
    lookup, warnings = les_enfants_terribles.load_venom_catalog_lookup(path)
    assert lookup[(100, 10)]["list_type"] == "BL"
    assert lookup[(100, 10)]["adu"] == 2.0
    # ADU=0 no se descarta (a diferencia de load_avl_catalog_rows).
    assert lookup[(100, 11)]["list_type"] == "REGULAR"
    assert warnings == []


def test_load_venom_catalog_lookup_without_list_type_column(tmp_path):
    path = tmp_path / "catalogo.xlsx"
    _build_catalogo_workbook(path, with_list_type=False)
    lookup, warnings = les_enfants_terribles.load_venom_catalog_lookup(path)
    assert lookup[(100, 10)]["list_type"] == ""
    assert any("LIST_TYPE" in warning for warning in warnings)


def test_empty_venom_summary_disabled():
    summary = empty_venom_summary(False)
    assert summary["enabled"] is False
    assert summary["lines_sent_ddmrp"] == 0
