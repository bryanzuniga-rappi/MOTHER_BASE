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


# --- disparador por DOH (stock + incoming + asignado) ------------------------

def _stock(dest_stock, origin=1000.0):
    return make_catalogs(stock_base={(444, 10): origin, (100, 10): dest_stock})


def test_triggers_when_stock_positive_but_under_one_doh():
    # stock 0.5 con ADU 1 => 0.5 DOH < 1
    summary = run_kazuhira(make_result(), catalog_rows(100, adu=1.0), _stock(0.5))
    assert summary["cases_sent"] == 1


def test_does_not_trigger_at_or_above_one_doh():
    summary = run_kazuhira(make_result(), catalog_rows(100, adu=1.0), _stock(1.0))
    assert summary["cases_sent"] == 0
    assert summary["skipped_doh_sufficient"] == 1


def test_incoming_counts_toward_doh_and_can_suppress_trigger():
    catalogs = _stock(0.0)
    catalogs.incoming_stock[(100, 10)] = 2.0  # 2 DOH con ADU 1
    summary = run_kazuhira(make_result(), catalog_rows(100, adu=1.0), catalogs)
    assert summary["cases_sent"] == 0


def test_insufficient_incoming_still_triggers_and_is_subtracted():
    catalogs = _stock(0.0)
    catalogs.incoming_stock[(100, 10)] = 0.4  # < 1 DOH
    summary = run_kazuhira(make_result(), catalog_rows(100, adu=2.0), catalogs)
    # ADU 2 x (5+3) - 0.4 = 15.6 -> 16
    assert summary["units_added"] == 16


def test_already_assigned_units_count_as_position_not_exclusion():
    """Una unidad enviada por otro engine con ADU 5 deja 0.2 DOH: Kazuhira
    debe completar, no darse por servido."""
    result = make_result(allocation_rows=[{
        "WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444,
        "RETAIL_ID": 10, "QUANTITY": 1,
    }])
    summary = run_kazuhira(result, catalog_rows(100, adu=5.0), _stock(0.0))
    assert summary["cases_sent"] == 1
    # 5 x (5+3) - 0 - 0 - 1 ya asignada = 39
    assert summary["units_added"] == 39


def test_missing_stock_row_is_treated_as_zero():
    catalogs = make_catalogs(stock_base={(444, 10): 1000.0})  # sin (100, 10)
    summary = run_kazuhira(make_result(), catalog_rows(100), catalogs)
    assert summary["cases_sent"] == 1
    assert summary["missing_stock_treated_as_zero"] == 1


def test_missing_stock_row_still_skipped_by_no_fountain9_mode():
    catalogs = make_catalogs(stock_base={(444, 10): 1000.0})
    summary = run_kazuhira(
        make_result(), catalog_rows(100), catalogs,
        candidate_mode="no_fountain9_coverage",
    )
    assert summary["cases_sent"] == 0
    assert summary["skipped_missing_stock"] == 1


# --- universo de tiendas: Fountain9 + SCHEDULE de hoy -------------------------

def test_allowed_destinations_restricts_kazuhira():
    summary = run_kazuhira(
        make_result(), catalog_rows(100, 200), make_catalogs(),
        allowed_destinations={100},
    )
    assert summary["cases_sent"] == 1
    assert summary["skipped_outside_universe"] == 1


def test_scheduled_destinations_today_uses_run_weekday_and_selected_origins():
    catalogs = make_catalogs(
        schedule_days={
            (100, 444): frozenset({"LUNES", "MARTES"}),
            (200, 444): frozenset({"MARTES"}),
            (300, 831): frozenset({"LUNES"}),  # origen no seleccionado
        },
        run_weekday_norm="LUNES",
    )
    assert m.scheduled_destinations_today(catalogs, (444,)) == {100}


def test_scheduled_destinations_ignores_the_schedule_block_toggle():
    catalogs = make_catalogs(
        schedule_days={(100, 444): frozenset({"LUNES"})},
        run_weekday_norm="LUNES",
        schedule_block_enabled=False,
    )
    assert m.scheduled_destinations_today(catalogs, (444,)) == {100}


def test_planned_store_universe_unions_fountain9_and_schedule():
    catalogs = make_catalogs(
        schedule_days={(200, 444): frozenset({"LUNES"})}, run_weekday_norm="LUNES"
    )
    universe = m.build_planned_store_universe(
        [(100, 10), (100, 11)], catalogs, (444,)
    )
    assert universe["stores"] == {100, 200}
    assert universe["from_fountain9"] == {100}
    assert universe["schedule_only"] == {200}


def test_sweep_restricted_to_planned_universe():
    catalogs = make_catalogs(stock_base={(100, 10): 0.0, (200, 10): 0.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100, 200), catalogs, set(), allowed_destinations={100}
    )
    assert [r["WAREHOUSE_DESTINATION"] for r in rows] == [100]


# --- cascada de Duration/Lead Time: propia -> ciudad -> país -------------------

def _city_catalogs():
    return make_catalogs(
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "A"},
            101: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "B"},
            102: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "NUEVA"},
            200: {"city": "GDL", "city_norm": "GDL", "warehouse_name": "C"},
            300: {"city": "MTY", "city_norm": "MTY", "warehouse_name": "SIN_NADA"},
        }
    )


def test_cascade_own_data_wins():
    d, lt, src = m.resolve_duration_lead_time_with_city_fallback(
        _city_catalogs(), {100: 4.0, 101: 8.0}, {100: 2.0, 101: 6.0}
    )
    assert (d[100], lt[100], src[100]) == (4.0, 2.0, "PROPIA")


def test_cascade_store_without_data_inherits_city_average():
    d, lt, src = m.resolve_duration_lead_time_with_city_fallback(
        _city_catalogs(), {100: 4.0, 101: 8.0, 200: 20.0}, {100: 2.0, 101: 6.0, 200: 9.0}
    )
    assert src[102] == "CIUDAD"
    assert d[102] == 6.0 and lt[102] == 4.0  # promedio de 100 y 101, no de GDL


def test_cascade_leaves_unresolved_store_for_country_fallback():
    d, lt, src = m.resolve_duration_lead_time_with_city_fallback(
        _city_catalogs(), {100: 4.0}, {100: 2.0}
    )
    assert 300 not in d and 300 not in src  # MTY no tiene ninguna tienda con dato


def test_cascade_ignores_store_with_only_one_of_the_two_values():
    """No mezclar el Duration de una tienda con el Lead Time de otra."""
    d, lt, src = m.resolve_duration_lead_time_with_city_fallback(
        _city_catalogs(), {100: 4.0}, {}
    )
    assert src == {}  # 100 no tiene lead time -> no cuenta como dato propio


def test_kazuhira_detail_names_city_source():
    result = make_result()
    run_kazuhira(
        result, catalog_rows(100, adu=1.0), make_catalogs(),
        duration_mode_by_store={100: 6.0}, lead_time_mode_by_store={100: 4.0},
        duration_source_by_store={100: "CIUDAD"},
    )
    assert "promedio de la ciudad" in result.base_rows[-1]["DETALLE_MOTIVO"]


def test_kazuhira_detail_names_country_source_when_fallback_used():
    result = make_result()
    run_kazuhira(
        result, catalog_rows(100, adu=1.0), make_catalogs(),
        duration_mode_by_store={}, lead_time_mode_by_store={},
        fallback_duration=6.0, fallback_lead_time=4.0,
    )
    assert "promedio país" in result.base_rows[-1]["DETALLE_MOTIVO"]


# --- motivos por tienda-SKU (skip_reasons) ---------------------------------------

def _reasons(rows, catalogs, config=CONFIG, **kwargs):
    log: dict = {}
    result = kwargs.pop("result", None) or make_result()
    run_kazuhira(result, rows, catalogs, config, skip_reasons=log, **kwargs)
    return log


def test_healthy_with_positive_stock_is_not_logged():
    """Con stock > 0 y >= 1 DOH no se guarda una entrada por SKU sano (en un
    catálogo grande serían cientos de miles); el barrido ya lo trata como
    sano por ausencia."""
    log = _reasons(catalog_rows(100, adu=1.0), _stock(5.0))
    assert (100, 10) not in log


def test_healthy_with_zero_stock_covered_by_incoming_is_logged():
    """Stock 0 pero el incoming ya da >= 1 DOH: sin esta entrada el barrido
    lo vería como quiebre."""
    catalogs = _stock(0.0)
    catalogs.incoming_stock[(100, 10)] = 3.0
    log = _reasons(catalog_rows(100, adu=1.0), catalogs)
    assert log[(100, 10)] == m.KAZUHIRA_REASON_HEALTHY


def test_reason_no_origin_stock():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 0.0})
    assert _reasons(catalog_rows(100), catalogs)[(100, 10)] == "SIN_STOCK_ORIGEN"


def test_reason_origin_blocked_by_schedule_with_stock_available():
    catalogs = make_catalogs(
        schedule_block_enabled=True,
        schedule_days={(100, 444): frozenset({"MARTES"})},
        run_weekday_norm="LUNES",
    )
    assert _reasons(catalog_rows(100), catalogs)[(100, 10)] == "BLOQUEO_ORIGEN"


def test_reason_store_capacity():
    catalogs = make_catalogs(store_capacity={100: 0.5, 200: 1000.0})
    assert _reasons(catalog_rows(100), catalogs)[(100, 10)] == "CAPACIDAD"


def test_reason_route_cost_block():
    catalogs = make_catalogs(route_cost_blocks={(100, 10)})
    assert _reasons(catalog_rows(100), catalogs)[(100, 10)] == "RUTA_COSTOS"


def test_reason_missing_duration_data():
    log = _reasons(
        catalog_rows(100), make_catalogs(),
        duration_mode_by_store={}, lead_time_mode_by_store={},
    )
    assert log[(100, 10)] == "SIN_DURATION"


def test_reason_task_budget_exhausted_declares_every_pending_candidate():
    """El corte por presupuesto ya no es silencioso: cada pendiente queda
    con motivo."""
    config = engine.Config(origin_warehouses=(444,), max_tasks=1)
    log = _reasons(
        catalog_rows(100, 200), make_catalogs(), config,
        result=make_result(tasks_used=1),
    )
    assert log == {(100, 10): "SIN_TAREAS", (200, 10): "SIN_TAREAS"}


def test_covered_keys_have_no_skip_reason():
    log = _reasons(catalog_rows(100), make_catalogs())
    assert (100, 10) not in log


# --- barrido con motivos (corrige la inconsistencia "sano = stock > 0") ----------

def test_sweep_low_doh_not_covered_is_not_labeled_healthy():
    """Antes: stock 0.2 => 'OK SIN NECESIDAD'. Ahora el motivo de Kazuhira
    manda: quedó sin cubrir por falta de stock en CEDIS."""
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 0.2})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100), catalogs, set(), kazuhira_active=True,
        skip_reasons={(100, 10): "SIN_STOCK_ORIGEN"},
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.KAZUHIRA_UNCOVERED_LABELS["SIN_STOCK_ORIGEN"]
    assert rows[0]["MOTIVO_KAZUHIRA"] == "SIN STOCK EN CEDIS"


def test_sweep_healthy_per_kazuhira_even_if_stock_is_zero():
    """Incoming/asignado ya dan 1 DOH: sano según Kazuhira."""
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 0.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100), catalogs, set(), kazuhira_active=True,
        skip_reasons={(100, 10): m.KAZUHIRA_REASON_HEALTHY},
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_HEALTHY_CUT


def test_sweep_every_reason_has_a_distinct_registered_label():
    labels = list(m.KAZUHIRA_UNCOVERED_LABELS.values())
    assert len(set(labels)) == len(labels)
    for label in labels:
        assert label in m.BREAKDOWN_ORDER


def test_sweep_skips_closed_stores_but_declares_excluded_products():
    """Cerradas/ciudades bloqueadas ya se reportan por sus resúmenes. Un
    producto excluido (BLOQUEOS o CODEC) en quiebre NO tiene otro reporte:
    antes se omitía en silencio; ahora queda declarado."""
    catalogs = make_catalogs(
        stock_base={(100, 10): 0.0, (200, 10): 0.0, (100, 99): 0.0},
        excluded_products={99},
    )
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100, 200) + [
            {"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 99, "ADU": 1.0}
        ],
        catalogs, set(), closed_store_ids={200},
    )
    by_key = {(r["WAREHOUSE_DESTINATION"], r["RETAIL_ID"]): r["TIPO_DE_CORTE"] for r in rows}
    assert (200, 10) not in by_key                       # tienda cerrada: fuera
    assert by_key[(100, 10)] == m.CATALOG_UNIVERSE_UNCOVERED_CUT
    assert by_key[(100, 99)] == m.CATALOG_UNIVERSE_EXCLUDED_PRODUCT_CUT


def test_sweep_excluded_product_with_stock_is_healthy_not_a_gap():
    catalogs = make_catalogs(stock_base={(100, 99): 40.0}, excluded_products={99})
    rows = m.build_catalog_universe_sweep_rows(
        [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 99, "ADU": 1.0}], catalogs, set()
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_HEALTHY_CUT


def test_sweep_declares_store_missing_from_tienda_sheet():
    catalogs = make_catalogs(stock_base={(777, 10): 0.0}, stores={})
    rows = m.build_catalog_universe_sweep_rows(
        [{"WAREHOUSE_DESTINATION": 777, "RETAIL_ID": 10, "ADU": 1.0}], catalogs, set()
    )
    assert rows[0]["TIPO_DE_CORTE"] == m.CATALOG_UNIVERSE_NO_STORE_CUT


def test_new_declared_cuts_are_registered_in_breakdown_order():
    assert m.CATALOG_UNIVERSE_EXCLUDED_PRODUCT_CUT in m.BREAKDOWN_ORDER
    assert m.CATALOG_UNIVERSE_NO_STORE_CUT in m.BREAKDOWN_ORDER


def test_kazuhira_counts_excluded_product_and_unregistered_store_skips():
    catalogs = make_catalogs(excluded_products={10})
    summary = run_kazuhira(make_result(), catalog_rows(100), catalogs)
    assert summary["skipped_excluded_product"] == 1
    catalogs = make_catalogs(stores={444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O"}})
    summary = run_kazuhira(make_result(), catalog_rows(100), catalogs)
    assert summary["skipped_store_not_registered"] == 1


def test_sweep_skips_blocked_city():
    catalogs = make_catalogs(stock_base={(100, 10): 0.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100), catalogs, set(), blocked_cities=("CDMX",)
    )
    assert rows == []


def test_annotate_base_rows_sets_column_on_every_row():
    rows = [
        {"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10},
        {"WAREHOUSE_DESTINATION": 200, "RETAIL_ID": 10},
        {"WAREHOUSE_DESTINATION": 300, "RETAIL_ID": 10},
    ]
    m.annotate_base_rows_with_kazuhira_reasons(
        rows,
        {(100, 10): "CAPACIDAD", (200, 10): m.KAZUHIRA_REASON_HEALTHY},
    )
    assert [r["MOTIVO_KAZUHIRA"] for r in rows] == ["CAPACIDAD DE TIENDA", "", ""]


def test_budget_exhausted_at_start_still_separates_healthy_from_pending():
    """Caso más común en producción: Kazuhira arranca con 0 tareas libres.
    Lo sano debe seguir sano; solo lo que de verdad es un hueco queda como
    SIN_TAREAS."""
    config = engine.Config(origin_warehouses=(444,), max_tasks=1)
    catalogs = make_catalogs(
        stock_base={(444, 10): 1000.0, (100, 10): 50.0, (200, 10): 0.0}
    )
    log = _reasons(
        catalog_rows(100, 200), catalogs, config, result=make_result(tasks_used=1)
    )
    assert (100, 10) not in log  # sano: stock 50, sin entrada
    assert log[(200, 10)] == "SIN_TAREAS"


# --- barrido en streaming (memoria) -------------------------------------------

def test_sweep_iterator_is_lazy_and_matches_list_version():
    catalogs = make_catalogs(stock_base={(100, 10): 0.0, (200, 10): 50.0})
    it = m.iter_catalog_universe_sweep_rows(catalog_rows(100, 200), catalogs, set())
    assert iter(it) is it  # generador: no materializa la lista
    as_list = m.build_catalog_universe_sweep_rows(catalog_rows(100, 200), catalogs, set())
    assert [r["TIPO_DE_CORTE"] for r in as_list] == [
        m.CATALOG_UNIVERSE_UNCOVERED_CUT, m.CATALOG_UNIVERSE_HEALTHY_CUT
    ]


def test_sweep_does_not_remember_healthy_keys_but_dedupes_gaps():
    catalogs = make_catalogs(stock_base={(100, 10): 0.0})
    rows = m.build_catalog_universe_sweep_rows(
        catalog_rows(100, 100), catalogs, set()
    )
    assert len(rows) == 1  # hueco duplicado -> una sola fila


def test_swa_report_no_longer_keeps_one_row_per_stockout():
    from tests.test_swa_report import make_catalogs as swa_catalogs
    catalogs = swa_catalogs(
        stock_base={(100, 10): 0}, swa_potential_gain={(100, 10): 1.0}
    )
    report = m.build_swa_report(
        catalog_rows(100), catalogs, SimpleNamespace(allocation_rows=[])
    )
    assert "rows" not in report
    assert report["casos_perdidos"] == 1
