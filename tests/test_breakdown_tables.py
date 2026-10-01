"""Pruebas del breakdown de 3 tablas:

1. build_planned_by_engine_rows — lo efectivamente planeado, por engine y
   causal.
2. build_cuts_detail_rows — todo lo que no se mandó, con motivo específico
   (incluye los sub-motivos de COPÉRNICO).
3. ordered_breakdown_rows — el overview general (ya existía, sin cambios).
"""

from collections import Counter
from types import SimpleNamespace

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


def _row(destination, sku, objetivo, asignado, tipo, regla="MOV_MINIMO_3"):
    return {
        "WAREHOUSE_DESTINATION": destination,
        "RETAIL_ID": sku,
        "CANTIDAD_OBJETIVO": objetivo,
        "CANTIDAD_ASIGNADA": asignado,
        "TIPO_DE_CORTE": tipo,
        "REGLA_DEMANDA": regla,
    }


# --- attribute_engine -----------------------------------------------------

def test_attribute_engine_naked_default():
    assert m.attribute_engine("OK") == "Naked"
    assert m.attribute_engine("CORTE POR STOCK") == "Naked"
    assert m.attribute_engine("CORTE POR COPÉRNICO CANCELADOS") == "Naked"


def test_hardcode_cases_get_their_own_distinct_tipo_de_corte():
    """Los 3 motivos reales de hardcode (antes todos caían juntos bajo "OK
    MANUAL POR FORECAST 0") deben quedar separados, cada uno con su propia
    etiqueta precisa."""
    expectations = {
        "HARDCODE_4_CERO_TOTAL": "OK MANUAL POR FORECAST Y STOCK EN CERO",
        "HARDCODE_3_INVENTARIO_MENOR_DEMANDA": (
            "OK MANUAL POR INVENTARIO MENOR A DEMANDA"
        ),
        "HARDCODE_3_NET_TRANSFER_BAJO": "OK MANUAL POR NET TRANSFER BAJO",
    }
    for regla, expected_label in expectations.items():
        result = SimpleNamespace(
            base_rows=[
                {
                    "TIPO_DE_CORTE": "OK",
                    "REGLA_DEMANDA": regla,
                    "CANTIDAD_ASIGNADA": 3,
                    "CANTIDAD_OBJETIVO": 3,
                }
            ]
        )
        m.apply_reporting_labels(result)
        assert result.base_rows[0]["TIPO_DE_CORTE"] == expected_label, regla


def test_genuine_fountain9_recommendation_unaffected_by_hardcode_split():
    """Una recomendación real de Fountain9 (REGLA_DEMANDA no es ninguno de
    los 3 hardcodes) debe seguir etiquetándose igual que siempre."""
    result = SimpleNamespace(
        base_rows=[
            {
                "TIPO_DE_CORTE": "OK",
                "REGLA_DEMANDA": "MOV_MINIMO_3",
                "CANTIDAD_ASIGNADA": 5,
                "CANTIDAD_OBJETIVO": 5,
            }
        ]
    )
    m.apply_reporting_labels(result)
    assert result.base_rows[0]["TIPO_DE_CORTE"] == "OK COMPLETO POR FOUNTAIN9"


def test_hardcode_labels_registered_in_breakdown_order():
    for label in (
        "OK MANUAL POR FORECAST Y STOCK EN CERO",
        "OK MANUAL POR INVENTARIO MENOR A DEMANDA",
        "OK MANUAL POR NET TRANSFER BAJO",
    ):
        assert label in m.BREAKDOWN_ORDER


def test_no_fountain9_coverage_sorted_before_shalashaska():
    """Regresión: otro gap de la sesión anterior — 'Cobertura sin
    Fountain9' faltaba en el orden de despliegue de esta tabla, lo que la
    mandaba al final en vez de a su lugar real en la secuencia del
    pipeline (justo después de Refuerzo, antes de Shalashaska)."""
    result = SimpleNamespace(
        base_rows=[
            {
                "TIPO_DE_CORTE": m.SHALASHASKA_CUT,
                "CANTIDAD_ASIGNADA": 1,
                "CANTIDAD_OBJETIVO": 1,
            },
            {
                "TIPO_DE_CORTE": m.NO_FOUNTAIN9_CUT,
                "CANTIDAD_ASIGNADA": 1,
                "CANTIDAD_OBJETIVO": 1,
            },
        ]
    )
    rows = m.build_planned_by_engine_rows(result)
    engines_in_order = [row["ENGINE"] for row in rows]
    assert engines_in_order.index("Cobertura sin Fountain9") < engines_in_order.index(
        "Shalashaska"
    )


def test_attribute_engine_known_add_on_engines():
    assert m.attribute_engine("ENVIADOS PARA CUBRIR AVL") == "AVL"
    assert m.attribute_engine("ENVIADOS PARA PREVENIR QUIEBRE") == "Preventivo"
    assert m.attribute_engine(m.SPECIAL_DOH_CUT) == "Refuerzo Golden/Infaltable/Anchor"
    assert m.attribute_engine(m.SHALASHASKA_CUT) == "Shalashaska"
    assert m.attribute_engine(m.LIQUID_CUT) == "Liquid"
    assert m.attribute_engine(m.VENOM_CUT) == "Venom"


# --- build_planned_by_engine_rows -----------------------------------------

def test_planned_by_engine_only_includes_assigned_rows():
    result = SimpleNamespace(
        base_rows=[
            _row(100, 10, 10, 10, "OK"),
            _row(100, 11, 5, 0, "CORTE POR STOCK"),  # sin asignar: no cuenta
            _row(100, 12, 8, 8, "ENVIADOS PARA CUBRIR AVL", regla="AVL_DOH"),
        ],
        allocation_rows=[],
    )
    rows = m.build_planned_by_engine_rows(result)
    engines = {row["ENGINE"] for row in rows}
    assert engines == {"Naked", "AVL"}
    naked_row = next(r for r in rows if r["ENGINE"] == "Naked")
    assert naked_row["CASOS"] == 1
    assert naked_row["UNIDADES"] == 10
    avl_row = next(r for r in rows if r["ENGINE"] == "AVL")
    assert avl_row["CASOS"] == 1
    assert avl_row["UNIDADES"] == 8


def test_planned_by_engine_groups_multiple_causales_within_same_engine():
    result = SimpleNamespace(
        base_rows=[
            _row(100, 10, 10, 10, "OK"),
            _row(100, 11, 10, 10, "OK"),
            _row(100, 12, 10, 6, "OK PARCIAL - CORTE POR STOCK"),
        ],
        allocation_rows=[],
    )
    rows = m.build_planned_by_engine_rows(result)
    causales = {(row["ENGINE"], row["CAUSAL"]): row["CASOS"] for row in rows}
    assert causales[("Naked", "OK")] == 2
    assert causales[("Naked", "OK PARCIAL - CORTE POR STOCK")] == 1


def test_planned_by_engine_includes_insumos_when_summary_given():
    result = SimpleNamespace(base_rows=[], allocation_rows=[])
    insumos_summary = {"lines_added": 12, "units_added": 4200}
    rows = m.build_planned_by_engine_rows(result, insumos_summary)
    assert len(rows) == 1
    assert rows[0]["ENGINE"] == "Insumos"
    assert rows[0]["CASOS"] == 12
    assert rows[0]["UNIDADES"] == 4200


def test_planned_by_engine_skips_insumos_when_nothing_added():
    result = SimpleNamespace(base_rows=[], allocation_rows=[])
    rows = m.build_planned_by_engine_rows(result, {"lines_added": 0, "units_added": 0})
    assert rows == []


# --- build_cuts_detail_rows ------------------------------------------------

def test_cuts_detail_only_includes_unassigned_rows():
    result = SimpleNamespace(
        base_rows=[
            _row(100, 10, 10, 10, "OK"),  # asignado: no cuenta como corte
            _row(100, 11, 5, 0, "CORTE POR STOCK"),
            _row(100, 12, 8, 0, "CORTE POR COPÉRNICO CANCELADOS"),
        ],
        allocation_rows=[],
    )
    rows = m.build_cuts_detail_rows(result)
    causales = {row["CAUSAL"]: row for row in rows}
    assert "OK" not in causales
    assert causales["CORTE POR STOCK"]["CASOS"] == 1
    assert causales["CORTE POR STOCK"]["UNIDADES_SIN_CUBRIR"] == 5
    assert causales["CORTE POR COPÉRNICO CANCELADOS"]["CASOS"] == 1
    assert causales["CORTE POR COPÉRNICO CANCELADOS"]["UNIDADES_SIN_CUBRIR"] == 8


def test_cuts_detail_separates_copernico_sub_reasons():
    """El punto central del pedido: LOST, CANCELADOS y RECIBO deben verse
    como filas DISTINTAS, no colapsadas en un solo bucket genérico."""
    result = SimpleNamespace(
        base_rows=[
            _row(100, 10, 5, 0, "CORTE POR COPÉRNICO LOST"),
            _row(100, 11, 3, 0, "CORTE POR COPÉRNICO CANCELADOS"),
            _row(100, 12, 4, 0, "CORTE POR COPÉRNICO RECIBO"),
            _row(100, 13, 6, 0, "CORTE POR STOCK"),  # sin COPÉRNICO de por medio
        ],
        allocation_rows=[],
    )
    rows = m.build_cuts_detail_rows(result)
    causales = {row["CAUSAL"] for row in rows}
    assert "CORTE POR COPÉRNICO LOST" in causales
    assert "CORTE POR COPÉRNICO CANCELADOS" in causales
    assert "CORTE POR COPÉRNICO RECIBO" in causales
    assert "CORTE POR STOCK" in causales
    # 4 causales distintas, ninguna se mezcló con otra.
    assert len(rows) == 4


def test_cuts_detail_includes_closed_stores_and_blocked_cities():
    result = SimpleNamespace(base_rows=[], allocation_rows=[])
    closed_summary = {"requirements": 7, "target_units": 21}
    block_summary = {"requirements": 3, "target_units": 9}
    rows = m.build_cuts_detail_rows(result, closed_summary, block_summary)
    causales = {row["CAUSAL"]: row for row in rows}
    assert causales["CORTE POR TIENDA CERRADA"]["CASOS"] == 7
    assert causales["CORTE POR TIENDA CERRADA"]["UNIDADES_SIN_CUBRIR"] == 21
    assert causales["CORTE POR CIUDAD BLOQUEADA"]["CASOS"] == 3
    assert causales["CORTE POR CIUDAD BLOQUEADA"]["UNIDADES_SIN_CUBRIR"] == 9


def test_cuts_detail_skips_closed_stores_when_zero():
    result = SimpleNamespace(base_rows=[], allocation_rows=[])
    rows = m.build_cuts_detail_rows(result, {"requirements": 0}, {"requirements": 0})
    assert rows == []


# --- consistencia entre las 3 tablas ---------------------------------------

def test_planned_and_cuts_tables_partition_all_assigned_vs_unassigned():
    """Todo caso de base_rows debe caer en EXACTAMENTE una de las dos tablas
    (planeado o corte), nunca en ambas ni en ninguna."""
    result = SimpleNamespace(
        base_rows=[
            _row(100, 10, 10, 10, "OK"),
            _row(100, 11, 10, 4, "OK PARCIAL - CORTE POR STOCK"),
            _row(100, 12, 5, 0, "CORTE POR STOCK"),
        ],
        allocation_rows=[],
    )
    planned = m.build_planned_by_engine_rows(result)
    cuts = m.build_cuts_detail_rows(result)
    total_planned_casos = sum(row["CASOS"] for row in planned)
    total_cut_casos = sum(row["CASOS"] for row in cuts)
    assert total_planned_casos == 2  # SKU 10 y 11 tienen algo asignado
    assert total_cut_casos == 1  # SKU 12 no tiene nada asignado
    assert total_planned_casos + total_cut_casos == len(result.base_rows)


# --- SIN RECOMENDACIÓN: breakdown aparte, por motivo -----------------------

def _no_rec_row(destination, sku, demand, opening, net_transfer=0.0):
    return {
        "WAREHOUSE_DESTINATION": destination,
        "RETAIL_ID": sku,
        "CANTIDAD_OBJETIVO": 0,
        "CANTIDAD_ASIGNADA": 0,
        "TIPO_DE_CORTE": "SIN RECOMENDACIÓN",
        "REGLA_DEMANDA": "SIN_RECOMENDACION",
        "PREDICTED_DEMAND": demand,
        "PREDICTED_OPENING_INVENTORY": opening,
        "NET_INTER_STORE_TRANSFERS": net_transfer,
    }


def test_classify_zero_demand():
    row = _no_rec_row(100, 10, demand=0, opening=5)
    assert m.classify_no_recommendation_reason(row) == "SIN DEMANDA PROYECTADA"


def test_classify_transfer_covers_need():
    row = _no_rec_row(100, 10, demand=10, opening=2, net_transfer=15)
    assert (
        m.classify_no_recommendation_reason(row)
        == "TRANSFERENCIA ENTRE TIENDAS CUBRE LA NECESIDAD"
    )


def test_classify_ample_margin():
    row = _no_rec_row(100, 10, demand=10, opening=25, net_transfer=0)
    assert m.classify_no_recommendation_reason(row) == "INVENTARIO CON AMPLIO MARGEN"


def test_classify_tight_margin():
    row = _no_rec_row(100, 10, demand=10, opening=12, net_transfer=0)
    assert (
        m.classify_no_recommendation_reason(row)
        == "INVENTARIO SUFICIENTE CON MARGEN AJUSTADO"
    )


def test_classify_fallback_when_data_does_not_fit_any_bucket():
    """Caso sintético que viola la invariante esperada (opening < demand,
    sin transferencia) — no debe tronar, debe caer al comodín."""
    row = _no_rec_row(100, 10, demand=10, opening=3, net_transfer=0)
    assert m.classify_no_recommendation_reason(row) == "SIN MOTIVO IDENTIFICADO"


def test_build_no_recommendation_breakdown_counts_correctly():
    result = SimpleNamespace(
        base_rows=[
            _no_rec_row(100, 10, demand=0, opening=5),
            _no_rec_row(100, 11, demand=0, opening=2),
            _no_rec_row(100, 12, demand=10, opening=25),
            _row(100, 13, 5, 5, "OK"),  # no es SIN RECOMENDACIÓN, debe ignorarse
        ],
    )
    rows = m.build_no_recommendation_breakdown(result)
    by_motivo = {r["MOTIVO"]: r["CASOS"] for r in rows}
    assert by_motivo["SIN DEMANDA PROYECTADA"] == 2
    assert by_motivo["INVENTARIO CON AMPLIO MARGEN"] == 1
    assert "OK" not in by_motivo
    assert sum(r["CASOS"] for r in rows) == 3


def test_cuts_detail_no_longer_includes_sin_recomendacion():
    """Punto central de esta sesión: SIN RECOMENDACIÓN debe salir por
    completo de la tabla de cortes general."""
    result = SimpleNamespace(
        base_rows=[
            _no_rec_row(100, 10, demand=0, opening=5),
            _row(100, 11, 5, 0, "CORTE POR STOCK"),
        ],
    )
    cuts = m.build_cuts_detail_rows(result)
    causales = {row["CAUSAL"] for row in cuts}
    assert "SIN RECOMENDACIÓN" not in causales
    assert "CORTE POR STOCK" in causales


def test_overview_breakdown_still_includes_sin_recomendacion():
    """El overview (tabla 3, independiente) NO debe perder SIN
    RECOMENDACIÓN — solo se quitó de la tabla de cortes, no de ahí."""
    status_counts = Counter({"SIN RECOMENDACIÓN": 7, "CORTE POR STOCK": 3})
    rows = m.ordered_breakdown_rows(status_counts)
    breakdown_labels = {row["BREAKDOWN"] for row in rows}
    assert "SIN RECOMENDACIÓN" in breakdown_labels
