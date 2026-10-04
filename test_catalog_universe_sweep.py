"""Pruebas de build_catalog_universe_sweep_rows: filas de solo-visibilidad
para que el universo entero de CATALOGO se vea en el reporte, sin importar
qué engines de cobertura estén activos."""

import modelo_abasto as engine
from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


def make_catalogs(**overrides) -> engine.Catalogs:
    base = dict(
        volume_m3={}, blocked_products=set(), route_cost_blocks=set(),
        store_priority={}, high_value={}, rackeados_444=set(),
        store_capacity={}, copernico_unusable_444={}, unavailable_stock={},
        stock_base={}, golden_infaltables=set(), stores={}, storage={},
        warnings=[],
    )
    base.update(overrides)
    return engine.Catalogs(**base)


def _catalog_row(destination, sku):
    return {"WAREHOUSE_DESTINATION": destination, "RETAIL_ID": sku, "ADU": 1.0}


def test_healthy_sku_gets_healthy_label():
    catalogs = make_catalogs(
        stock_base={(100, 10): 50},
        stores={100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "STORE"}},
    )
    rows = m.build_catalog_universe_sweep_rows(
        [_catalog_row(100, 10)], catalogs, existing_keys=set()
    )
    assert len(rows) == 1
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_HEALTHY_CUT
    assert rows[0]["REGLA_DEMANDA"] == m.CATALOG_UNIVERSE_HEALTHY_REGLA
    assert rows[0]["CANTIDAD_OBJETIVO"] == 0
    assert rows[0]["CANTIDAD_ASIGNADA"] == 0


def test_stockout_sku_gets_uncovered_label():
    catalogs = make_catalogs(
        stock_base={(100, 10): 0},
        stores={100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "S"}},
    )
    rows = m.build_catalog_universe_sweep_rows(
        [_catalog_row(100, 10)], catalogs, existing_keys=set()
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_UNCOVERED_CUT
    assert rows[0]["REGLA_DEMANDA"] == m.CATALOG_UNIVERSE_UNCOVERED_REGLA


def test_existing_keys_are_skipped():
    """Una combinación ya tocada por cualquier engine (Fountain9 u otro)
    no debe generar una fila duplicada."""
    catalogs = make_catalogs(stock_base={(100, 10): 0, (200, 20): 0})
    rows = m.build_catalog_universe_sweep_rows(
        [_catalog_row(100, 10), _catalog_row(200, 20)],
        catalogs,
        existing_keys={(100, 10)},
    )
    assert len(rows) == 1
    assert rows[0]["RETAIL_ID"] == 20


def test_duplicate_catalog_rows_produce_one_sweep_row():
    catalogs = make_catalogs(stock_base={(100, 10): 0})
    rows = m.build_catalog_universe_sweep_rows(
        [_catalog_row(100, 10), _catalog_row(100, 10)],
        catalogs,
        existing_keys=set(),
    )
    assert len(rows) == 1


def test_never_assigns_quantity_regardless_of_stock():
    """Punto central: estas filas NUNCA consumen stock/tareas, incluso si
    hay stock de sobra en el destino — son puramente informativas."""
    catalogs = make_catalogs(stock_base={(100, 10): 99999})
    rows = m.build_catalog_universe_sweep_rows(
        [_catalog_row(100, 10)], catalogs, existing_keys=set()
    )
    assert rows[0]["CANTIDAD_ASIGNADA"] == 0
    assert rows[0]["CANTIDAD_OBJETIVO"] == 0


def test_store_context_filled_when_available():
    catalogs = make_catalogs(
        stock_base={(100, 10): 0},
        stores={100: {"city": "GDL", "city_norm": "GDL", "warehouse_name": "TIENDA GDL"}},
    )
    rows = m.build_catalog_universe_sweep_rows(
        [_catalog_row(100, 10)], catalogs, existing_keys=set()
    )
    assert rows[0]["CITY"] == "GDL"
    assert rows[0]["WAREHOUSE_NAME"] == "TIENDA GDL"


def test_empty_catalog_rows_returns_empty():
    catalogs = make_catalogs()
    assert m.build_catalog_universe_sweep_rows([], catalogs, set()) == []


def test_fallback_duration_averages_stores_with_data():
    duration, lead_time = m.compute_fallback_duration_and_lead_time(
        {100: 5.0, 200: 10.0, 300: None}, {100: 2.0, 200: 4.0, 300: None}
    )
    assert duration == 7.5
    assert lead_time == 3.0


def test_fallback_duration_none_when_no_store_has_data():
    duration, lead_time = m.compute_fallback_duration_and_lead_time({}, {})
    assert duration is None
    assert lead_time is None


def test_all_keys_already_existing_returns_empty():
    catalogs = make_catalogs(stock_base={(100, 10): 0})
    rows = m.build_catalog_universe_sweep_rows(
        [_catalog_row(100, 10)], catalogs, existing_keys={(100, 10)}
    )
    assert rows == []
