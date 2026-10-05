"""COPÉRNICO y storage del 856: la zona (ZonaPiso) manda; si el SKU no tiene
zona, se usa el storage de DATA_TRANSFERS (hoja STORAGE).

Origen del caso: csv.Sniffer elegía la comilla simple como entrecomillado
(las descripciones traen apóstrofes) y el lector perdía 44 % de las filas, entre
ellas las del SKU 7235 (zona RR => Refrigerated) que salió Room Temperature."""

import csv
import io
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from tests._streamlit_stub import install

install()

import modelo_abasto as engine  # noqa: E402
import modules.les_enfants_terribles as m  # noqa: E402
from tests.e2e_fixture import FakeUpload, build_plan_csv_bytes, build_workbook_bytes

HEADER = ["BODEGA", "EAN", "referencia", "Descripcion", "Ubicacion", "Saldo", "Estatus",
          "diasvigencia", "ZonaPiso"]

# Patrón real del archivo del 856: la columna diasvigencia trae valores como '-28
# (apóstrofe de texto de Excel justo después de una coma) y las descripciones
# traen ' ' sueltos. Eso hacía que csv.Sniffer eligiera la comilla simple.
TRICKY_DESCRIPTIONS = [
    "Royal Canin Loaf - ' ' - 385 g", "Pulparindo gigante - ' ' - 1 ud.",
    "Crema L'Oréal 50 g", "Salsa ' picante", "Aceite normal",
]


def write_copernico(tmp_path, rows, delimiter=",", name="COPERNICO.csv"):
    path = tmp_path / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


def break_the_file(path, marker="DESC_ROTA"):
    """Deja una celda que abre comilla y nunca la cierra (fusiona filas al leer)."""
    text = path.read_text(encoding="utf-8")
    assert marker in text
    path.write_text(text.replace(marker, '"' + marker, 1), encoding="utf-8")


def tricky_rows(count=60, start=7000):
    rows = []
    for i in range(count):
        zone = ("E", "RR", "RCC", "MRM", "BIN")[i % 5]
        rows.append(["856", start + i, f"ref{i}", TRICKY_DESCRIPTIONS[i % len(TRICKY_DESCRIPTIONS)],
                     f"U{i}", 10 + i, "Aprobado", "'-28" if i % 2 == 0 else "30", zone])
    return rows


def target_rows(skus=(7235,)):
    """Filas del caso: SKUs en zona RR (Refrigerated), con dos ubicaciones cada uno."""
    return [["856", sku, "r", "Producto normal", f"RR0{n}", saldo, "Aprobado", "30", "RR"]
            for sku in skus for n, saldo in ((1, 9), (2, 153))]


def real_pattern_rows(skus=(7235,)):
    """El caso real: las filas del SKU quedan en medio de filas con el patrón '-28.
    Con el lector viejo (csv.Sniffer) este archivo se leía en 21 de 62 filas y el
    SKU se perdía."""
    return tricky_rows(5, 1000) + target_rows(skus) + tricky_rows(55, 2000)


def load(path):
    return engine.load_copernico_unusable_csv(path)


# --- lectura -----------------------------------------------------------------------------

def test_every_row_is_read_even_with_apostrophes_in_the_descriptions(tmp_path):
    rows = tricky_rows()
    _unusable, overrides, summary = load(write_copernico(tmp_path, rows))
    assert summary["total_rows"] == len(rows) == summary["source_rows"]
    assert summary["row_count_mismatches"] == []
    assert summary["warehouse_856_unknown_zones"] == {}


def test_zone_decides_the_storage_of_the_856(tmp_path):
    _u, overrides, _s = load(write_copernico(tmp_path, tricky_rows()))
    assert overrides[(856, 7000)] == "Room Temperature"      # E
    assert overrides[(856, 7001)] == "Refrigerated"          # RR
    assert overrides[(856, 7002)] == "Freezer"               # RCC
    assert (856, 7003) not in overrides                      # MRM: se ignora, sin override
    assert (856, 7004) not in overrides                      # BIN: no usable, sin override


def test_the_7235_case_is_read_in_full(tmp_path):
    """Regresión del 7235: con el lector viejo se leían 21 de 62 filas."""
    rows = real_pattern_rows()
    _u, overrides, summary = load(write_copernico(tmp_path, rows))
    assert summary["total_rows"] == len(rows) == 62
    assert overrides[(856, 7235)] == "Refrigerated"
    assert summary["warehouse_856_unknown_zones"] == {}


def test_semicolon_and_tab_delimited_files_still_load(tmp_path):
    for delimiter in (";", "\t"):
        path = write_copernico(tmp_path, tricky_rows(10), delimiter=delimiter, name=f"c{ord(delimiter)}.csv")
        _u, overrides, summary = load(path)
        assert summary["total_rows"] == 10 and overrides[(856, 7001)] == "Refrigerated"


def test_a_misread_file_is_flagged_instead_of_failing_silently(tmp_path):
    """Una comilla doble sin cerrar fusiona filas: debe avisarse."""
    rows = tricky_rows(12)
    rows[3][3] = "DESC_ROTA"
    path = write_copernico(tmp_path, rows)
    break_the_file(path)
    _u, _o, summary = load(path)
    mismatch = summary["row_count_mismatches"]
    assert mismatch and mismatch[0]["file"] == "COPERNICO.csv"
    assert mismatch[0]["read"] < mismatch[0]["lines"]
    assert mismatch[0]["lines"] == 12


def test_load_catalogs_warns_when_rows_do_not_match(tmp_path):
    rows = tricky_rows(12)
    rows[3][3] = "DESC_ROTA"
    path = write_copernico(tmp_path, rows)
    break_the_file(path)
    database = tmp_path / "dt.xlsx"
    database.write_bytes(build_workbook_bytes({100: "CDMX"}, [10], origin=856))
    catalogs = engine.load_catalogs(
        database, engine.Config(origin_warehouses=(856,), max_tasks=10), copernico_csv_path=[path]
    )
    assert any("se leyeron" in w and "líneas de datos" in w for w in catalogs.warnings)


# --- jerarquía: zona > OVER_ORIGEN_STORAGE > hoja STORAGE > Room Temperature ---------------

def fake_catalogs(**kwargs):
    base = dict(
        copernico_storage_by_warehouse={}, storage_override_by_origin={},
        origin_storage_override_enabled=False, storage={},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_zone_is_mandatory_over_the_sheet_and_the_manual_override():
    c = fake_catalogs(
        copernico_storage_by_warehouse={(856, 1): "Refrigerated"},
        storage_override_by_origin={(856, 1): "Freezer"}, origin_storage_override_enabled=True,
        storage={1: "Room Temperature"},
    )
    assert engine.source_storage_type(c, 856, 1) == "Refrigerated"


def test_without_a_zone_the_data_transfers_storage_applies():
    c = fake_catalogs(storage={1: "Freezer", 2: ""})
    assert engine.source_storage_type(c, 856, 1) == "Freezer"          # hoja STORAGE
    assert engine.source_storage_type(c, 856, 2) == "Room Temperature"  # sin dato en ningún lado
    assert engine.source_storage_type(c, 856, 3) == "Room Temperature"


def test_manual_override_only_fills_in_where_there_is_no_zone():
    c = fake_catalogs(storage_override_by_origin={(856, 1): "Freezer"},
                      origin_storage_override_enabled=True, storage={1: "Room Temperature"})
    assert engine.source_storage_type(c, 856, 1) == "Freezer"


def test_other_origins_are_not_affected_by_the_856_zone():
    c = fake_catalogs(copernico_storage_by_warehouse={(856, 1): "Refrigerated"}, storage={1: "Room Temperature"})
    assert engine.source_storage_type(c, 444, 1) == "Room Temperature"
    assert engine.source_storage_type(c, 831, 1) == "Room Temperature"


def test_unassigned_rows_show_the_zone_storage_too():
    c = fake_catalogs(copernico_storage_by_warehouse={(856, 1): "Refrigerated"}, storage={1: "Room Temperature"})
    assert engine.allocation_storage_summary(c, [], 1) == "Room Temperature"             # sin pistas
    assert engine.allocation_storage_summary(c, [], 1, fallback_sources=(444, 856)) == "Refrigerated"
    assert engine.allocation_storage_summary(c, [(856, 5)], 1) == "Refrigerated"


# --- punta a punta: todos los engines escriben el storage de la zona -----------------------------

SKUS = [7235, 7236, 7237, 7238]
STORAGE_SHEET = [(sku, "Room Temperature") for sku in SKUS[:3]] + [(7238, "Freezer")]
OWNER = [(856, sku, "OWNER_A", 100000) for sku in SKUS]


def copernico_upload():
    """7235-7237 en zona RR (Refrigerated) dentro de un archivo con el patrón real
    (apóstrofes); el 7238 no tiene fila: debe quedar con la hoja (Freezer)."""
    rows = real_pattern_rows(SKUS[:3]) + [["856", 999, "r", "Otro producto", "E01", 5, "Aprobado", "30", "E"]]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADER)
    writer.writerows(rows)
    return FakeUpload("COPERNICO_856.csv", buffer.getvalue().encode())


def run_856(plan, **overrides):
    database = build_workbook_bytes(
        {100: "Monterrey"}, SKUS, origin=856,
        extra_rows={"STORAGE": STORAGE_SHEET, "OWNER": OWNER, "SHARE_VENTAS": [(100, 1.0)]},
        destination_stock={(100, 7236): 1.0}, catalog_adu={(100, 7236): 5.0},
    )
    kwargs = dict(
        uploaded_copernico=[copernico_upload()], uploaded_plans=[FakeUpload("p.csv", build_plan_csv_bytes(plan))],
        database_bytes=database, origins=(856,), max_tasks=500, run_date=date(2026, 10, 5),
        include_insumos=False, enable_closed_stores_rule=False, block_fruver_811=False,
        block_off_schedule_shipments=False, include_naked_engine=True, include_solidus_engine=False,
        include_kazuhira_engine=False,
    )
    kwargs.update(overrides)
    return m.execute_planning(**kwargs)


def bulk_lines(run):
    out = []
    with zipfile.ZipFile(run["zip"]) as archive:
        for name in archive.namelist():
            if name.startswith("BulkCD_856"):
                text = archive.read(name).decode("utf-8-sig")
                out += list(csv.DictReader(io.StringIO(text)))
    return {int(float(r["RETAIL_ID"])): r for r in out}


def test_naked_line_of_the_7235_comes_out_refrigerated():
    lines = bulk_lines(run_856([(100, 7235, 5)]))
    assert lines[7235]["STORAGE"] == "Refrigerated"


def test_solidus_coverages_use_the_zone_not_the_sheet():
    run = run_856(
        [(100, 7235, 5)], include_solidus_engine=True, include_avl_fill=True,
        include_preventive_fill=True, avl_doh=3.0,
    )
    lines = bulk_lines(run)
    assert lines[7236]["STORAGE"] == "Refrigerated"             # Preventivo / AVL (no es Fountain9)
    assert lines[7237]["STORAGE"] == "Refrigerated"
    assert lines[7236]["PLANNING_REASON"] != "FOUNTAIN9 · NAKED ENGINE"


def test_sku_without_a_zone_keeps_the_data_transfers_storage():
    run = run_856([(100, 7235, 5)], include_solidus_engine=True, include_avl_fill=True, avl_doh=3.0)
    assert bulk_lines(run)[7238]["STORAGE"] == "Freezer"


def test_every_assigned_line_of_every_engine_uses_the_zone_when_there_is_one():
    run = run_856(
        [(100, 7235, 5)], include_solidus_engine=True, include_avl_fill=True,
        include_preventive_fill=True, avl_doh=3.0, include_kazuhira_engine=True,
    )
    wrong = {sku: r["STORAGE"] for sku, r in bulk_lines(run).items()
             if sku in (7235, 7236, 7237) and r["STORAGE"] != "Refrigerated"}
    assert not wrong


# --- reportes ------------------------------------------------------------------------------------

def test_base_transfers_shows_the_zone_storage_on_rows_that_were_not_assigned():
    """Fila de corte (sin stock del owner): STORAGE debe verse con la zona."""
    database = build_workbook_bytes(
        {100: "Monterrey"}, SKUS, origin=856, extra_rows={"STORAGE": STORAGE_SHEET, "OWNER": []},
    )
    run = m.execute_planning(
        uploaded_copernico=[copernico_upload()],
        uploaded_plans=[FakeUpload("p.csv", build_plan_csv_bytes([(100, 7235, 5)]))],
        database_bytes=database, origins=(856,), max_tasks=50, run_date=date(2026, 10, 5),
        include_insumos=False, enable_closed_stores_rule=False, block_fruver_811=False,
        block_off_schedule_shipments=False, include_naked_engine=True,
    )
    import openpyxl
    with zipfile.ZipFile(run["zip"]) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".xlsx"))
        wb = openpyxl.load_workbook(io.BytesIO(archive.read(name)), read_only=True, data_only=True)
        rows = list(wb["BASE_TRANSFERS"].iter_rows(values_only=True))
    header = list(rows[0])
    row = next(r for r in rows[1:] if r[header.index("RETAIL_ID")] == 7235)
    assert row[header.index("CANTIDAD_ASIGNADA")] == 0
    assert row[header.index("STORAGE")] == "Refrigerated"


def test_kazuhira_declared_gaps_are_attributed_to_kazuhira_not_naked():
    for label in m.KAZUHIRA_UNCOVERED_LABELS.values():
        row = {"TIPO_DE_CORTE": label, "REGLA_DEMANDA": "KAZUHIRA_SIN_STOCK_ORIGEN"}
        assert m.attribute_row(row) == ("Kazuhira", "—"), label
    assert m.attribute_row({"TIPO_DE_CORTE": "OK COMPLETO POR FOUNTAIN9", "REGLA_DEMANDA": "ROQ"})[0] == "Naked"


def test_warehouse_detection_uses_the_same_fixed_format(tmp_path):
    path = write_copernico(tmp_path, real_pattern_rows())
    upload = FakeUpload("COPERNICO.csv", path.read_bytes())
    assert m.detect_copernico_warehouses([upload]) == {856}
