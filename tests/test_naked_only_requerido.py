"""Pruebas de las métricas 'Requerido · Naked' en build_planning_analytics.

'Requerido' en Planeación Lista debe reflejar SOLO la necesidad original de
Naked/Solidus (Fountain9 + reglas de mínimo/hardcode), nunca lo que los
engines de cobertura (AVL, Preventivo, Refuerzo especial, Shalashaska,
Liquid, Venom) agregan como su propio objetivo.
"""

from types import SimpleNamespace

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


def _naked_row(destination, sku, objetivo, asignado, m3_objetivo, regla="MOV_MINIMO_3"):
    return {
        "WAREHOUSE_DESTINATION": destination,
        "RETAIL_ID": sku,
        "CANTIDAD_OBJETIVO": objetivo,
        "CANTIDAD_ASIGNADA": asignado,
        "M3_OBJETIVO": m3_objetivo,
        "M3_ASIGNADO": m3_objetivo if asignado >= objetivo else 0.0,
        "MOV_ORIGINAL": objetivo,
        "REGLA_DEMANDA": regla,
        "TIPO_DE_CORTE": "OK",
        "CITY": "CDMX",
        "WAREHOUSE_NAME": "STORE",
        "STORAGE": "Room Temperature",
        "VALUE": "REGULAR",
        "PRIORIDAD_TIENDA": 1,
        "ES_GOLDEN": False,
        "ES_INFALTABLE": False,
        "STOCK_BASE_444": 0,
        "ASIGNADO_444": asignado,
        "TAREAS_GENERADAS": 1,
        "M3_POR_UNIDAD": 0.1,
    }


def _topup_row(destination, sku, objetivo, asignado, m3_objetivo, regla):
    row = _naked_row(destination, sku, objetivo, asignado, m3_objetivo, regla)
    row["TIPO_DE_CORTE"] = "ENVIADOS POR ALGUN ENGINE"
    return row


def test_naked_summary_excludes_all_known_topup_engines():
    naked_rows = [
        _naked_row(100, 10, objetivo=10, asignado=10, m3_objetivo=1.0),
        _naked_row(100, 11, objetivo=5, asignado=5, m3_objetivo=0.5),
    ]
    topup_rows = [
        _topup_row(100, 20, 8, 8, 2.0, "AVL_DOH"),
        _topup_row(100, 21, 6, 6, 1.5, "PREVENTIVO_DOH"),
        _topup_row(100, 22, 7, 7, 1.7, "REFUERZO_ESPECIALES_DOH"),
        _topup_row(100, 23, 9, 9, 2.2, "SHALASHASKA_ENGINE"),
        _topup_row(100, 24, 4, 4, 1.1, "LIQUID_ENGINE"),
        _topup_row(100, 25, 3, 3, 0.9, "VENOM_DDMRP"),
        _topup_row(100, 26, 3, 3, 0.9, "VENOM_OOWL_MINIMO"),
    ]
    result = SimpleNamespace(
        base_rows=naked_rows + topup_rows,
        allocation_rows=[],
        capacity_rows=[],
        tasks_used=0,
        max_tasks=100,
        warnings=[],
    )
    analytics = m.build_planning_analytics(result, (444,))
    summary = analytics["summary"]

    # Solo las 2 filas Naked/Solidus cuentan como "requerido".
    assert summary["naked_eligible_cases"] == 2
    assert summary["naked_target_units"] == 15  # 10 + 5
    assert summary["naked_target_m3"] == 1.5  # 1.0 + 0.5

    # El total general SÍ debe incluir todo (para "Planeación Final").
    assert summary["eligible_cases"] == 9
    assert summary["target_units"] == 15 + (8 + 6 + 7 + 9 + 4 + 3 + 3)


def test_naked_summary_matches_full_summary_when_no_topup_engines_ran():
    naked_rows = [
        _naked_row(100, 10, objetivo=10, asignado=10, m3_objetivo=1.0),
        _naked_row(100, 11, objetivo=5, asignado=5, m3_objetivo=0.5),
    ]
    result = SimpleNamespace(
        base_rows=naked_rows,
        allocation_rows=[],
        capacity_rows=[],
        tasks_used=0,
        max_tasks=100,
        warnings=[],
    )
    analytics = m.build_planning_analytics(result, (444,))
    summary = analytics["summary"]

    assert summary["naked_eligible_cases"] == summary["eligible_cases"]
    assert summary["naked_target_units"] == summary["target_units"]
    assert summary["naked_target_m3"] == summary["target_m3"]


def test_engine_topup_regla_demanda_constant_matches_actual_engine_tags():
    """Si algún engine cambia su REGLA_DEMANDA, esta prueba debe fallar para
    que alguien actualice ENGINE_TOPUP_REGLA_DEMANDA a la vez."""
    import engines.liquid_engine as liquid_engine
    import engines.shalashaska_engine as shalashaska_engine
    import engines.venom_engine as venom_engine

    with open(liquid_engine.__file__, encoding="utf-8") as f:
        assert '"REGLA_DEMANDA": "LIQUID_ENGINE"' in f.read()
    with open(shalashaska_engine.__file__, encoding="utf-8") as f:
        assert '"REGLA_DEMANDA": "SHALASHASKA_ENGINE"' in f.read()
    with open(venom_engine.__file__, encoding="utf-8") as f:
        venom_source = f.read()
        assert '"REGLA_DEMANDA": "VENOM_DDMRP"' in venom_source
        assert '"REGLA_DEMANDA": "VENOM_OOWL_MINIMO"' in venom_source
