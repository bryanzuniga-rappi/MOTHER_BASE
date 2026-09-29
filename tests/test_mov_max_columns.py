"""Pruebas del nuevo cálculo de MOV efectivo: máximo entre la columna (MOV)
y hasta 11 columnas relacionadas opcionales de Fountain9, y máximo (no
suma) entre filas/archivos duplicados de la misma tienda-SKU."""

import csv
from pathlib import Path

import modelo_abasto as engine
from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


def make_catalogs(**overrides) -> engine.Catalogs:
    base = dict(
        volume_m3={}, blocked_products=set(), route_cost_blocks=set(),
        store_priority={}, high_value={}, rackeados_444=set(),
        store_capacity={}, copernico_unusable_444={}, unavailable_stock={},
        stock_base={}, golden_infaltables=set(), stores={}, storage={},
        warnings=[],
    )
    base.update(overrides)
    return engine.Catalogs(**base)


CONFIG = engine.Config(origin_warehouses=(444,), max_tasks=100)


def _write_plan_csv(path: Path, headers: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)


def _read_consolidated(output_path: Path) -> dict:
    with output_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return {(int(r["Warehouseid"]), int(r["SKU ID"])): r for r in rows}


def test_mov_max_takes_maximum_of_available_columns(tmp_path):
    plan_path = tmp_path / "plan.csv"
    _write_plan_csv(
        plan_path,
        [
            "Warehouseid", "SKU ID", "Predicted Demand for selected duration",
            "Predicted Opening Inventory",
            "Replenishment Quantity for Plan Duration (MOV)",
            "Replenishment Quantity for Plan Duration (MOQ)",
            "Replenishment Quantity for Plan Duration (Batch Size Rounded)",
            "Net Inter-Store Transfers",
        ],
        [[100, 10, "0", "0", "5", "8", "3", "0"]],
    )
    catalogs = make_catalogs()
    output_path = tmp_path / "canonical.csv"
    _, consolidated, _ = m.consolidate_plan_files(
        [plan_path], catalogs, CONFIG, output_path
    )
    # MOV=5, MOQ=8, Batch=3 -> el máximo es 8, no la suma (16) ni solo MOV (5).
    assert consolidated[(100, 10)]["ROQ_INPUT"] == 8.0

    canonical = _read_consolidated(output_path)
    assert float(canonical[(100, 10)]["Replenishment Quantity for Plan Duration (MOV)"]) == 8.0


def test_mov_max_works_with_only_required_mov_column(tmp_path):
    """Las 11 columnas opcionales no deben ser obligatorias — un archivo
    que solo trae MOV debe seguir funcionando igual que antes."""
    plan_path = tmp_path / "plan.csv"
    _write_plan_csv(
        plan_path,
        [
            "Warehouseid", "SKU ID", "Predicted Demand for selected duration",
            "Predicted Opening Inventory",
            "Replenishment Quantity for Plan Duration (MOV)",
            "Net Inter-Store Transfers",
        ],
        [[100, 10, "0", "0", "7", "0"]],
    )
    catalogs = make_catalogs()
    output_path = tmp_path / "canonical.csv"
    _, consolidated, _ = m.consolidate_plan_files(
        [plan_path], catalogs, CONFIG, output_path
    )
    assert consolidated[(100, 10)]["ROQ_INPUT"] == 7.0


def test_mov_max_duplicate_rows_take_max_not_sum(tmp_path):
    """Punto central de esta sesión: la misma tienda-SKU en dos filas
    (o archivos) distintos debe quedarse con el MÁXIMO, nunca la suma."""
    plan_path = tmp_path / "plan.csv"
    _write_plan_csv(
        plan_path,
        [
            "Warehouseid", "SKU ID", "Predicted Demand for selected duration",
            "Predicted Opening Inventory",
            "Replenishment Quantity for Plan Duration (MOV)",
            "Net Inter-Store Transfers",
        ],
        [
            [100, 10, "0", "0", "5", "0"],
            [100, 10, "0", "0", "12", "0"],
        ],
    )
    catalogs = make_catalogs()
    output_path = tmp_path / "canonical.csv"
    _, consolidated, _ = m.consolidate_plan_files(
        [plan_path], catalogs, CONFIG, output_path
    )
    # Si fuera suma, sería 17. Debe ser 12 (el máximo).
    assert consolidated[(100, 10)]["ROQ_INPUT"] == 12.0


def test_mov_max_duplicate_across_two_files_takes_max(tmp_path):
    plan_path_1 = tmp_path / "plan1.csv"
    plan_path_2 = tmp_path / "plan2.csv"
    headers = [
        "Warehouseid", "SKU ID", "Predicted Demand for selected duration",
        "Predicted Opening Inventory",
        "Replenishment Quantity for Plan Duration (MOV)",
        "Net Inter-Store Transfers",
    ]
    _write_plan_csv(plan_path_1, headers, [[100, 10, "0", "0", "20", "0"]])
    _write_plan_csv(plan_path_2, headers, [[100, 10, "0", "0", "6", "0"]])
    catalogs = make_catalogs()
    output_path = tmp_path / "canonical.csv"
    _, consolidated, _ = m.consolidate_plan_files(
        [plan_path_1, plan_path_2], catalogs, CONFIG, output_path
    )
    assert consolidated[(100, 10)]["ROQ_INPUT"] == 20.0


def test_mov_max_other_accumulated_fields_still_sum(tmp_path):
    """Demanda, opening y net transfer NO cambiaron — siguen sumándose
    entre filas duplicadas, solo el MOV efectivo pasó a máximo."""
    plan_path = tmp_path / "plan.csv"
    _write_plan_csv(
        plan_path,
        [
            "Warehouseid", "SKU ID", "Predicted Demand for selected duration",
            "Predicted Opening Inventory",
            "Replenishment Quantity for Plan Duration (MOV)",
            "Net Inter-Store Transfers",
        ],
        [
            [100, 10, "3", "2", "5", "1"],
            [100, 10, "4", "1", "9", "2"],
        ],
    )
    catalogs = make_catalogs()
    output_path = tmp_path / "canonical.csv"
    _, consolidated, _ = m.consolidate_plan_files(
        [plan_path], catalogs, CONFIG, output_path
    )
    record = consolidated[(100, 10)]
    assert record["PREDICTED_DEMAND"] == 7.0  # 3+4, sigue sumando
    assert record["PREDICTED_OPENING_INVENTORY"] == 3.0  # 2+1, sigue sumando
    assert record["NET_INTER_STORE_TRANSFERS"] == 3.0  # 1+2, sigue sumando
    assert record["ROQ_INPUT"] == 9.0  # max(5,9), ya no suma


def test_mov_max_all_twelve_columns_present(tmp_path):
    """Con las 12 columnas presentes, toma el máximo real entre todas."""
    headers = [
        "Warehouseid", "SKU ID", "Predicted Demand for selected duration",
        "Predicted Opening Inventory",
        "Replenishment Quantity for Plan Duration (Batch Size Rounded)",
        "Replenishment Quantity for Plan Duration (MOQ)",
        "Replenishment Quantity for Plan Duration (MOV)",
        "Replenishment Quantity for Plan Duration (Initial Allocation)",
        "Replenishment Quantity for Plan Duration (Max Cap. Adj.)",
        "Replenishment Quantity for Plan Duration (Max Cap. Adj.) (Batch Size Rounded)",
        "Replenishment Quantity for Plan Duration (Max Cap. Adj.) (MOQ)",
        "Replenishment Quantity for Plan Duration Diff.",
        "Allocation Quantity for Plan Duration",
        "Replenishment(Allocation) Quantity for Plan Duration Editable",
        "Allocation (Store Based)",
        "Allocation (DOI Based)",
        "Net Inter-Store Transfers",
    ]
    values = ["1", "2", "3", "4", "5", "6", "7", "8", "99", "10", "11", "0"]
    plan_path = tmp_path / "plan.csv"
    _write_plan_csv(plan_path, headers, [[100, 10, "0", "0", *values]])
    catalogs = make_catalogs()
    output_path = tmp_path / "canonical.csv"
    _, consolidated, _ = m.consolidate_plan_files(
        [plan_path], catalogs, CONFIG, output_path
    )
    assert consolidated[(100, 10)]["ROQ_INPUT"] == 99.0


def test_mov_column_still_strictly_required(tmp_path):
    """(MOV) sigue siendo obligatoria — sin ella, el archivo se rechaza,
    aunque traiga varias de las 11 opcionales."""
    plan_path = tmp_path / "plan.csv"
    _write_plan_csv(
        plan_path,
        [
            "Warehouseid", "SKU ID", "Predicted Demand for selected duration",
            "Predicted Opening Inventory",
            "Replenishment Quantity for Plan Duration (MOQ)",
            "Net Inter-Store Transfers",
        ],
        [[100, 10, "0", "0", "8", "0"]],
    )
    catalogs = make_catalogs()
    output_path = tmp_path / "canonical.csv"
    try:
        m.consolidate_plan_files([plan_path], catalogs, CONFIG, output_path)
    except ValueError as exc:
        assert "MOV" in str(exc)
    else:
        raise AssertionError("Debía rechazar el archivo sin la columna (MOV)")
