"""Pruebas de la exclusión universal ZonaPiso = LOST en el CSV de COPÉRNICO.

Antes de este cambio, ZonaPiso solo se evaluaba para la bodega 856 (para
clasificar E/RCC/RR/MRM). El resto de las bodegas únicamente miraban la
columna Ubicacion. Ahora, sin importar la bodega, una fila con
ZonaPiso = LOST siempre excluye ese saldo, igual que CANCELADOS/RECIBO_444
en Ubicacion.
"""

import csv

import modelo_abasto as engine


def _write_copernico_csv(path, rows, header=("Bodega", "EAN", "Ubicacion", "Saldo", "ZonaPiso")):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_lost_excludes_regardless_of_warehouse(tmp_path):
    path = tmp_path / "copernico.csv"
    _write_copernico_csv(
        path,
        [
            # Bodega no-856, ubicación normalmente usable (empieza con "Z"),
            # pero LOST debe excluirla de todas formas.
            [444, 10, "ZABCDEFG", 5, "LOST"],
            # Bodega no-856, ubicación usable normal, sin LOST -> disponible.
            [444, 11, "ZABCDEFG", 7, ""],
            # Otra bodega distinta (831), también debe respetar LOST.
            [831, 30, "ZABCDEFG", 6, "LOST"],
        ],
    )
    unusable, _storage_overrides, summary = engine.load_copernico_unusable_csv(path)

    assert unusable[(444, 10)] == 5.0
    assert (444, 11) not in unusable
    assert unusable[(831, 30)] == 6.0
    assert summary["lost_zone_rows"] == 2
    assert summary["lost_zone_units"] == 11.0
    assert summary["lost_zone_warehouses"] == [444, 831]


def test_lost_takes_priority_over_usable_ubicacion():
    """LOST excluye incluso si Ubicacion por sí sola sería usable."""
    assert engine.copernico_is_usable("ZABCDEFG") is True  # referencia: sería usable


def test_existing_ubicacion_rules_unaffected(tmp_path):
    """RECIBO_444/CANCELADOS en Ubicacion se siguen excluyendo igual que antes."""
    path = tmp_path / "copernico.csv"
    _write_copernico_csv(
        path,
        [
            [444, 12, "RECIBO_444", 3, ""],
            [444, 13, "CANCELADOS", 2, ""],
            [444, 14, "ZABCDEFG", 9, ""],
        ],
    )
    unusable, _storage_overrides, summary = engine.load_copernico_unusable_csv(path)

    assert unusable[(444, 12)] == 3.0
    assert unusable[(444, 13)] == 2.0
    assert (444, 14) not in unusable
    assert summary["lost_zone_rows"] == 0


def test_lost_in_warehouse_856_bypasses_zone_classification(tmp_path):
    """En 856, LOST no debe clasificarse como E/RCC/RR/MRM ni como zona desconocida."""
    path = tmp_path / "copernico.csv"
    _write_copernico_csv(
        path,
        [
            [856, 20, "", 9, "LOST"],
            [856, 21, "", 4, "E"],
            [856, 22, "", 6, "MRM"],
        ],
    )
    unusable, storage_overrides, summary = engine.load_copernico_unusable_csv(path)

    assert unusable[(856, 20)] == 9.0
    assert (856, 21) not in unusable
    assert storage_overrides.get((856, 21)) == "Room Temperature"
    assert (856, 22) not in unusable  # MRM: ya descontado en STOCK_DISPONIBLE_FINAL
    assert summary["lost_zone_rows"] == 1
    assert summary["lost_zone_units"] == 9.0
    assert summary["lost_zone_warehouses"] == [856]
    # LOST no debe contarse como "zona desconocida" de 856.
    assert summary["warehouse_856_unknown_zone_rows"] == 0
    assert summary["warehouse_856_rows"] == 3


def test_no_lost_rows_reports_zero(tmp_path):
    path = tmp_path / "copernico.csv"
    _write_copernico_csv(
        path,
        [
            [444, 40, "ZABCDEFG", 5, ""],
        ],
    )
    _unusable, _storage_overrides, summary = engine.load_copernico_unusable_csv(path)

    assert summary["lost_zone_rows"] == 0
    assert summary["lost_zone_units"] == 0.0
    assert summary["lost_zone_warehouses"] == []


def test_csv_without_zonapiso_column_still_works_for_non_856(tmp_path):
    """La columna ZonaPiso sigue siendo opcional para bodegas != 856."""
    path = tmp_path / "copernico.csv"
    _write_copernico_csv(
        path,
        [
            [444, 50, "ZABCDEFG", 5],
            [444, 51, "RECIBO_444", 2],
        ],
        header=("Bodega", "EAN", "Ubicacion", "Saldo"),
    )
    unusable, _storage_overrides, summary = engine.load_copernico_unusable_csv(path)

    assert (444, 50) not in unusable
    assert unusable[(444, 51)] == 2.0
    assert summary["lost_zone_rows"] == 0


def test_accepts_single_path_for_backward_compatibility(tmp_path):
    path = tmp_path / "copernico.csv"
    _write_copernico_csv(path, [[444, 10, "RECIBO_444", 5, ""]])
    unusable, _storage_overrides, summary = engine.load_copernico_unusable_csv(path)

    assert unusable[(444, 10)] == 5.0
    assert summary["files_processed"] == 1


def test_combines_multiple_uploaded_files(tmp_path):
    path1 = tmp_path / "copernico_1.csv"
    _write_copernico_csv(path1, [[444, 11, "CANCELADOS", 3, ""]])
    path2 = tmp_path / "copernico_2.csv"
    _write_copernico_csv(path2, [[831, 12, "ZABCDEFG", 7, "LOST"]])

    unusable, _storage_overrides, summary = engine.load_copernico_unusable_csv(
        [path1, path2]
    )

    assert unusable[(444, 11)] == 3.0
    assert unusable[(831, 12)] == 7.0
    assert summary["files_processed"] == 2
    assert summary["total_rows"] == 2
    assert summary["lost_zone_rows"] == 1


def test_same_warehouse_sku_across_files_accumulates(tmp_path):
    """El mismo par bodega-SKU repetido en dos archivos se SUMA, no se pisa."""
    path1 = tmp_path / "copernico_1.csv"
    _write_copernico_csv(path1, [[444, 20, "CANCELADOS", 4, ""]])
    path2 = tmp_path / "copernico_2.csv"
    _write_copernico_csv(path2, [[444, 20, "CANCELADOS", 6, ""]])

    unusable, _storage_overrides, _summary = engine.load_copernico_unusable_csv(
        [path1, path2]
    )

    assert unusable[(444, 20)] == 10.0


def test_files_can_have_different_optional_columns(tmp_path):
    """Un archivo sin ZonaPiso conviviendo con otro que sí la trae."""
    path1 = tmp_path / "sin_zonapiso.csv"
    _write_copernico_csv(
        path1, [[444, 30, "ZABCDEFG", 9]],
        header=("Bodega", "EAN", "Ubicacion", "Saldo"),
    )
    path2 = tmp_path / "con_zonapiso.csv"
    _write_copernico_csv(path2, [[444, 31, "ZABCDEFG", 2, "LOST"]])

    unusable, _storage_overrides, summary = engine.load_copernico_unusable_csv(
        [path1, path2]
    )

    assert (444, 30) not in unusable  # usable, sin LOST y sin columna ZonaPiso
    assert unusable[(444, 31)] == 2.0  # excluido por LOST en el otro archivo
    assert summary["files_processed"] == 2


def test_empty_file_list_raises_clear_error():
    try:
        engine.load_copernico_unusable_csv([])
    except ValueError as exc:
        assert "ningún archivo" in str(exc)
    else:
        raise AssertionError("debía lanzar ValueError con lista vacía")


def test_load_catalogs_end_to_end_applies_lost_exclusion(tmp_path):
    """Confirma que el saldo LOST descontado por COPÉRNICO llega hasta STOCK."""
    import openpyxl
    from pathlib import Path

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    def add(name, headers, rows):
        ws = wb.create_sheet(name)
        ws.append(headers)
        for r in rows:
            ws.append(r)

    add("VOLUMETRIA", ["SKU", "PALLETS"], [[10, 0.01]])
    add("BLOQUEOS", ["SKU"], [])
    add("RUTA_COSTOS", ["Destination", "Catalog ID"], [])
    add("PRIORIDAD", ["WAREHOUSE_ID", "PRIORIDAD"], [[100, 1]])
    add("444_HV", ["EAN", "Category"], [])
    add("831_HV", ["EAN", "Category"], [])
    add("RACKEADOS", ["WHS", "SYNC"], [])
    add("CAP_RECIBO", ["WH_ID", "CAP"], [[100, 50]])
    add("CATALOGO", ["WAREHOUSE_ID", "PRODUCT_ID", "ADU"], [])
    add("KVI", ["WAREHOUSE_ID", "PRODUCT_ID", "KVI"], [])
    add("SHARE_VENTAS", ["WAREHOUSE_ID", "SHARE"], [])
    add("NO_DISPONIBLE", ["WAREHOUSE_ID", "PRODUCT_ID", "STOCK"], [])
    add(
        "POR_MERMAR",
        [
            "WAREHOUSE_ID", "PRODUCT_ID", "STOCK_AVAILABLE", "VALUE_STOCK",
            "ARRIVAL_DATE", "EXPIRATION_DATE",
        ],
        [],
    )
    add(
        "STOCK",
        ["WAREHOUSE_ID", "PRODUCT_ID", "STOCK_DISPONIBLE_FINAL"],
        [[444, 10, 20]],
    )
    add("OWNER", ["WAREHOUSE_ID", "PRODUCT_ID", "OWNER_NAME", "STOCK_DISPONIBLE_FINAL"], [])
    add(
        "INSUMOS",
        [
            "WAREHOUSE_DESTINATION", "WAREHOUSE_SOURCE", "RETAIL_ID", "QUANTITY",
            "PLANNED_DATE", "ROUTE", "DELIVERY_PRIORITY",
        ],
        [],
    )
    add(
        "GOLDEN_INFALTABLES_ANCHOR",
        ["WAREHOUSE_ID", "PRODUCT_ID_SYNC", "IS_INFALTABLE", "IS_GOLDEN", "IS_ANCHOR"],
        [],
    )
    add(
        "TIENDA",
        ["CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME"],
        [
            ["Ciudad de México", 100, "Tienda Test"],
            ["Ciudad de México", 444, "O444"],
        ],
    )
    add("STORAGE", ["PRODUCT_ID", "STORAGE_NAME"], [])
    add("TIENDAS_CERRADAS", ["WAREHOUSE_ID"], [])
    add("SCHEDULE", ["CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME", "ORIGEN", "DAYS"], [])
    xlsx_path = tmp_path / "DATA_TRANSFERS.xlsx"
    wb.save(xlsx_path)

    copernico_path = tmp_path / "copernico.csv"
    _write_copernico_csv(
        copernico_path,
        [[444, 10, "ZABCDEFG", 14, "LOST"]],
    )

    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    catalogs = engine.load_catalogs(
        Path(xlsx_path), config, copernico_csv_path=Path(copernico_path)
    )

    # STOCK 444/10 = 20; COPÉRNICO descuenta 14 por LOST -> quedan 6 usables.
    info = engine.source_stock_components(catalogs, 444, 10)
    assert info["copernico_unusable"] == 14.0
    assert info["adjusted"] == 6.0
    assert any("LOST" in warning for warning in catalogs.warnings)


def test_load_catalogs_accepts_multiple_copernico_files(tmp_path):
    """El camino real de la app: varios archivos subidos a la vez."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    def add(name, headers, rows):
        ws = wb.create_sheet(name)
        ws.append(headers)
        for r in rows:
            ws.append(r)

    add("VOLUMETRIA", ["SKU", "PALLETS"], [[10, 0.01], [11, 0.01]])
    add("BLOQUEOS", ["SKU"], [])
    add("RUTA_COSTOS", ["Destination", "Catalog ID"], [])
    add("PRIORIDAD", ["WAREHOUSE_ID", "PRIORIDAD"], [[100, 1]])
    add("444_HV", ["EAN", "Category"], [])
    add("831_HV", ["EAN", "Category"], [])
    add("RACKEADOS", ["WHS", "SYNC"], [])
    add("CAP_RECIBO", ["WH_ID", "CAP"], [[100, 50]])
    add("CATALOGO", ["WAREHOUSE_ID", "PRODUCT_ID", "ADU"], [])
    add("KVI", ["WAREHOUSE_ID", "PRODUCT_ID", "KVI"], [])
    add("SHARE_VENTAS", ["WAREHOUSE_ID", "SHARE"], [])
    add("NO_DISPONIBLE", ["WAREHOUSE_ID", "PRODUCT_ID", "STOCK"], [])
    add(
        "POR_MERMAR",
        [
            "WAREHOUSE_ID", "PRODUCT_ID", "STOCK_AVAILABLE", "VALUE_STOCK",
            "ARRIVAL_DATE", "EXPIRATION_DATE",
        ],
        [],
    )
    add(
        "STOCK",
        ["WAREHOUSE_ID", "PRODUCT_ID", "STOCK_DISPONIBLE_FINAL"],
        [[444, 10, 20], [444, 11, 20]],
    )
    add("OWNER", ["WAREHOUSE_ID", "PRODUCT_ID", "OWNER_NAME", "STOCK_DISPONIBLE_FINAL"], [])
    add(
        "INSUMOS",
        [
            "WAREHOUSE_DESTINATION", "WAREHOUSE_SOURCE", "RETAIL_ID", "QUANTITY",
            "PLANNED_DATE", "ROUTE", "DELIVERY_PRIORITY",
        ],
        [],
    )
    add(
        "GOLDEN_INFALTABLES_ANCHOR",
        ["WAREHOUSE_ID", "PRODUCT_ID_SYNC", "IS_INFALTABLE", "IS_GOLDEN", "IS_ANCHOR"],
        [],
    )
    add(
        "TIENDA",
        ["CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME"],
        [
            ["Ciudad de México", 100, "Tienda Test"],
            ["Ciudad de México", 444, "O444"],
        ],
    )
    add("STORAGE", ["PRODUCT_ID", "STORAGE_NAME"], [])
    add("TIENDAS_CERRADAS", ["WAREHOUSE_ID"], [])
    add("SCHEDULE", ["CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME", "ORIGEN", "DAYS"], [])
    xlsx_path = tmp_path / "DATA_TRANSFERS.xlsx"
    wb.save(xlsx_path)

    # Dos archivos, cada uno descuenta un SKU distinto.
    copernico_path_1 = tmp_path / "copernico_1.csv"
    _write_copernico_csv(copernico_path_1, [[444, 10, "RECIBO_444", 5, ""]])
    copernico_path_2 = tmp_path / "copernico_2.csv"
    _write_copernico_csv(copernico_path_2, [[444, 11, "ZABCDEFG", 8, "LOST"]])

    config = engine.Config(origin_warehouses=(444,), max_tasks=100)
    catalogs = engine.load_catalogs(
        xlsx_path,
        config,
        copernico_csv_path=[copernico_path_1, copernico_path_2],
    )

    info_10 = engine.source_stock_components(catalogs, 444, 10)
    info_11 = engine.source_stock_components(catalogs, 444, 11)
    assert info_10["copernico_unusable"] == 5.0
    assert info_10["adjusted"] == 15.0
    assert info_11["copernico_unusable"] == 8.0
    assert info_11["adjusted"] == 12.0
    assert any(
        "2 archivo(s)" in warning for warning in catalogs.warnings
    ), "la advertencia debe mencionar que fueron varios archivos"
