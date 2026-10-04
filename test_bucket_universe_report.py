"""Pruebas del reporte de universo completo Golden/Infaltable/Anchor
(build_bucket_universe_report): las 4 categorías y el micro-detalle de
motivos de no-cobertura."""

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
        store_priority={100: 1},
        high_value={},
        rackeados_444=set(),
        store_capacity={100: 100.0},
        copernico_unusable_444={},
        unavailable_stock={},
        stock_base={(444, 10): 100.0, (100, 10): 0.0},
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


def make_result(**overrides) -> SimpleNamespace:
    base = dict(
        base_rows=[], allocation_rows=[], capacity_rows=[], tasks_used=0,
        max_tasks=100, warnings=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def catalog_rows(adu=1.0):
    return [{"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 10, "ADU": adu}]


CONFIG = engine.Config(origin_warehouses=(444,), max_tasks=100)


def test_empty_bucket_returns_disabled():
    report = m.build_bucket_universe_report(
        set(), make_result(), make_catalogs(), CONFIG, set(), (), catalog_rows()
    )
    assert report["enabled"] is False


def test_sin_problema_when_never_at_risk():
    catalogs = make_catalogs(stock_base={(444, 10): 100.0, (100, 10): 50.0})  # 50 DOH
    report = m.build_bucket_universe_report(
        {(100, 10)}, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    assert report["summary"]["sin_problema"] == 1
    assert report["summary"]["no_cubierto"] == 0
    assert report["rows"][0]["CATEGORIA"] == "SIN_PROBLEMA"


def test_iba_a_quebrar_y_se_salvo():
    """Stock inicial > 0 pero DOH < 3; algo lo asignó hoy y llegó a >= 3."""
    catalogs = make_catalogs(stock_base={(444, 10): 100.0, (100, 10): 1.0})  # 1 DOH
    result = make_result(
        allocation_rows=[
            {"WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 10, "QUANTITY": 5},
        ]
    )
    report = m.build_bucket_universe_report(
        {(100, 10)}, result, catalogs, CONFIG, set(), (), catalog_rows()
    )
    row = report["rows"][0]
    assert row["CATEGORIA"] == "IBA_A_QUEBRAR_Y_SE_SALVO"
    assert row["DOH_INICIAL"] == 1.0
    assert row["DOH_FINAL"] == 6.0
    assert report["summary"]["iba_a_quebrar_y_se_salvo"] == 1


def test_quebrado_y_se_salvo():
    """Stock inicial = 0; algo lo asignó hoy y llegó a >= 3 DOH."""
    catalogs = make_catalogs(stock_base={(444, 10): 100.0, (100, 10): 0.0})
    result = make_result(
        allocation_rows=[
            {"WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 10, "QUANTITY": 5},
        ]
    )
    report = m.build_bucket_universe_report(
        {(100, 10)}, result, catalogs, CONFIG, set(), (), catalog_rows()
    )
    row = report["rows"][0]
    assert row["CATEGORIA"] == "QUEBRADO_Y_SE_SALVO"
    assert row["DOH_INICIAL"] == 0.0
    assert report["summary"]["quebrado_y_se_salvo"] == 1


def test_no_cubierto_when_still_below_target():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 1.0})  # sin stock en origen
    report = m.build_bucket_universe_report(
        {(100, 10)}, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    row = report["rows"][0]
    assert row["CATEGORIA"] == "NO_CUBIERTO"
    assert row["MOTIVO_NO_CUBIERTO"] != ""
    assert report["summary"]["no_cubierto"] == 1


# --- Micro-detalle: motivos de no-cobertura --------------------------------

def test_motivo_sku_excluido_globalmente():
    catalogs = make_catalogs(
        stock_base={(444, 10): 0.0, (100, 10): 1.0},
        excluded_products={10},
    )
    report = m.build_bucket_universe_report(
        {(100, 10)}, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    assert report["rows"][0]["MOTIVO_NO_CUBIERTO"] == "SKU EXCLUIDO GLOBALMENTE"


def test_motivo_tienda_cerrada():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 1.0})
    report = m.build_bucket_universe_report(
        {(100, 10)}, make_result(), catalogs, CONFIG, {100}, (), catalog_rows()
    )
    assert report["rows"][0]["MOTIVO_NO_CUBIERTO"] == "TIENDA CERRADA"


def test_motivo_ciudad_bloqueada():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 1.0})
    report = m.build_bucket_universe_report(
        {(100, 10)}, make_result(), catalogs, CONFIG, set(), ("CDMX",), catalog_rows()
    )
    assert report["rows"][0]["MOTIVO_NO_CUBIERTO"] == "CIUDAD BLOQUEADA"


def test_motivo_rackeado():
    catalogs = make_catalogs(
        stock_base={(444, 10): 0.0, (100, 10): 1.0},
        rackeados_444={10},
    )
    report = m.build_bucket_universe_report(
        {(100, 10)}, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    assert "RACKEADO" in report["rows"][0]["MOTIVO_NO_CUBIERTO"]


def test_motivo_copernico_con_razon_especifica():
    catalogs = make_catalogs(
        stock_base={(444, 10): 0.0, (100, 10): 1.0},
        copernico_unusable_by_reason={
            "LOST": {}, "CANCELADOS": {(444, 10): 5.0}, "RECIBO_444": {}, "ZONA_856": {},
        },
    )
    catalogs.copernico_unusable_by_warehouse = {(444, 10): 5.0}
    report = m.build_bucket_universe_report(
        {(100, 10)}, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    assert "COPÉRNICO CANCELADOS" in report["rows"][0]["MOTIVO_NO_CUBIERTO"]


def test_motivo_bloqueo_regional():
    catalogs = make_catalogs(
        stock_base={(444, 10): 0.0, (100, 10): 1.0},
        blocked_products={10},
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "Guadalajara", "city_norm": "GDL", "warehouse_name": "STORE"},
        },
    )
    catalogs.regional_block_enabled = True
    report = m.build_bucket_universe_report(
        {(100, 10)}, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    assert "BLOQUEO REGIONAL" in report["rows"][0]["MOTIVO_NO_CUBIERTO"]


def test_motivo_sin_stock_en_origen():
    catalogs = make_catalogs(stock_base={(444, 10): 0.0, (100, 10): 1.0})
    report = m.build_bucket_universe_report(
        {(100, 10)}, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    assert "SIN STOCK" in report["rows"][0]["MOTIVO_NO_CUBIERTO"]


def test_motivo_capacidad_de_tienda_llena():
    catalogs = make_catalogs(
        stock_base={(444, 10): 100.0, (100, 10): 1.0},
        store_capacity={100: 5.0},
    )
    result = make_result(
        capacity_rows=[
            {
                "WAREHOUSE_DESTINATION": 100,
                "CAPACIDAD_M3": 5.0,
                "M3_CONTABILIZADO_CAPACIDAD": 5.0,
            }
        ]
    )
    report = m.build_bucket_universe_report(
        {(100, 10)}, result, catalogs, CONFIG, set(), (), catalog_rows()
    )
    assert "CAPACIDAD" in report["rows"][0]["MOTIVO_NO_CUBIERTO"]


def test_motivo_sin_adu_en_ningun_lado():
    catalogs = make_catalogs(stock_base={(444, 20): 100.0, (100, 20): 1.0})
    report = m.build_bucket_universe_report(
        {(100, 20)}, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    assert report["rows"][0]["MOTIVO_NO_CUBIERTO"] == (
        "SIN ADU PARA CALCULAR DOH (ni propio ni de la ciudad)"
    )


def test_motivo_sin_bloqueo_identificado_when_actually_open():
    """Si hay stock disponible y nada la bloquea, pero igual sigue con DOH
    bajo, debe decir explícitamente que no hay motivo — no inventar uno."""
    catalogs = make_catalogs(stock_base={(444, 10): 100.0, (100, 10): 1.0})
    report = m.build_bucket_universe_report(
        {(100, 10)}, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    assert report["rows"][0]["MOTIVO_NO_CUBIERTO"] == "SIN MOTIVO DE BLOQUEO IDENTIFICADO"


def test_three_separate_buckets_are_independent():
    """Golden, Infaltable y Anchor se evalúan como universos independientes
    aunque compartan la misma tienda-SKU."""
    catalogs = make_catalogs(
        stock_base={(444, 10): 100.0, (100, 10): 50.0},
        golden_products={(100, 10)},
        infaltable_products=set(),
        anchor_products=set(),
    )
    golden_report = m.build_bucket_universe_report(
        catalogs.golden_products, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    infaltable_report = m.build_bucket_universe_report(
        catalogs.infaltable_products, make_result(), catalogs, CONFIG, set(), (), catalog_rows()
    )
    assert golden_report["universe_size"] == 1
    assert infaltable_report["enabled"] is False
