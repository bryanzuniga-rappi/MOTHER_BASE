"""Pruebas del toggle 'Bloquear envíos fuera de frecuencia' (SCHEDULE)."""

from pathlib import Path

import openpyxl

import modelo_abasto as engine

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as les_enfants_terribles  # noqa: E402


def make_row(destination: int, sku: int, mov: float, input_row: int = 1) -> dict:
    return {
        "WAREHOUSE_DESTINATION": destination,
        "RETAIL_ID": sku,
        "SKU_NAME": "",
        "PREDICTED_OPENING_INVENTORY": 0.0,
        "PREDICTED_DEMAND": 0.0,
        "CURRENT_INVENTORY": 0,
        "MOV_ORIGINAL": mov,
        "INPUT_ROW": input_row,
        "ES_MANUAL_FORECAST_ZERO": False,
    }


def make_catalogs(**overrides) -> engine.Catalogs:
    base = dict(
        volume_m3={10: 1.0},
        blocked_products=set(),
        route_cost_blocks=set(),
        store_priority={100: 1},
        high_value={},
        rackeados_444=set(),
        store_capacity={100: 100.0},
        copernico_unusable_444={},
        unavailable_stock={},
        stock_base={(444, 10): 5.0, (831, 10): 5.0},
        golden_infaltables=set(),
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            831: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O831"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "STORE"},
        },
        storage={},
        warnings=[],
    )
    base.update(overrides)
    return engine.Catalogs(**base)


def test_is_schedule_blocked_ignores_missing_pair_even_when_enabled():
    catalogs = make_catalogs(
        schedule_block_enabled=True,
        run_weekday_norm="MIERCOLES",
        schedule_days={},
    )
    assert engine.is_schedule_blocked(catalogs, 444, 100) is False


def test_is_schedule_blocked_off_by_default():
    catalogs = make_catalogs(
        schedule_days={(100, 444): frozenset({"LUNES"})},
        run_weekday_norm="MIERCOLES",
    )
    # schedule_block_enabled default es False.
    assert engine.is_schedule_blocked(catalogs, 444, 100) is False


def test_is_schedule_blocked_blocks_off_day():
    catalogs = make_catalogs(
        schedule_block_enabled=True,
        run_weekday_norm="MIERCOLES",
        schedule_days={(100, 444): frozenset({"LUNES", "VIERNES"})},
    )
    assert engine.is_schedule_blocked(catalogs, 444, 100) is True


def test_is_schedule_blocked_allows_scheduled_day():
    catalogs = make_catalogs(
        schedule_block_enabled=True,
        run_weekday_norm="LUNES",
        schedule_days={(100, 444): frozenset({"LUNES", "VIERNES"})},
    )
    assert engine.is_schedule_blocked(catalogs, 444, 100) is False


def test_normalize_weekday_tolerates_accents_and_stray_punctuation():
    assert engine.normalize_weekday(" .Miércoles ") == "MIERCOLES"
    assert engine.normalize_weekday("lunes") == "LUNES"
    assert engine.normalize_weekday("DOMINGO,") == "DOMINGO"


def test_plan_transfers_blocks_single_origin_when_off_schedule():
    """444 no tiene envío programado hoy; 831 sí. Debe usar 831 completo."""
    catalogs = make_catalogs(
        schedule_block_enabled=True,
        run_weekday_norm="MIERCOLES",
        schedule_days={
            (100, 444): frozenset({"LUNES"}),
            (100, 831): frozenset({"MIERCOLES"}),
        },
    )
    config = engine.Config(origin_warehouses=(444, 831), max_tasks=100)
    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)

    assert len(result.allocation_rows) == 1
    allocation = result.allocation_rows[0]
    assert allocation["WAREHOUSE_SOURCE"] == 831
    assert allocation["QUANTITY"] == 5  # tope real: stock_base 831 = 5

    base_row = result.base_rows[0]
    assert base_row["TIPO_DE_CORTE"] == "OK PARCIAL - BLOQUEO POR FRECUENCIA"
    assert base_row["BLOQUEO_FRECUENCIA_444"] is True
    assert base_row["BLOQUEO_FRECUENCIA_831"] is False


def test_plan_transfers_blocks_all_origins_when_no_pair_is_scheduled_today():
    catalogs = make_catalogs(
        schedule_block_enabled=True,
        run_weekday_norm="MARTES",
        schedule_days={
            (100, 444): frozenset({"LUNES"}),
            (100, 831): frozenset({"LUNES"}),
        },
    )
    config = engine.Config(origin_warehouses=(444, 831), max_tasks=100)
    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)

    assert result.allocation_rows == []
    base_row = result.base_rows[0]
    assert base_row["TIPO_DE_CORTE"] == "BLOQUEO POR FRECUENCIA"
    assert base_row["CANTIDAD_ASIGNADA"] == 0


def test_plan_transfers_ignores_schedule_when_toggle_disabled():
    catalogs = make_catalogs(
        schedule_block_enabled=False,
        run_weekday_norm="MARTES",
        schedule_days={
            (100, 444): frozenset({"LUNES"}),
            (100, 831): frozenset({"LUNES"}),
        },
    )
    config = engine.Config(origin_warehouses=(444, 831), max_tasks=100)
    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)

    assigned = sum(row["QUANTITY"] for row in result.allocation_rows)
    assert assigned == 8
    assert result.base_rows[0]["TIPO_DE_CORTE"] == "OK"


def test_plan_transfers_ignores_pair_missing_from_schedule():
    """Un par destino-origen ausente de SCHEDULE no tiene restricción."""
    catalogs = make_catalogs(
        schedule_block_enabled=True,
        run_weekday_norm="MARTES",
        schedule_days={(100, 444): frozenset({"LUNES"})},  # 831 no aparece
    )
    config = engine.Config(origin_warehouses=(444, 831), max_tasks=100)
    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)

    assigned_by_source = {
        row["WAREHOUSE_SOURCE"]: row["QUANTITY"] for row in result.allocation_rows
    }
    assert assigned_by_source.get(444, 0) == 0
    assert assigned_by_source.get(831, 0) == 5


def _build_data_transfers_workbook(path: Path) -> None:
    """Arma un DATA_TRANSFERS.xlsx sintético con las 21 hojas obligatorias."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    def add(name, headers, rows):
        ws = wb.create_sheet(name)
        ws.append(headers)
        for r in rows:
            ws.append(r)

    add("VOLUMETRIA", ["SKU", "PALLETS"], [[10, 0.01]])
    add("BLOQUEOS", ["SKU"], [])
    add("RUTA_COSTOS", ["Destination", "Catalog ID"], [])
    add("PRIORIDAD", ["WAREHOUSE_ID", "PRIORIDAD"], [[100, 1]])
    add("444_HV", ["EAN", "Category"], [])
    add("831_HV", ["EAN", "Category"], [])
    add("RACKEADOS", ["WHS", "SYNC"], [])
    add("CAP_RECIBO", ["WH_ID", "CAP"], [[100, 50]])
    add("CATALOGO", ["WAREHOUSE_ID", "PRODUCT_ID", "ADU"], [])
    add("KVI", ["WAREHOUSE_ID", "PRODUCT_ID", "KVI"], [])
    add("SHARE_VENTAS", ["WAREHOUSE_ID", "SHARE"], [])
    add("NO_DISPONIBLE", ["WAREHOUSE_ID", "PRODUCT_ID", "STOCK"], [])
    add(
        "POR_MERMAR",
        [
            "WAREHOUSE_ID", "PRODUCT_ID", "STOCK_AVAILABLE", "VALUE_STOCK",
            "ARRIVAL_DATE", "EXPIRATION_DATE",
        ],
        [],
    )
    add(
        "STOCK",
        ["WAREHOUSE_ID", "PRODUCT_ID", "STOCK_DISPONIBLE_FINAL"],
        [[444, 10, 20], [831, 10, 20]],
    )
    add("OWNER", ["WAREHOUSE_ID", "PRODUCT_ID", "OWNER_NAME", "STOCK_DISPONIBLE_FINAL"], [])
    add(
        "INSUMOS",
        [
            "WAREHOUSE_DESTINATION", "WAREHOUSE_SOURCE", "RETAIL_ID", "QUANTITY",
            "PLANNED_DATE", "ROUTE", "DELIVERY_PRIORITY",
        ],
        [],
    )
    add(
        "GOLDEN_INFALTABLES_ANCHOR",
        ["WAREHOUSE_ID", "PRODUCT_ID_SYNC", "IS_INFALTABLE", "IS_GOLDEN", "IS_ANCHOR"],
        [],
    )
    add(
        "TIENDA",
        ["CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME"],
        [
            ["Ciudad de México", 100, "Tienda Test"],
            ["Ciudad de México", 444, "O444"],
            ["Ciudad de México", 831, "O831"],
        ],
    )
    add("STORAGE", ["PRODUCT_ID", "STORAGE_NAME"], [])
    add("TIENDAS_CERRADAS", ["WAREHOUSE_ID"], [])
    # Encabezado con espacio ("WAREHOUSE ID"), como en la hoja real del usuario.
    add(
        "SCHEDULE",
        ["CITY", "WAREHOUSE ID", "WAREHOUSE NAME", "ORIGEN", "DAYS"],
        [
            ["Ciudad de México", 100, "Tienda Test", 444, "Lunes"],
            [
                "Ciudad de México", 100, "Tienda Test", 831,
                "Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo",
            ],
        ],
    )
    wb.save(path)


def test_load_catalogs_reads_schedule_with_space_header(tmp_path):
    """Confirma que WAREHOUSE ID (con espacio) se reconoce igual que WAREHOUSE_ID."""
    path = tmp_path / "DATA_TRANSFERS.xlsx"
    _build_data_transfers_workbook(path)
    config = engine.Config(origin_warehouses=(444, 831), max_tasks=100)
    catalogs = engine.load_catalogs(path, config)

    assert catalogs.schedule_days[(100, 444)] == frozenset({"LUNES"})
    assert catalogs.schedule_days[(100, 831)] == {
        "LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO",
    }
    # run_weekday_norm se calcula solo, sin toggle activado por default.
    assert catalogs.schedule_block_enabled is False
    assert catalogs.run_weekday_norm in engine.WEEKDAY_DISPLAY_NAMES


def test_schedule_block_summary_reports_full_cut(tmp_path):
    path = tmp_path / "DATA_TRANSFERS.xlsx"
    _build_data_transfers_workbook(path)
    config = engine.Config(origin_warehouses=(444, 831), max_tasks=100)
    catalogs = engine.load_catalogs(path, config)
    catalogs.schedule_block_enabled = True
    # Forzamos un día en el que ningún origen tiene envío programado.
    catalogs.schedule_days = {
        (100, 444): frozenset({"LUNES"}),
        (100, 831): frozenset({"LUNES"}),
    }
    catalogs.run_weekday_norm = "MARTES"

    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)
    les_enfants_terribles.normalize_result_storage(result)
    les_enfants_terribles.apply_reporting_labels(result)
    summary = les_enfants_terribles.schedule_block_summary(result, catalogs)

    assert summary["enabled"] is True
    assert summary["weekday"] == "Martes"
    assert summary["requirements_full_cut"] == 1
    assert summary["requirements_partial_cut"] == 0
    assert summary["units_missing"] == 8
    assert summary["stores"] == 1
    assert summary["products"] == 1
    assert summary["pairs_configured"] == 2


def test_schedule_block_summary_disabled_returns_zeroed_summary(tmp_path):
    path = tmp_path / "DATA_TRANSFERS.xlsx"
    _build_data_transfers_workbook(path)
    config = engine.Config(origin_warehouses=(444, 831), max_tasks=100)
    catalogs = engine.load_catalogs(path, config)
    catalogs.schedule_block_enabled = False

    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)
    les_enfants_terribles.normalize_result_storage(result)
    les_enfants_terribles.apply_reporting_labels(result)
    summary = les_enfants_terribles.schedule_block_summary(result, catalogs)

    assert summary["enabled"] is False
    assert summary["requirements_full_cut"] == 0
    assert summary["requirements_partial_cut"] == 0

