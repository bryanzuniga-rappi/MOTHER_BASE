"""Pruebas de Kazuhira Engine (apply_avl_fill con candidate_mode="kazuhira"):
garantía total de cobertura de quiebres, con fallback de Duration/Lead Time
y dos toggles de bypass (presupuesto de tareas y capacidad de tienda)."""

from types import SimpleNamespace

import modelo_abasto as engine
from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


def make_catalogs(**overrides) -> engine.Catalogs:
    base = dict(
        volume_m3={10: 1.0},
        blocked_products=set(),
        route_cost_blocks=set(),
        store_priority={100: 1, 200: 1},
        high_value={},
        rackeados_444=set(),
        store_capacity={100: 1000.0, 200: 1000.0},
        copernico_unusable_444={},
        unavailable_stock={},
        stock_base={(444, 10): 1000.0, (100, 10): 0.0, (200, 10): 0.0},
        golden_infaltables=set(),
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "S100"},
            200: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "S200"},
        },
        storage={},
        warnings=[],
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


def catalog_rows(*destinations, adu=1.0):
    return [
        {"WAREHOUSE_DESTINATION": d, "RETAIL_ID": 10, "ADU": adu}
        for d in destinations
    ]


CONFIG = engine.Config(origin_warehouses=(444,), max_tasks=100)


def run_kazuhira(result, rows, catalogs, config=CONFIG, **kwargs):
    defaults = dict(
        candidate_mode="kazuhira",
        excluded_keys=set(),
        duration_mode_by_store={100: 5.0, 200: 5.0},
        lead_time_mode_by_store={100: 3.0, 200: 3.0},
    )
    defaults.update(kwargs)
    return m.apply_avl_fill(
        result, rows, catalogs, config, set(), (), 1.0, **defaults
    )


# --- cobertura base --------------------------------------------------------

def test_covers_stockout_with_same_formula_as_no_fountain9():
    result = make_result()
    summary = run_kazuhira(result, catalog_rows(100, adu=2.0), make_catalogs())
    assert summary["units_added"] == 16  # 2.0 x (5+3)
    assert summary["cases_sent"] == 1


def test_labels_are_kazuhira_specific():
    result = make_result()
    run_kazuhira(result, catalog_rows(100, adu=2.0), make_catalogs())
    assert result.base_rows[-1]["TIPO_DE_CORTE"] == m.KAZUHIRA_CUT
    assert result.base_rows[-1]["REGLA_DEMANDA"] == m.KAZUHIRA_REGLA_DEMANDA
    assert result.allocation_rows[-1][m.PLANNING_REASON_COLUMN] == m.PLANNING_REASON_KAZUHIRA


def test_covers_regardless_of_fountain9_history():
    """Punto central: excluded_keys vacío => cubre aunque Fountain9 haya
    tenido (y recomendado) la tienda-SKU, mientras siga en quiebre."""
    result = make_result()
    summary = run_kazuhira(
        result, catalog_rows(100), make_catalogs(), excluded_keys=set()
    )
    assert summary["cases_sent"] == 1


def test_already_assigned_this_run_is_not_shipped_again():
    result = make_result(
        allocation_rows=[
            {"WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 10, "QUANTITY": 5}
        ]
    )
    summary = run_kazuhira(result, catalog_rows(100), make_catalogs())
    assert summary["cases_sent"] == 0


def test_healthy_stock_is_not_covered():
    catalogs = make_catalogs(stock_base={(444, 10): 1000.0, (100, 10): 50.0})
    summary = run_kazuhira(make_result(), catalog_rows(100), catalogs)
    assert summary["cases_sent"] == 0


# --- fallback de Duration / Lead Time --------------------------------------

def test_fallback_used_when_store_has_no_own_duration_data():
    result = make_result()
    summary = run_kazuhira(
        result,
        catalog_rows(100, adu=1.0),
        make_catalogs(),
        duration_mode_by_store={},
        lead_time_mode_by_store={},
        fallback_duration=6.0,
        fallback_lead_time=4.0,
    )
    assert summary["units_added"] == 10  # 1.0 x (6+4)
    assert "promedio" in result.base_rows[-1]["DETALLE_MOTIVO"] or "país" in result.base_rows[-1]["DETALLE_MOTIVO"]


def test_no_fallback_provided_skips_like_no_fountain9():
    summary = run_kazuhira(
        make_result(),
        catalog_rows(100),
        make_catalogs(),
        duration_mode_by_store={},
        lead_time_mode_by_store={},
    )
    assert summary["cases_sent"] == 0
    assert summary["skipped_no_duration_data"] == 1


def test_no_fountain9_mode_ignores_fallback_still_skips():
    """El fallback es exclusivo de Kazuhira — Cobertura sin Fountain9 sigue
    saltándose tiendas sin dato propio."""
    summary = run_kazuhira(
        make_result(),
        catalog_rows(100),
        make_catalogs(),
        candidate_mode="no_fountain9_coverage",
        duration_mode_by_store={},
        lead_time_mode_by_store={},
        fallback_duration=6.0,
        fallback_lead_time=4.0,
    )
    assert summary["cases_sent"] == 0


# --- bypass de presupuesto de tareas ---------------------------------------

def test_respects_task_budget_by_default():
    config = engine.Config(origin_warehouses=(444,), max_tasks=1)
    result = make_result(tasks_used=1)
    summary = run_kazuhira(result, catalog_rows(100), make_catalogs(), config)
    assert summary["cases_sent"] == 0


def test_ignore_task_budget_covers_even_when_exhausted():
    config = engine.Config(origin_warehouses=(444,), max_tasks=1)
    result = make_result(tasks_used=1)
    summary = run_kazuhira(
        result, catalog_rows(100, 200), make_catalogs(), config,
        ignore_task_budget=True,
    )
    assert summary["cases_sent"] == 2
    assert result.tasks_used == 3  # excede el máximo de 1, a propósito


# --- bypass de capacidad de tienda -----------------------------------------

def test_respects_store_capacity_by_default():
    catalogs = make_catalogs(store_capacity={100: 0.5, 200: 1000.0})
    summary = run_kazuhira(make_result(), catalog_rows(100), catalogs)
    assert summary["cases_sent"] == 0
    assert summary["skipped_capacity"] == 1


def test_ignore_store_capacity_ships_full_target_anyway():
    catalogs = make_catalogs(store_capacity={100: 0.5, 200: 1000.0})
    result = make_result()
    summary = run_kazuhira(
        result, catalog_rows(100, adu=2.0), catalogs, ignore_store_capacity=True
    )
    assert summary["units_added"] == 16
    # La excepción queda visible en el reporte de capacidad:
    row = result.capacity_rows[0]
    assert row["M3_CONTABILIZADO_CAPACIDAD"] > row["CAPACIDAD_M3"]


def test_ignore_store_capacity_does_not_ignore_origin_stock():
    """Los bypass no inventan stock: sin stock en CEDIS no se manda nada."""
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 0.0})
    summary = run_kazuhira(
        make_result(), catalog_rows(100), catalogs,
        ignore_task_budget=True, ignore_store_capacity=True,
    )
    assert summary["cases_sent"] == 0
    assert summary["skipped_no_source_stock"] == 1


def test_bypass_flags_have_no_effect_on_other_modes():
    """Solo Kazuhira honra los bypass en la práctica porque es el único
    que los recibe de quien llama — pero si otro modo los recibiera, la
    firma no debe romper el modo base."""
    summary = m.apply_avl_fill(
        make_result(), catalog_rows(100), make_catalogs(), CONFIG, set(), (), 1.0,
        candidate_mode="stockout",
    )
    assert summary["mode"] == "stockout"


# --- atribución en tablas de breakdown --------------------------------------

def test_kazuhira_attributed_to_its_own_engine():
    assert m.attribute_engine(m.KAZUHIRA_CUT) == "Kazuhira"


def test_kazuhira_cut_registered_in_breakdown_order():
    assert m.KAZUHIRA_CUT in m.BREAKDOWN_ORDER


# --- barrido de universo con Kazuhira activo --------------------------------

def test_sweep_labels_remaining_stockout_as_post_kazuhira_when_active():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 0.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100), catalogs, set(), kazuhira_active=True
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_POST_KAZUHIRA_CUT


def test_sweep_keeps_sin_evaluar_label_when_kazuhira_inactive():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 0.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100), catalogs, set(), kazuhira_active=False
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_UNCOVERED_CUT


def test_sweep_healthy_label_unaffected_by_kazuhira():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 20.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100), catalogs, set(), kazuhira_active=True
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_HEALTHY_CUT


def test_post_kazuhira_cut_appears_in_cuts_detail():
    result = SimpleNamespace(
        base_rows=[{
            "WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10,
            "CANTIDAD_OBJETIVO": 0, "CANTIDAD_ASIGNADA": 0,
            "TIPO_DE_CORTE": m.CATALOG_UNIVERSE_POST_KAZUHIRA_CUT,
        }]
    )
    causales = {r["CAUSAL"] for r in m.build_cuts_detail_rows(result)}
    assert m.CATALOG_UNIVERSE_POST_KAZUHIRA_CUT in causales
