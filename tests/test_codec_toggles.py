"""Toggles globales de CODEC: capacidad de tienda y hoja BLOQUEOS."""

from datetime import date
from types import SimpleNamespace

import modelo_abasto as engine
import modules.les_enfants_terribles as m
from tests.e2e_fixture import FakeUpload, build_plan_csv_bytes, build_workbook_bytes
from tests.test_e2e_kazuhira import _bulk_lines

STORES = {100: "CDMX"}
SKUS = [10, 11]


def run_planning(plan_rows, *, extra_rows=None, **overrides):
    workbook = build_workbook_bytes(STORES, SKUS, extra_rows=extra_rows)
    kwargs = dict(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("plan.csv", build_plan_csv_bytes(plan_rows))],
        database_bytes=workbook,
        origins=(444,),
        max_tasks=1000,
        run_date=date(2026, 10, 5),
        include_insumos=False,
        enable_closed_stores_rule=False,
        block_fruver_811=False,
        block_off_schedule_shipments=False,
    )
    kwargs.update(overrides)
    return m.execute_planning(**kwargs)


# --- capacidad de tienda ----------------------------------------------------------

def test_store_capacity_limit_helper_respects_the_global_bypass():
    catalogs = SimpleNamespace(store_capacity={100: 0.01})
    normal = engine.Config(default_store_capacity_m3=10.0)
    bypass = engine.Config(default_store_capacity_m3=10.0, ignore_store_capacity=True)
    assert engine.store_capacity_limit_m3(catalogs, normal, 100) == 0.01
    assert engine.store_capacity_limit_m3(catalogs, normal, 999) == 10.0
    assert engine.store_capacity_limit_m3(catalogs, bypass, 100) == engine.UNLIMITED_CAPACITY_M3


def test_naked_is_cut_by_store_capacity_by_default():
    # CAP_RECIBO 0.01 m³ con 0.002 m³ por unidad => caben 5 unidades.
    run = run_planning([(100, 10, 8)], extra_rows={"CAP_RECIBO": [(100, 0.01)]})
    assert _bulk_lines(run)[(100, 10)] == 5


def test_global_toggle_ignores_store_capacity_in_every_engine():
    run = run_planning(
        [(100, 10, 8)], extra_rows={"CAP_RECIBO": [(100, 0.01)]},
        ignore_store_capacity=True,
    )
    assert _bulk_lines(run)[(100, 10)] == 8
    assert any("Capacidad de tienda ignorada" in w for w in run["warnings"])


def test_global_toggle_also_lifts_the_cap_for_catalog_coverages():
    """AVL (Solidus) comparte el bypass global, no solo Kazuhira."""
    extra = {"CAP_RECIBO": [(100, 0.01)]}
    kwargs = dict(extra_rows=extra, include_avl_fill=True, avl_doh=10.0)
    capped = _bulk_lines(run_planning([(100, 10, 1)], **kwargs))
    free = _bulk_lines(run_planning([(100, 10, 1)], ignore_store_capacity=True, **kwargs))
    assert sum(capped.values()) < sum(free.values())


def test_capacity_report_keeps_the_real_capacity_when_bypassed():
    run = run_planning(
        [(100, 10, 8)], extra_rows={"CAP_RECIBO": [(100, 0.01)]},
        ignore_store_capacity=True,
    )
    import io, zipfile
    import openpyxl
    with zipfile.ZipFile(run["zip"]) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".xlsx"))
        wb = openpyxl.load_workbook(io.BytesIO(archive.read(name)), read_only=True, data_only=True)
        rows = list(wb["BASE_TRANSFERS"].iter_rows(values_only=True))
    header = list(rows[0])
    capacities = {r[header.index("CAPACIDAD_TIENDA_M3")] for r in rows[1:] if r[header.index("RETAIL_ID")] == 10}
    assert capacities == {0.01}                # reporte con la capacidad real, no con "infinito"


# --- hoja BLOQUEOS --------------------------------------------------------------------

def test_bloqueos_sheet_excludes_skus_by_default():
    run = run_planning([(100, 10, 5), (100, 11, 5)], extra_rows={"BLOQUEOS": [(10,)]})
    lines = _bulk_lines(run)
    assert (100, 10) not in lines and lines[(100, 11)] == 5


def test_bloqueos_toggle_off_lets_sheet_skus_through_and_says_so():
    run = run_planning(
        [(100, 10, 5), (100, 11, 5)], extra_rows={"BLOQUEOS": [(10,)]},
        enable_global_blocks_rule=False,
    )
    assert _bulk_lines(run)[(100, 10)] == 5
    assert any("Regla BLOQUEOS desactivada" in w for w in run["warnings"])


def test_bloqueos_toggle_off_keeps_the_manual_sku_exclusion():
    run = run_planning(
        [(100, 10, 5), (100, 11, 5)], extra_rows={"BLOQUEOS": [(10,)]},
        enable_global_blocks_rule=False, excluded_skus=[11],
    )
    lines = _bulk_lines(run)
    assert lines[(100, 10)] == 5 and (100, 11) not in lines
