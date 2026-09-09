"""Pruebas del bucket dedicado 'CORTE POR COPÉRNICO' en TIPO_DE_CORTE.

Antes de este cambio, un requerimiento sin cubrir por exclusiones de
COPÉRNICO (ubicación no usable, LOST, etc.) caía en el bucket genérico
"CORTE POR STOCK", con COPERNICO_NO_USABLE mencionado solo como texto
suelto dentro de DETALLE_MOTIVO — sin forma de cuantificarlo por separado
en el breakdown. Ahora tiene su propio TIPO_DE_CORTE.
"""

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
        copernico_unusable_by_warehouse={},
        unavailable_stock={},
        stock_base={(444, 10): 5.0},
        golden_infaltables=set(),
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "STORE"},
        },
        storage={},
        warnings=[],
    )
    base.update(overrides)
    return engine.Catalogs(**base)


def test_full_cut_attributed_to_copernico_when_it_would_have_covered_it():
    """Todo el stock quedó excluido por COPÉRNICO -> bucket dedicado, no genérico."""
    catalogs = make_catalogs(
        stock_base={(444, 10): 5.0},
        copernico_unusable_by_warehouse={(444, 10): 5.0},  # excluye TODO
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)

    base_row = result.base_rows[0]
    assert base_row["CANTIDAD_ASIGNADA"] == 0
    assert base_row["TIPO_DE_CORTE"] == "CORTE POR COPÉRNICO"
    assert "COPÉRNICO" in base_row["DETALLE_MOTIVO"]


def test_partial_cut_attributed_to_copernico():
    catalogs = make_catalogs(
        stock_base={(444, 10): 10.0},
        copernico_unusable_by_warehouse={(444, 10): 4.0},  # deja 6 usables
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)

    base_row = result.base_rows[0]
    assert base_row["CANTIDAD_ASIGNADA"] == 6
    assert base_row["TIPO_DE_CORTE"] == "OK PARCIAL - CORTE POR COPÉRNICO"


def test_generic_stock_cut_unaffected_when_copernico_excludes_nothing():
    """Regresión: un stockout genuino sin COPÉRNICO sigue cayendo en el
    bucket genérico de siempre."""
    catalogs = make_catalogs(
        stock_base={(444, 10): 3.0},
        copernico_unusable_by_warehouse={},
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)

    base_row = result.base_rows[0]
    assert base_row["CANTIDAD_ASIGNADA"] == 3
    assert base_row["TIPO_DE_CORTE"] == "OK PARCIAL - CORTE POR STOCK"


def test_regional_block_unaffected_by_new_copernico_bucket():
    """Un bloqueo regional normal (sin exclusión de COPÉRNICO de por medio)
    sigue cayendo en BLOQUEO REGIONAL, sin que el nuevo bucket lo interfiera."""
    catalogs = make_catalogs(
        stock_base={(444, 10): 5.0},
        copernico_unusable_by_warehouse={},  # sin exclusión de COPÉRNICO aquí
        blocked_products={10},
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "Guadalajara", "city_norm": "GDL", "warehouse_name": "STORE GDL"},
        },
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)

    base_row = result.base_rows[0]
    assert base_row["TIPO_DE_CORTE"] == "BLOQUEO REGIONAL"


def test_regional_block_priority_over_copernico_with_two_origins():
    """444 tiene stock real bloqueado por regla regional; 831 tiene stock
    excluido por COPÉRNICO. El bloqueo regional manda en la etiqueta."""
    catalogs = make_catalogs(
        stock_base={(444, 10): 5.0, (831, 10): 5.0},
        copernico_unusable_by_warehouse={(831, 10): 5.0},
        blocked_products={10},
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            831: {"city": "Guadalajara", "city_norm": "GDL", "warehouse_name": "O831"},
            100: {"city": "Guadalajara", "city_norm": "GDL", "warehouse_name": "STORE GDL"},
        },
    )
    config = engine.Config(origin_warehouses=(444, 831), max_tasks=100)
    rows = [make_row(100, 10, mov=8)]
    result = engine.plan_transfers(rows, catalogs, config)

    base_row = result.base_rows[0]
    assert base_row["TIPO_DE_CORTE"] == "BLOQUEO REGIONAL"


def test_copernico_cut_summary_quantifies_units(tmp_path):
    """El resumen dedicado suma unidades, no solo casos."""
    catalogs = make_catalogs(
        stock_base={(444, 10): 5.0, (444, 20): 10.0},
        copernico_unusable_by_warehouse={(444, 10): 5.0, (444, 20): 4.0},
        volume_m3={10: 1.0, 20: 1.0},
    )
    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    rows = [make_row(100, 10, mov=8), make_row(100, 20, mov=8, input_row=2)]
    result = engine.plan_transfers(rows, catalogs, config)
    les_enfants_terribles.normalize_result_storage(result)
    les_enfants_terribles.apply_reporting_labels(result)
    summary = les_enfants_terribles.copernico_cut_summary(result)

    assert summary["requirements_full_cut"] == 1  # SKU 10: 0 asignado
    assert summary["requirements_partial_cut"] == 1  # SKU 20: 6 de 8
    assert summary["units_missing"] == 8 + 2  # (8-0) + (8-6)
    assert summary["stores"] == 1
    assert summary["products"] == 2


def test_copernico_cut_summary_empty_when_no_cuts():
    result_like = type("R", (), {"base_rows": [{"TIPO_DE_CORTE": "OK"}]})()
    summary = les_enfants_terribles.copernico_cut_summary(result_like)
    assert summary["requirements_full_cut"] == 0
    assert summary["requirements_partial_cut"] == 0
    assert summary["units_missing"] == 0
