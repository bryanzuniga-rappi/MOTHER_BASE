"""Fixture de punta a punta: arma un DATA_TRANSFERS.xlsx y un Bulk de Fountain9
sintéticos y ejecuta execute_planning completo.
"""

import io
import zipfile
from datetime import date

import openpyxl

ALL_DAYS = "LUNES,MARTES,MIERCOLES,JUEVES,VIERNES,SABADO,DOMINGO"

EMPTY_SHEETS = {
    "VOLUMETRIA": ["SKU", "PALLETS"],
    "BLOQUEOS_FORANEAS": ["SKU"],
    "BLOQUEOS": ["PRODUCT_ID"],
    "RUTA_COSTOS": ["Destination", "Catalog ID"],
    "PRIORIDAD": ["WAREHOUSE_ID", "PRIORIDAD"],
    "444_HV": ["EAN", "Category"],
    "831_HV": ["EAN", "Category"],
    "RACKEADOS": ["WHS", "SYNC"],
    "CAP_RECIBO": ["WH_ID", "CAP"],
    "KVI": ["WAREHOUSE_ID", "PRODUCT_ID", "KVI"],
    "SHARE_VENTAS": ["WAREHOUSE_ID", "SHARE"],
    "NO_DISPONIBLE": ["WAREHOUSE_ID", "PRODUCT_ID", "STOCK"],
    "POR_MERMAR": [
        "WAREHOUSE_ID", "PRODUCT_ID", "STOCK_AVAILABLE", "VALUE_STOCK",
        "ARRIVAL_DATE", "EXPIRATION_DATE",
    ],
    "OWNER": ["WAREHOUSE_ID", "PRODUCT_ID", "OWNER_NAME", "STOCK_DISPONIBLE_FINAL"],
    "INSUMOS": [
        "WAREHOUSE_DESTINATION", "WAREHOUSE_SOURCE", "RETAIL_ID", "QUANTITY",
        "PLANNED_DATE", "ROUTE", "DELIVERY_PRIORITY",
    ],
    "GOLDEN_INFALTABLES_ANCHOR": [
        "WAREHOUSE_ID", "PRODUCT_ID_SYNC", "IS_INFALTABLE", "IS_GOLDEN", "IS_ANCHOR",
    ],
    "STORAGE": ["PRODUCT_ID", "STORAGE_NAME"],
    "TIENDAS_CERRADAS": ["WAREHOUSE_ID"],
}

PLAN_HEADERS = [
    "Warehouseid", "SKU ID", "Current Inventory",
    "Predicted Demand for selected duration", "Predicted Opening Inventory",
    "Replenishment Quantity for Plan Duration (MOV)", "Net Inter-Store Transfers",
    "Duration", "Primary Source Lead Time (Days)",
]


def build_workbook_bytes(
    stores: dict[int, str],          # store_id -> city
    skus: list[int],
    schedule_only_stores: set[int] = frozenset(),
    origin: int = 444,
    origin_stock: float = 100000.0,
    destination_stock: dict[tuple[int, int], float] | None = None,
    adu: float = 1.0,
    incoming: dict[tuple[int, int], float] | None = None,
    incoming_column: str | None = "INCOMING_TR",
    omit_stock_rows: set[tuple[int, int]] = frozenset(),
    extra_rows: dict[str, list[tuple]] | None = None,
    categories: dict[int, str] | None = None,
    catalog_adu: dict[tuple[int, int], float] | None = None,
    swa_values: dict[tuple[int, int], float] | None = None,
) -> bytes:
    """``extra_rows``: filas para hojas que por defecto van vacías (p. ej.
    CAP_RECIBO, BLOQUEOS, KVI, POR_MERMAR). ``categories``: CATEGORY_NAME por SKU."""
    destination_stock = destination_stock or {}
    wb = openpyxl.Workbook(write_only=True)

    def sheet(name, headers, rows=()):
        ws = wb.create_sheet(name)
        ws.append(headers)
        for row in rows:
            ws.append(list(row))

    extra_rows = extra_rows or {}
    categories = categories or {}
    catalog_adu = catalog_adu or {}
    for name, headers in EMPTY_SHEETS.items():
        sheet(name, headers, extra_rows.get(name, ()))
    all_stores = {origin: "CDMX", **stores}
    sheet(
        "TIENDA", ["CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME"],
        ((city, store, f"S{store}") for store, city in all_stores.items()),
    )
    sheet(
        "CATALOGO", ["WAREHOUSE_ID", "PRODUCT_ID", "ADU"],
        ((store, sku, catalog_adu.get((store, sku), adu)) for store in stores for sku in skus),
    )
    incoming = incoming or {}
    stock_rows = [(origin, sku, origin_stock) for sku in skus]
    stock_rows += (
        (store, sku, destination_stock.get((store, sku), 0.0))
        for store in stores for sku in skus
        if (store, sku) not in omit_stock_rows
    )
    stock_headers = ["WAREHOUSE_ID", "PRODUCT_ID", "STOCK_DISPONIBLE_FINAL"]
    if incoming_column:
        stock_headers.append(incoming_column)
        stock_rows = [
            (*row, incoming.get((row[0], row[1]), 0.0)) for row in stock_rows
        ]
    sheet("STOCK", stock_headers, stock_rows)
    sheet(
        "SCHEDULE", ["CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME", "ORIGEN", "DAYS"],
        ((stores[s], s, f"S{s}", origin, ALL_DAYS) for s in schedule_only_stores),
    )
    sheet("DATA", ["SYNC_ID", "PRODUCT_NAME", "MACROCATEGORY_NAME",
                   "CATEGORY_NAME", "SUBCATEGORY_NAME"],
          ((sku, f"PRODUCTO {sku}", "M", categories.get(sku, "C"), "S") for sku in skus))
    sheet("SWA", ["WAREHOUSE_ID", "PRODUCT_ID", "SWA_POTENTIAL_GAIN_COUNTRY"],
          (((store, sku, value) for (store, sku), value in swa_values.items())
           if swa_values is not None
           else ((store, sku, 0.01) for store in stores for sku in skus[:1])))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_plan_csv_bytes(rows: list[tuple], extra_mov_column: str | None = None) -> bytes:
    """Filas: (tienda, sku, mov) o (tienda, sku, mov, demanda, opening, net_transfer).
    ``extra_mov_column``: nombre de una columna MOV opcional; su valor es el
    séptimo elemento de la fila (o 0)."""
    headers = list(PLAN_HEADERS) + ([extra_mov_column] if extra_mov_column else [])
    lines = [",".join(headers)]
    for row in rows:
        store, sku, mov = row[:3]
        demand, opening, net = (row[3:6] if len(row) >= 6 else (mov, 0, 0))
        extra = f",{row[6] if len(row) > 6 else 0}" if extra_mov_column else ""
        lines.append(f"{store},{sku},0,{demand},{opening},{mov},{net},5,3{extra}")
    return ("\n".join(lines) + "\n").encode("utf-8")


class FakeUpload(io.BytesIO):
    def __init__(self, name: str, data: bytes):
        super().__init__(data)
        self.name = name
        self.size = len(data)          # st.file_uploader expone .size


def read_zip_names(zip_path) -> list[str]:
    with zipfile.ZipFile(zip_path) as archive:
        return archive.namelist()
