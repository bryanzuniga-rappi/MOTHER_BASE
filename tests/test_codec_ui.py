"""CODEC de punta a punta con un Streamlit simulado: lo que la UI manda a
execute_planning (nombres y valores) y los defaults pedidos."""

import modules.les_enfants_terribles as m
from tests.codec_harness import run_codec


def kwargs_for(overrides=None, **options):
    kwargs, fake = run_codec(overrides, **options)
    assert kwargs is not None, f"la UI no llegó a ejecutar: {fake.errors}"
    return kwargs


# --- defaults pedidos -------------------------------------------------------------------

def test_requested_defaults():
    k = kwargs_for()
    assert k["block_fruver_811"] is True
    assert k["block_off_schedule_shipments"] is True
    assert k["venom_lead_time_days"] == 2.0
    assert k["special_doh_targets"] == {}              # buckets del Refuerzo apagados
    assert k["avl_doh"] == 3.0


def test_each_refuerzo_bucket_defaults_to_three_doh_when_enabled():
    k = kwargs_for(force_toggles=True)
    assert k["special_doh_targets"] == {"INFALTABLE": 3.0, "GOLDEN": 3.0, "ANCHOR": 3.0, "KVI": 3.0}


def test_refuerzo_bucket_toggle_and_doh_are_independent():
    k = kwargs_for({
        "Reforzar Golden": True, "DOH objetivo (Golden)": 5.0,
        "Reforzar KVIs": True, "DOH objetivo (KVIs)": 2.0,
    })
    assert k["special_doh_targets"] == {"GOLDEN": 5.0, "KVI": 2.0}
    assert k["include_special_doh_fill"] is True


def test_swa_priority_toggle_reaches_solidus():
    assert kwargs_for()["solidus_swa_priority"] is True
    assert kwargs_for({"Priorizar por SWA cuando falte capacidad o tareas": False})["solidus_swa_priority"] is False


# --- toggles globales --------------------------------------------------------------------

def test_global_toggles_reach_the_engine():
    k = kwargs_for()
    assert k["ignore_store_capacity"] is False and k["enable_global_blocks_rule"] is True
    k = kwargs_for({"Ignorar capacidad de tienda (m³)": True, "Regla de bloqueos": False})
    assert k["ignore_store_capacity"] is True and k["enable_global_blocks_rule"] is False


# --- Naked -----------------------------------------------------------------------------------

def test_naked_controls_reach_the_engine():
    k = kwargs_for()
    assert (k["hardcode_zero_total"], k["hardcode_inventory_below_demand"], k["hardcode_low_net_transfer"]) == (True, True, True)
    assert (k["net_transfer_max"], k["destination_stock_below"]) == (3.0, 3.0)
    assert k["raise_small_roq_to_minimum"] is True and k["use_extra_mov_columns"] is True
    k = kwargs_for({
        "Cubrir inventario menor a la demanda": False, "Net transfer máximo (unidades)": 5.0,
        "Subir recomendaciones pequeñas al mínimo": False, "Usar columnas adicionales de MOV": False,
    })
    assert k["hardcode_inventory_below_demand"] is False and k["net_transfer_max"] == 5.0
    assert k["raise_small_roq_to_minimum"] is False and k["use_extra_mov_columns"] is False


def test_hardcode_rules_hidden_when_master_toggle_is_off():
    kwargs, fake = run_codec({"Cubrir a Fountain9": False})
    labels = [label for _kind, label in fake.labels]
    assert "Cubrir forecast y stock en cero" not in labels
    assert kwargs["cover_fountain9_hardcodes"] is False


# --- Shalashaska ---------------------------------------------------------------------------

def test_shalashaska_defaults_and_inputs():
    k = kwargs_for()
    assert k["shalashaska_extra_cities"] == () and k["shalashaska_allow_sensitive"] is False
    assert k["shalashaska_evacuation_fraction"] == 1.0
    assert k["shalashaska_target_doh"] == 7.0
    k = kwargs_for({
        "Ciudades adicionales (opcional)": ["Guadalajara"],
        "Permitir categorías sensibles (Huevo)": True,
        "Evacuar solo una parte de la merma": True,
    })
    assert k["shalashaska_extra_cities"] == ("Guadalajara",)
    assert k["shalashaska_allow_sensitive"] is True
    assert k["shalashaska_evacuation_fraction"] == 0.8             # 80 % por defecto
    k = kwargs_for({"Evacuar solo una parte de la merma": True, "Porcentaje de merma a evacuar (%)": 60})
    assert k["shalashaska_evacuation_fraction"] == 0.6


def test_shalashaska_doh_is_no_longer_an_input():
    _k, fake = run_codec()
    assert "DOH objetivo (primera pasada)" not in [label for _kind, label in fake.labels]


def test_shalashaska_offers_extra_cities_beyond_the_forced_ones():
    kwargs, fake = run_codec()                       # origen 811 => CDMX forzada
    assert kwargs is not None
    assert "Ciudades adicionales (opcional)" in [label for _kind, label in fake.labels]


# --- Liquid ------------------------------------------------------------------------------------

def test_liquid_has_no_forecast_horizon_input_anymore():
    _k, fake = run_codec()
    assert not [l for _kind, l in fake.labels if "horizonte" in l.lower()]


# --- Venom -------------------------------------------------------------------------------------

def test_venom_parameters_reach_the_engine():
    k = kwargs_for()
    assert (k["venom_ltf"], k["venom_vf"], k["venom_order_cycle_days"]) == (0.5, 0.5, 0.0)
    assert k["venom_trigger_zone"] == "yellow" and k["venom_shipping_multiple"] == 1
    assert k["venom_subtract_lead_time_demand"] is True and k["venom_consider_incoming"] is True
    assert k["venom_cap_to_store_capacity"] is False and k["venom_only_manual_skus"] is False
    assert k["venom_min_green_units"] == float(k["minimum_positive_quantity"])
    k = kwargs_for({
        "Factor de lead time (LTF)": 0.8, "Factor de variabilidad (VF)": 0.2,
        "Ciclo de pedido (días)": 3.0, "Múltiplo de envío (unidades)": 6,
        "Disparador de reorden": "green", "Limitar a la capacidad de la tienda": True,
        "Considerar incoming en tránsito": False,
    })
    assert (k["venom_ltf"], k["venom_vf"], k["venom_order_cycle_days"]) == (0.8, 0.2, 3.0)
    assert k["venom_shipping_multiple"] == 6 and k["venom_trigger_zone"] == "green"
    assert k["venom_cap_to_store_capacity"] is True and k["venom_consider_incoming"] is False


def test_venom_manual_skus_are_parsed_per_origin():
    k = kwargs_for({m.format_origin(811): "10087, 10589\n10848"})
    assert k["venom_manual_skus_by_origin"] == {811: {10087, 10589, 10848}}
    assert kwargs_for()["venom_manual_skus_by_origin"] == {}


def test_venom_kvi_is_a_selectable_section_type():
    k = kwargs_for({"Tipo de sección (Venom)": ["IS_KVI", "IS_GOLDEN"]})
    assert k["venom_section_types"] == frozenset({"IS_KVI", "IS_GOLDEN"})


# --- todo prendido ------------------------------------------------------------------------------

def test_everything_on_still_binds_to_the_engine_signature():
    k = kwargs_for(force_toggles=True)
    assert k["ignore_store_capacity"] is True
    assert k["venom_only_manual_skus"] is True and k["venom_cap_to_store_capacity"] is True


# --- textos de las tarjetas de engine ------------------------------------------------------

CARD_KEYS = {
    "Naked": "engine_naked_card", "Shalashaska": "engine_shalashaska_card",
    "Solidus": "engine_solidus_card", "Liquid": "engine_liquid_card",
    "Venom": "engine_venom_card", "Kazuhira": "engine_kazuhira_card",
}


def test_each_engine_card_uses_the_registry_text():
    _k, fake = run_codec()
    for engine, key in CARD_KEYS.items():
        assert fake.cards[key]["description"] == m.ENGINE_INFO[engine]["card"], engine


def test_card_texts_are_short_and_name_the_engines_purpose():
    for engine in CARD_KEYS:
        text = m.ENGINE_INFO[engine]["card"]
        assert 80 <= len(text) <= 320, (engine, len(text))
        assert text.count(".") <= 4, engine            # sin párrafos largos


def test_cards_are_numbered_in_execution_order():
    _k, fake = run_codec()
    eyebrows = [fake.cards[CARD_KEYS[e]]["eyebrow"] for e in CARD_KEYS]
    assert [x.split("·")[0].strip() for x in eyebrows] == [f"ENGINE / 0{i}" for i in range(1, 7)]
    assert list(CARD_KEYS) == list(m.ENGINE_ORDER[:6])


def test_raiden_still_sees_the_locked_message_on_restricted_engines():
    from tests.codec_harness import FakeStreamlit
    original = FakeStreamlit.__init__

    def raiden_init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.session_state["mb_profile"] = "RAIDEN"

    FakeStreamlit.__init__ = raiden_init
    try:
        _kwargs, fake = run_codec()
    finally:
        FakeStreamlit.__init__ = original
    for engine in ("Solidus", "Liquid", "Kazuhira"):
        assert fake.cards[CARD_KEYS[engine]]["description"] == "Bloqueado para el perfil Raiden."


def test_numbers_in_the_explanations_match_the_real_defaults():
    """Los textos citan umbrales; no pueden contradecir lo que hace el código."""
    liquid = m.ENGINE_INFO["Liquid"]["card"] + " ".join(m.ENGINE_INFO["Liquid"]["how"])
    assert "14 DOH" in liquid
    import inspect
    from engines import liquid_engine
    assert inspect.signature(liquid_engine.apply_liquid_engine).parameters["max_doh"].default == 14.0
    solidus_preventive = m.ENGINE_INFO["Solidus"]["coverages"]["Preventivo"]
    assert "1 DOH" in solidus_preventive and "3 unidades" in solidus_preventive
    shalashaska = " ".join(m.ENGINE_INFO["Shalashaska"]["how"])
    from engines import shalashaska_engine as sh
    assert sh.FORCED_CITY_BY_ORIGIN[444] == "CDMX" and "444, 811, 831 y 834: CDMX" in shalashaska
    assert sh.FORCED_CITY_BY_ORIGIN[425] == "GDL" and sh.FORCED_CITY_BY_ORIGIN[49] == "MTY"
