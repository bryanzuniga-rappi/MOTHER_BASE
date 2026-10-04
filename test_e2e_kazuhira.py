"""Prueba de punta a punta de execute_planning con Kazuhira activo.

Existe porque compilar y probar piezas sueltas no detecta errores de
tiempo de ejecución en la orquestación (variables fuera de alcance, un
archivo que no llega al zip, etc.)."""

from datetime import date

import modelo_abasto as engine
from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402
from tests.e2e_fixture import (  # noqa: E402
    FakeUpload, build_plan_csv_bytes, build_workbook_bytes, read_zip_names,
)

STORES = {100: "CDMX", 101: "CDMX", 300: "CDMX"}   # 300 solo está en SCHEDULE
SKUS = [10, 11, 12]


def _run(**overrides):
    workbook = build_workbook_bytes(
        STORES, SKUS, schedule_only_stores={300},
        destination_stock={(101, 12): 50.0},        # tienda 101 / sku 12: sana
    )
    plan = build_plan_csv_bytes([(100, 10, 5), (101, 10, 5)])
    kwargs = dict(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("plan.csv", plan)],
        database_bytes=workbook,
        origins=(444,),
        max_tasks=1000,
        run_date=date(2026, 10, 5),
        include_insumos=False,
        include_kazuhira_engine=True,
        enable_closed_stores_rule=False,
    )
    kwargs.update(overrides)
    return m.execute_planning(**kwargs)


def _bulk_lines(run):
    import csv, io, zipfile
    with zipfile.ZipFile(run["zip"]) as archive:
        text = archive.read("BulkCD_444.csv").decode("utf-8-sig")
    return {
        (int(r["WAREHOUSE_DESTINATION"]), int(r["RETAIL_ID"])): int(r["QUANTITY"])
        for r in csv.DictReader(io.StringIO(text))
    }


def test_kazuhira_end_to_end_covers_catalog_gaps_and_schedule_only_store():
    run = _run()
    k = run["kazuhira"]
    assert k["universe_stores"] == 3
    assert k["universe_from_fountain9"] == 2
    assert k["universe_schedule_only"] == 1
    lines = _bulk_lines(run)
    # La tienda 300 NO viene en Fountain9, solo en SCHEDULE: recibe sus 3 SKUs.
    # Duration/Lead Time heredados de la ciudad (5 + 3) con ADU 1 => 8.
    assert {sku: lines[(300, sku)] for sku in SKUS} == {10: 8, 11: 8, 12: 8}
    # SKUs que Fountain9 no pidió en tiendas que sí planea:
    assert lines[(100, 11)] == 8 and lines[(100, 12)] == 8 and lines[(101, 11)] == 8
    # Lo que Fountain9 sí pidió se respeta (Kazuhira no lo duplica):
    assert lines[(100, 10)] == 5 and lines[(101, 10)] == 5
    # (101, 12) tiene stock 50: sano, no se manda nada.
    assert (101, 12) not in lines


def test_healthy_universe_goes_to_csv_in_zip_not_to_base_rows():
    run = _run()
    names = read_zip_names(run["zip"])
    assert any("Universo_Catalogo_Sin_Necesidad" in n for n in names)
    healthy = run["status_counts"].get(m.CATALOG_UNIVERSE_HEALTHY_CUT, 0)
    assert healthy >= 1                       # (101, 12) al menos


def test_every_planned_store_sku_is_covered_or_declared_or_healthy():
    """La garantía: nada de las tiendas planeadas queda sin explicación."""
    run = _run()
    counts = run["status_counts"]
    total_combinations = len(STORES) * len(SKUS)      # 9
    accounted = sum(
        counts.get(label, 0)
        for label in (
            m.KAZUHIRA_CUT, m.CATALOG_UNIVERSE_HEALTHY_CUT,
            *m.KAZUHIRA_UNCOVERED_LABELS.values(),
            m.CATALOG_UNIVERSE_POST_KAZUHIRA_CUT,
            "OK COMPLETO POR FOUNTAIN9", "SIN RECOMENDACIÓN",
            "OK MANUAL POR FORECAST Y STOCK EN CERO",
        )
    )
    assert accounted == total_combinations


def test_run_without_kazuhira_has_no_healthy_csv():
    run = _run(include_kazuhira_engine=False, include_avl_fill=False)
    names = read_zip_names(run["zip"])
    assert not any("Universo_Catalogo_Sin_Necesidad" in n for n in names)
