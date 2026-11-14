"""Estado visual de hojas DATA_TRANSFERS, sin recorrer su contenido completo."""

import io
from datetime import datetime

import openpyxl

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


def _database_bytes(*, farma_updated_at=None):
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name in m.REQUIRED_DATABASE_SHEETS:
        sheet = book.create_sheet(name)
        if name in m.ALEPH_SHEETS:
            sheet.cell(6, 3, "12 rows by 4 columns")
            sheet.cell(
                7,
                3,
                farma_updated_at if name == "FARMA" and farma_updated_at is not None
                else datetime(2026, 11, 3, 9, 0),
            )
        elif name in {"TIENDAS_CERRADAS", "PILOTO"}:
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
    piloto = next(row for row in health["rows"] if row["HOJA"] == "PILOTO")
    stock = next(row for row in health["rows"] if row["HOJA"] == "STOCK")
    assert farma["LINEAS"] == 12
    assert stock["LINEAS"] == 12
    assert m.database_section("FARMA") == "ALEPH"
    assert m.database_section("PILOTO") == "INPUTS MANUALES"
    assert piloto["ESTADO"] == "OK" and "FOUNTAIN9" in piloto["DETALLE"]
    assert m.database_section("STOCK") == "ALEPH"


def test_database_health_checks_farma_as_an_aleph_sheet():
    health = m.inspect_database(_database_bytes(farma_updated_at="#REF!"))
    farma = next(row for row in health["rows"] if row["HOJA"] == "FARMA")
    assert farma["ESTADO"] == "ERROR"
    assert farma["CONTROL"] == "C7"
    assert "C7" in farma["DETALLE"]


def test_database_health_uses_xml_rows_when_google_omits_sheet_dimensions():
    counts = m.database_sheet_xml_row_counts(_database_bytes())
    # FARMA es Aleph y su conteo viene de los metadatos, no del XML de datos.
    assert "FARMA" not in counts
    assert counts["VOLUMETRIA"] == 1
