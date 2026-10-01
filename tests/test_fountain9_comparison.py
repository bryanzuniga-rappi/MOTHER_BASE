"""Pruebas del reporte comparativo Fountain9 vs Mother Base
(build_fountain9_comparison_report), y de la lectura opcional de
'Allocation (Store Based)' en consolidate_plan_files."""

import csv
from pathlib import Path
from types import SimpleNamespace

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


def _consolidated_record(destination, sku, f9_allocation):
    return (
        (destination, sku),
        {
            "WAREHOUSE_DESTINATION": destination,
            "RETAIL_ID": sku,
            "FOUNTAIN9_ALLOCATION": f9_allocation,
        },
    )


def _alloc_row(destination, sku, quantity):
    return {
        "WAREHOUSE_DESTINATION": destination,
        "RETAIL_ID": sku,
        "QUANTITY": quantity,
    }


# --- build_fountain9_comparison_report ------------------------------------

def test_disabled_when_no_row_has_the_column():
    consolidated = dict(
        [_consolidated_record(100, 10, None), _consolidated_record(100, 11, None)]
    )
    result = SimpleNamespace(allocation_rows=[])
    catalogs = make_catalogs()
    report = m.build_fountain9_comparison_report(result, catalogs, consolidated)
    assert report == {"enabled": False}


def test_basic_counts_both_sides():
    consolidated = dict(
        [
            _consolidated_record(100, 10, 5.0),
            _consolidated_record(100, 11, 0.0),
            _consolidated_record(200, 10, 8.0),
        ]
    )
    result = SimpleNamespace(
        allocation_rows=[
            _alloc_row(100, 10, 3),
            _alloc_row(200, 10, 8),
        ]
    )
    catalogs = make_catalogs(stock_base={(100, 10): 5, (100, 11): 5, (200, 10): 5})
    report = m.build_fountain9_comparison_report(result, catalogs, consolidated)

    assert report["enabled"] is True
    assert report["universo_total"] == 3
    assert report["fountain9"]["productos"] == 1  # sku 10 (sku 11 tiene 0)
    assert report["fountain9"]["tiendas"] == 2  # 100 y 200
    assert report["fountain9"]["piezas"] == 13  # 5+8
    assert report["fountain9"]["tareas"] == 2
    assert report["mother_base_mismo_alcance"]["productos"] == 1
    assert report["mother_base_mismo_alcance"]["tiendas"] == 2
    assert report["mother_base_mismo_alcance"]["piezas"] == 11  # 3+8
    assert report["mother_base_mismo_alcance"]["tareas"] == 2


def test_stockout_coverage_categorization():
    consolidated = dict(
        [
            _consolidated_record(100, 10, 5.0),   # solo F9 cubre
            _consolidated_record(100, 11, 0.0),   # solo MB cubre
            _consolidated_record(100, 12, 4.0),   # ambos cubren
            _consolidated_record(100, 13, 0.0),   # ninguno cubre
        ]
    )
    result = SimpleNamespace(
        allocation_rows=[
            _alloc_row(100, 11, 3),
            _alloc_row(100, 12, 4),
        ]
    )
    # Las 4 combinaciones tienen stock=0 en destino -> las 4 son rupturas.
    catalogs = make_catalogs(
        stock_base={(100, 10): 0, (100, 11): 0, (100, 12): 0, (100, 13): 0}
    )
    report = m.build_fountain9_comparison_report(result, catalogs, consolidated)

    assert report["total_rupturas"] == 4
    assert report["solo_fountain9"] == 1
    assert report["solo_mother_base"] == 1
    assert report["ambos_cubrieron"] == 1
    assert report["ninguno_cubrio"] == 1


def test_only_stockouts_count_toward_coverage_not_full_universe():
    """Una combinación SIN stock=0 no debe contarse en ninguno de los 4
    buckets de cobertura, aunque sí participe en productos/piezas/tareas."""
    consolidated = dict([_consolidated_record(100, 10, 5.0)])
    result = SimpleNamespace(allocation_rows=[])
    catalogs = make_catalogs(stock_base={(100, 10): 50})  # no es ruptura
    report = m.build_fountain9_comparison_report(result, catalogs, consolidated)
    assert report["total_rupturas"] == 0
    assert report["fountain9"]["piezas"] == 5  # sigue contando en piezas


def test_mother_base_adicional_captures_what_fountain9_never_saw():
    """El punto central de esta sesión: Mother Base cubre tienda-SKU que
    Fountain9 nunca evaluó en absoluto (ausentes de 'consolidated') — eso
    debe aparecer en 'mother_base_adicional', separado del cara a cara."""
    consolidated = dict(
        [
            _consolidated_record(100, 10, 5.0),  # Fountain9 SÍ evaluó esto
        ]
    )
    result = SimpleNamespace(
        allocation_rows=[
            _alloc_row(100, 10, 5),   # dentro del alcance de Fountain9
            _alloc_row(200, 99, 7),   # FUERA: Fountain9 nunca vio el sku 99
            _alloc_row(300, 50, 4),   # FUERA: otra tienda-sku que F9 no vio
        ]
    )
    catalogs = make_catalogs()
    report = m.build_fountain9_comparison_report(result, catalogs, consolidated)

    assert report["mother_base_adicional"]["productos"] == 2  # skus 99 y 50
    assert report["mother_base_adicional"]["tiendas"] == 2  # tiendas 200 y 300
    assert report["mother_base_adicional"]["piezas"] == 11  # 7+4
    assert report["mother_base_adicional"]["tareas"] == 2


def test_mother_base_total_equals_mismo_alcance_mas_adicional():
    consolidated = dict([_consolidated_record(100, 10, 5.0)])
    result = SimpleNamespace(
        allocation_rows=[
            _alloc_row(100, 10, 5),
            _alloc_row(200, 99, 7),
        ]
    )
    catalogs = make_catalogs()
    report = m.build_fountain9_comparison_report(result, catalogs, consolidated)

    mismo = report["mother_base_mismo_alcance"]
    adicional = report["mother_base_adicional"]
    total = report["mother_base_total"]
    assert total["piezas"] == mismo["piezas"] + adicional["piezas"]
    assert total["tareas"] == mismo["tareas"] + adicional["tareas"]
    assert total["piezas"] == 12  # 5 + 7
    assert total["tareas"] == 2


def test_mother_base_adicional_empty_when_nothing_outside_scope():
    """Si Mother Base solo asignó dentro de lo que Fountain9 ya vio, el
    bloque adicional debe quedar en ceros, no tronar."""
    consolidated = dict([_consolidated_record(100, 10, 5.0)])
    result = SimpleNamespace(allocation_rows=[_alloc_row(100, 10, 5)])
    catalogs = make_catalogs()
    report = m.build_fountain9_comparison_report(result, catalogs, consolidated)
    assert report["mother_base_adicional"] == {
        "productos": 0, "tiendas": 0, "piezas": 0, "tareas": 0,
    }


# --- lectura opcional de Allocation (Store Based) en consolidate_plan_files

def _write_plan_csv(path: Path, headers: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)


CONFIG = engine.Config(origin_warehouses=(444,), max_tasks=100)


def test_fountain9_allocation_column_read_when_present(tmp_path):
    plan_path = tmp_path / "plan.csv"
    _write_plan_csv(
        plan_path,
        [
            "Warehouseid", "SKU ID", "Predicted Demand for selected duration",
            "Predicted Opening Inventory",
            "Replenishment Quantity for Plan Duration (MOV)",
            "Net Inter-Store Transfers", "Allocation (Store Based)",
        ],
        [[100, 10, "5", "0", "5", "0", "3"]],
    )
    catalogs = make_catalogs()
    output_path = tmp_path / "canonical.csv"
    _, consolidated, _ = m.consolidate_plan_files(
        [plan_path], catalogs, CONFIG, output_path
    )
    assert consolidated[(100, 10)]["FOUNTAIN9_ALLOCATION"] == 3.0


def test_fountain9_allocation_none_when_column_absent(tmp_path):
    plan_path = tmp_path / "plan.csv"
    _write_plan_csv(
        plan_path,
        [
            "Warehouseid", "SKU ID", "Predicted Demand for selected duration",
            "Predicted Opening Inventory",
            "Replenishment Quantity for Plan Duration (MOV)",
            "Net Inter-Store Transfers",
        ],
        [[100, 10, "5", "0", "5", "0"]],
    )
    catalogs = make_catalogs()
    output_path = tmp_path / "canonical.csv"
    _, consolidated, _ = m.consolidate_plan_files(
        [plan_path], catalogs, CONFIG, output_path
    )
    assert consolidated[(100, 10)]["FOUNTAIN9_ALLOCATION"] is None


def test_fountain9_allocation_takes_max_across_duplicate_rows(tmp_path):
    """Mismo criterio que ROQ_INPUT: máximo entre filas duplicadas, nunca
    suma — consistente con cómo tratamos 'la cantidad final de otro
    sistema' en el resto del pipeline."""
    plan_path = tmp_path / "plan.csv"
    _write_plan_csv(
        plan_path,
        [
            "Warehouseid", "SKU ID", "Predicted Demand for selected duration",
            "Predicted Opening Inventory",
            "Replenishment Quantity for Plan Duration (MOV)",
            "Net Inter-Store Transfers", "Allocation (Store Based)",
        ],
        [
            [100, 10, "5", "0", "5", "0", "3"],
            [100, 10, "5", "0", "5", "0", "9"],
        ],
    )
    catalogs = make_catalogs()
    output_path = tmp_path / "canonical.csv"
    _, consolidated, _ = m.consolidate_plan_files(
        [plan_path], catalogs, CONFIG, output_path
    )
    assert consolidated[(100, 10)]["FOUNTAIN9_ALLOCATION"] == 9.0
