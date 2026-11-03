"""Estado visual de hojas DATA_TRANSFERS, sin recorrer su contenido completo."""

import io
from datetime import datetime

import openpyxl

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


def _database_bytes(*, farma_a2=820):
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name in m.REQUIRED_DATABASE_SHEETS:
        sheet = book.create_sheet(name)
        if name in m.ALEPH_SHEETS:
            sheet.cell(7, 3, datetime(2026, 11, 3, 9, 0))
        elif name == "FARMA":
            sheet.append(["WAREHOUSE_ID", "PRODUCT_ID", "MAKER"])
            sheet.append([farma_a2, 10010, "RFP"])
        elif name == "TIENDAS_CERRADAS":
            sheet.append(["WAREHOUSE_ID"])
            sheet.append([123])
        else:
            sheet.append(["HEADER"])
            sheet.append(["dato"])
    output = io.BytesIO()
    book.save(output)
    return output.getvalue()


def test_database_health_splits_manual_and_aleph_and_counts_used_rows():
    health = m.inspect_database(_database_bytes())
    farma = next(row for row in health["rows"] if row["HOJA"] == "FARMA")
    stock = next(row for row in health["rows"] if row["HOJA"] == "STOCK")
    assert farma["LINEAS"] == 1
    assert stock["LINEAS"] == 6
    assert m.database_section("FARMA") == "INPUTS MANUALES"
    assert m.database_section("STOCK") == "ALEPH"


def test_database_health_checks_farma_ref_in_a2_not_manual_header():
    health = m.inspect_database(_database_bytes(farma_a2="#REF!"))
    farma = next(row for row in health["rows"] if row["HOJA"] == "FARMA")
    assert farma["ESTADO"] == "ERROR"
    assert farma["CONTROL"] == "A2"
    assert "A2" in farma["DETALLE"]
