"""Contrato Naked (Fountain9 DOI) → Otacon residual."""

import csv
import io
from datetime import date
from pathlib import Path

import openpyxl

import modules.les_enfants_terribles as m
from tests.e2e_fixture import FakeUpload, build_workbook_bytes


def _plan(doi: int, source: int, mov: int = 10) -> bytes:
    headers = [
        "Warehouseid", "SKU ID", "Current Inventory",
        "Predicted Demand for selected duration", "Predicted Opening Inventory",
        "Replenishment Quantity for Plan Duration (MOV)",
        "Net Inter-Store Transfers", "Allocation (DOI Based)",
        "Source Id Before Multi Source",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    writer.writerow({
        "Warehouseid": 100, "SKU ID": 10, "Current Inventory": 0,
        "Predicted Demand for selected duration": mov,
        "Predicted Opening Inventory": 0,
        "Replenishment Quantity for Plan Duration (MOV)": mov,
        "Net Inter-Store Transfers": 0, "Allocation (DOI Based)": doi,
        "Source Id Before Multi Source": source,
    })
    return buffer.getvalue().encode()


def _bulk_rows(run):
    path = next(
        Path(item) for item in run["files"]
        if Path(item).name.startswith("BulkCD_") and Path(item).suffix == ".csv"
    )
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _run(doi: int, stock: int, mov: int = 10):
    return m.execute_planning(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("fountain9.csv", _plan(doi, 444, mov))],
        database_bytes=build_workbook_bytes(
            {100: "CDMX"}, [10], origin=444, origin_stock=stock
        ),
        origins=(444,), max_tasks=100, run_date=date(2026, 10, 6),
        include_insumos=False, enable_closed_stores_rule=False,
        block_fruver_811=False, block_off_schedule_shipments=False,
        minimum_positive_quantity=4,
    )


def test_naked_doi_does_not_raise_small_quantity_to_minimum():
    run = _run(doi=1, stock=1, mov=1)
    rows = _bulk_rows(run)
    assert len(rows) == 1
    assert int(rows[0]["QUANTITY"]) == 1
    assert rows[0]["PLANNING_REASON"] == m.PLANNING_REASON_FOUNTAIN9


def test_otacon_uses_residual_and_bulk_stays_unique():
    run = _run(doi=3, stock=5, mov=10)
    rows = _bulk_rows(run)
    assert len(rows) == 1
    assert int(rows[0]["QUANTITY"]) == 5
    assert m.PLANNING_REASON_FOUNTAIN9 in rows[0]["PLANNING_REASON"]
    assert m.PLANNING_REASON_OTACON in rows[0]["PLANNING_REASON"]


def test_otacon_protects_fountain9_quantity_when_naked_is_off():
    """Con Naked apagado, Otacon ejecuta DOI antes de ampliar el residual."""
    raw_database = build_workbook_bytes(
        {100: "CDMX"}, [10], origin=444, origin_stock=0
    )
    workbook = openpyxl.load_workbook(io.BytesIO(raw_database))
    workbook["TIENDA"].append(["CDMX", 831, "S831"])
    workbook["STOCK"].append([831, 10, 3, 0])
    database = io.BytesIO()
    workbook.save(database)
    workbook.close()

    run = m.execute_planning(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("fountain9.csv", _plan(3, 444, 3))],
        database_bytes=database.getvalue(),
        origins=(831, 444), max_tasks=100, run_date=date(2026, 10, 6),
        include_naked_engine=False, include_otacon_engine=True,
        include_insumos=False, enable_closed_stores_rule=False,
        block_fruver_811=False, block_off_schedule_shipments=False,
        minimum_positive_quantity=4,
    )
    rows = _bulk_rows(run)

    assert len(rows) == 1
    assert int(rows[0]["QUANTITY"]) == 3
    assert int(rows[0]["WAREHOUSE_SOURCE"]) == 831
    assert m.PLANNING_REASON_OTACON_F9_PROTECTED in rows[0]["PLANNING_REASON"]
    assert run["fountain9_audit"][0]["NAKED_EJECUTADO"] == 3


def test_piloto_store_can_only_receive_the_literal_fountain9_quantity():
    """PILOTO bloquea el residual de Otacon y cualquier ampliación posterior."""
    raw_database = build_workbook_bytes(
        {100: "CDMX"}, [10], origin=444, origin_stock=5
    )
    workbook = openpyxl.load_workbook(io.BytesIO(raw_database))
    pilot = workbook.create_sheet("PILOTO")
    pilot.append(["WAREHOUSE_ID"])
    pilot.append([100])
    database = io.BytesIO()
    workbook.save(database)
    workbook.close()

    run = m.execute_planning(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("fountain9.csv", _plan(3, 444, 10))],
        database_bytes=database.getvalue(),
        origins=(444,), max_tasks=100, run_date=date(2026, 10, 6),
        include_insumos=False, enable_closed_stores_rule=False,
        block_fruver_811=False, block_off_schedule_shipments=False,
        minimum_positive_quantity=4,
    )
    rows = _bulk_rows(run)

    assert len(rows) == 1
    assert int(rows[0]["QUANTITY"]) == 3
    assert rows[0]["PLANNING_REASON"] == m.PLANNING_REASON_PILOT_FOUNTAIN9
    assert any("Regla PILOTO activa" in warning for warning in run["warnings"])


def test_piloto_uses_codec_source_order_with_naked_off():
    """PILOTO conserva el DOI total aunque Naked esté apagado, pero no el
    origen F9: debe tomar primero el origen prioritario de CODEC."""
    raw_database = build_workbook_bytes(
        {100: "CDMX"}, [10], origin=444, origin_stock=0
    )
    workbook = openpyxl.load_workbook(io.BytesIO(raw_database))
    pilot = workbook.create_sheet("PILOTO")
    pilot.append(["WAREHOUSE_ID"])
    pilot.append([100])
    workbook["TIENDA"].append(["CDMX", 831, "S831"])
    workbook["STOCK"].append([831, 10, 10, 0])
    database = io.BytesIO()
    workbook.save(database)
    workbook.close()

    run = m.execute_planning(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("fountain9.csv", _plan(3, 444, 10))],
        database_bytes=database.getvalue(),
        origins=(831, 444), max_tasks=100, run_date=date(2026, 10, 6),
        include_naked_engine=False, include_insumos=False,
        enable_closed_stores_rule=False,
        block_fruver_811=False, block_off_schedule_shipments=False,
        minimum_positive_quantity=4,
    )
    rows = _bulk_rows(run)

    assert len(rows) == 1
    assert int(rows[0]["QUANTITY"]) == 3
    assert int(rows[0]["WAREHOUSE_SOURCE"]) == 831
    assert rows[0]["PLANNING_REASON"] == m.PLANNING_REASON_PILOT_FOUNTAIN9


def test_shalashaska_never_uses_a_piloto_store_as_evacuation_destination():
    """PILOTO permanece exclusivo de Naked aunque Shalashaska use el universo diario."""
    raw_database = build_workbook_bytes(
        {100: "CDMX", 101: "CDMX"},
        [10],
        schedule_only_stores={101},
        origin=444,
        origin_stock=100,
        extra_rows={
            "POR_MERMAR": [(444, 10, 50, 10.0, date(2026, 10, 1), date(2026, 10, 12))],
            "SHARE_VENTAS": [(100, 0.5), (101, 0.5)],
        },
    )
    workbook = openpyxl.load_workbook(io.BytesIO(raw_database))
    pilot = workbook.create_sheet("PILOTO")
    pilot.append(["WAREHOUSE_ID"])
    pilot.append([100])
    database = io.BytesIO()
    workbook.save(database)
    workbook.close()

    run = m.execute_planning(
        uploaded_copernico=[],
        uploaded_plans=[FakeUpload("fountain9.csv", _plan(3, 444, 10))],
        database_bytes=database.getvalue(),
        origins=(444,), max_tasks=100, run_date=date(2026, 10, 6),
        include_insumos=False, include_shalashaska_engine=True,
        enable_closed_stores_rule=False,
        block_fruver_811=False, block_off_schedule_shipments=False,
    )
    by_store = {int(row["WAREHOUSE_DESTINATION"]): int(row["QUANTITY"]) for row in _bulk_rows(run)}
    assert by_store[100] == 3
    assert by_store[101] == 50
