"""Contrato Naked (Fountain9 DOI) → Otacon residual."""

import csv
import io
from datetime import date
from pathlib import Path

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
        if Path(item).name == "BulkCD_444.csv"
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
