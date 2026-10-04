"""Fixture de punta a punta: arma un DATA_TRANSFERS.xlsx y un Bulk de
Fountain9 sintéticos y ejecuta execute_planning completo. Sirve para el test
de regresión (datos mínimos) y para medir escala (muchas tiendas/SKUs)."""

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
) -> bytes:
    destination_stock = destination_stock or {}
    wb = openpyxl.Workbook(write_only=True)

    def sheet(name, headers, rows=()):
        ws = wb.create_sheet(name)
        ws.append(headers)
        for row in rows:
            ws.append(list(row))

    for name, headers in EMPTY_SHEETS.items():
        sheet(name, headers)
    all_stores = {origin: "CDMX", **stores}
    sheet(
        "TIENDA", ["CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME"],
        ((city, store, f"S{store}") for store, city in all_stores.items()),
    )
    sheet(
        "CATALOGO", ["WAREHOUSE_ID", "PRODUCT_ID", "ADU"],
        ((store, sku, adu) for store in stores for sku in skus),
    )
    stock_rows = [(origin, sku, origin_stock) for sku in skus]
    stock_rows += (
        (store, sku, destination_stock.get((store, sku), 0.0))
        for store in stores for sku in skus
    )
    sheet("STOCK", ["WAREHOUSE_ID", "PRODUCT_ID", "STOCK_DISPONIBLE_FINAL"], stock_rows)
    sheet(
        "SCHEDULE", ["CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME", "ORIGEN", "DAYS"],
        ((stores[s], s, f"S{s}", origin, ALL_DAYS) for s in schedule_only_stores),
    )
    sheet("DATA", ["SYNC_ID", "PRODUCT_NAME", "MACROCATEGORY_NAME",
                   "CATEGORY_NAME", "SUBCATEGORY_NAME"],
          ((sku, f"PRODUCTO {sku}", "M", "C", "S") for sku in skus))
    sheet("SWA", ["WAREHOUSE_ID", "PRODUCT_ID", "SWA_POTENTIAL_GAIN_COUNTRY"],
          ((store, sku, 0.01) for store in stores for sku in skus[:1]))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_plan_csv_bytes(rows: list[tuple]) -> bytes:
    """rows: (store, sku, mov)."""
    lines = [",".join(PLAN_HEADERS)]
    for store, sku, mov in rows:
        lines.append(f"{store},{sku},0,{mov},0,{mov},0,5,3")
    return ("\n".join(lines) + "\n").encode("utf-8")


class FakeUpload(io.BytesIO):
    def __init__(self, name: str, data: bytes):
        super().__init__(data)
        self.name = name


def read_zip_names(zip_path) -> list[str]:
    with zipfile.ZipFile(zip_path) as archive:
        return archive.namelist()
