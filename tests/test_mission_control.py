import modelo_abasto as engine

from engines.mission_control import select_engine_rows


def make_row(roq: float, demand: float, opening: float) -> dict:
    return {
        "ROQ_INPUT": roq,
        "MOV_ORIGINAL": roq,
        "PREDICTED_DEMAND": demand,
        "PREDICTED_OPENING_INVENTORY": opening,
    }


def test_loadout_routes_natural_and_manual_independently():
    config = engine.Config()
    natural = make_row(5, 10, 2)
    manual = make_row(0, 0, 0)
    no_recommendation = make_row(0, 0, 5)

    naked_rows, naked_summary = select_engine_rows(
        [natural, manual, no_recommendation],
        config,
        include_naked=True,
        include_solidus=False,
    )
    assert naked_rows == [natural, no_recommendation]
    assert naked_summary["solidus_requirements"] == 1

    solidus_rows, _ = select_engine_rows(
        [natural, manual, no_recommendation],
        config,
        include_naked=False,
        include_solidus=True,
    )
    assert solidus_rows == [manual]

