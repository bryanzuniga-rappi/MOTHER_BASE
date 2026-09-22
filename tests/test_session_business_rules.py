"""Pruebas de los ajustes de negocio de esta sesión:

- SKUs excluidos permanentemente a nivel backend.
- Restricciones exclusivas del perfil Raiden (orígenes default, ciudades
  protegidas, bloqueo de Solidus/Liquid).
- Validación de COPÉRNICO por warehouse antes de ejecutar.
- MOQ especial del SKU 86195 en INSUMOS.
"""

import io
from types import SimpleNamespace

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modelo_abasto as engine  # noqa: E402
import modules.les_enfants_terribles as m  # noqa: E402


# --- SKUs excluidos a nivel backend -------------------------------------

def test_backend_excluded_skus_are_exactly_the_requested_three():
    assert m.BACKEND_EXCLUDED_SKUS == frozenset({92462, 92463, 9151})


def test_backend_excluded_skus_survive_even_with_empty_codec_field():
    """Simula exactamente la línea de execute_planning: unión incondicional."""
    excluded_skus_from_codec: set[int] = set()
    excluded_sku_set = set(excluded_skus_from_codec or ()) | m.BACKEND_EXCLUDED_SKUS
    assert {92462, 92463, 9151}.issubset(excluded_sku_set)


def test_backend_excluded_skus_combine_with_user_choices():
    excluded_skus_from_codec = {111, 222}
    excluded_sku_set = set(excluded_skus_from_codec) | m.BACKEND_EXCLUDED_SKUS
    assert excluded_sku_set == {111, 222, 92462, 92463, 9151}


# --- Restricciones de perfil Raiden --------------------------------------

def test_raiden_protected_cities_are_the_six_requested():
    assert m.RAIDEN_PROTECTED_CITIES == frozenset(
        {"CDMX", "GDL", "MTY", "PUEBLA", "QUERETARO", "SALTILLO"}
    )


def test_raiden_default_origins_are_444_and_831():
    assert m.RAIDEN_DEFAULT_ORIGINS == (444, 831)


def test_raiden_blockable_city_options_excludes_protected_cities():
    """Replica la lógica de filtrado que usa render() para el multiselect."""
    city_labels = {
        "CDMX": "Ciudad de México",
        "GDL": "Guadalajara",
        "MTY": "Monterrey",
        "PUEBLA": "Puebla",
        "QUERETARO": "Querétaro",
        "SALTILLO": "Saltillo",
        "TIJUANA": "Tijuana",
    }
    blockable_city_options = [
        city for city in city_labels if city not in m.RAIDEN_PROTECTED_CITIES
    ]
    assert blockable_city_options == ["TIJUANA"]


# --- Validación de COPÉRNICO por warehouse -------------------------------

def test_copernico_required_warehouses_are_444_831_856():
    assert m.COPERNICO_REQUIRED_WAREHOUSES == frozenset({444, 831, 856})


class _FakeUploadedFile:
    """Simula lo mínimo de un UploadedFile de Streamlit que usa la función."""

    def __init__(self, content: bytes):
        self._buffer = io.BytesIO(content)

    def seek(self, position: int) -> None:
        self._buffer.seek(position)

    def getvalue(self) -> bytes:
        return self._buffer.getvalue()


def _make_copernico_csv_bytes(bodega: int, rows: int = 2) -> bytes:
    lines = ["Bodega,EAN,Ubicacion,Saldo,ZonaPiso"]
    for i in range(rows):
        lines.append(f"{bodega},{1000 + i},ZABCDEFG,5,")
    return "\n".join(lines).encode("utf-8")


def test_detect_copernico_warehouses_single_file():
    files = [_FakeUploadedFile(_make_copernico_csv_bytes(444))]
    assert m.detect_copernico_warehouses(files) == {444}


def test_detect_copernico_warehouses_multiple_files():
    files = [
        _FakeUploadedFile(_make_copernico_csv_bytes(444)),
        _FakeUploadedFile(_make_copernico_csv_bytes(831)),
    ]
    assert m.detect_copernico_warehouses(files) == {444, 831}


def test_detect_copernico_warehouses_tolerates_space_header():
    content = b"Bodega,EAN,Ubicacion,Saldo\n856,2000,ZABCDEFG,3\n"
    files = [_FakeUploadedFile(content)]
    assert m.detect_copernico_warehouses(files) == {856}


def test_detect_copernico_warehouses_empty_list_returns_empty_set():
    assert m.detect_copernico_warehouses([]) == set()
    assert m.detect_copernico_warehouses(None) == set()


def test_origins_requiring_copernico_validation_logic():
    """Replica la comprobación que bloquea la ejecución en render()."""
    selected_origins = {444, 831}
    origins_needing_copernico = selected_origins & m.COPERNICO_REQUIRED_WAREHOUSES
    covered = {444}  # solo se cargó el CSV de 444
    missing = origins_needing_copernico - covered
    assert missing == {831}


def test_origins_not_requiring_copernico_pass_without_files():
    selected_origins = {425, 856}
    origins_needing_copernico = selected_origins & m.COPERNICO_REQUIRED_WAREHOUSES
    covered: set[int] = set()
    missing = origins_needing_copernico - covered
    assert missing == {856}  # 425 no requiere, 856 sí y falta


def test_all_required_origins_covered_passes():
    selected_origins = {444, 831, 856}
    origins_needing_copernico = selected_origins & m.COPERNICO_REQUIRED_WAREHOUSES
    covered = {444, 831, 856}
    missing = origins_needing_copernico - covered
    assert missing == set()


# --- MOQ especial del SKU 86195 -------------------------------------------

def test_sku_86195_moq_is_200():
    assert m.INSUMO_STOCK_RULES[86195]["moq"] == 200


def test_sku_86195_quantities_round_down_to_multiples_of_200():
    moq = m.INSUMO_STOCK_RULES[86195]["moq"]
    for requested in (0, 150, 199, 200, 250, 399, 400, 999):
        batches = requested // moq
        rounded = batches * moq
        assert rounded % 200 == 0
    assert (250 // moq) * moq == 200
    assert (399 // moq) * moq == 200
    assert (400 // moq) * moq == 400


def test_other_insumo_rules_unaffected_by_86195_change():
    assert m.INSUMO_STOCK_RULES[85097]["moq"] == 1_000
    assert m.INSUMO_STOCK_RULES[76491]["moq"] == 1_000


# --- Nuevos SKUs de INSUMOS: 82126 y 90532 --------------------------------

def test_sku_82126_target_and_moq():
    rule = m.INSUMO_STOCK_RULES[82126]
    assert rule["target_stock"] == 1_050
    assert rule["moq"] == 350


def test_sku_90532_target_and_moq():
    rule = m.INSUMO_STOCK_RULES[90532]
    assert rule["target_stock"] == 1_050
    assert rule["moq"] == 350


def test_sku_76491_target_updated_to_5000():
    assert m.INSUMO_STOCK_RULES[76491]["target_stock"] == 5_000


def test_sku_82126_has_no_city_restriction():
    assert 82126 not in m.INSUMO_CITY_RESTRICTIONS


def test_sku_90532_restricted_to_cdmx_only():
    assert m.INSUMO_CITY_RESTRICTIONS[90532] == frozenset({"CDMX"})


def test_append_insumos_blocks_90532_outside_cdmx(tmp_path):
    catalogs = engine.Catalogs(
        volume_m3={82126: 0.001, 90532: 0.001},
        blocked_products=set(),
        route_cost_blocks=set(),
        store_priority={100: 1, 200: 1},
        high_value={},
        rackeados_444=set(),
        store_capacity={100: 100.0, 200: 100.0},
        copernico_unusable_444={},
        unavailable_stock={},
        stock_base={
            (444, 82126): 10_000.0,
            (444, 90532): 10_000.0,
        },
        golden_infaltables=set(),
        stores={
            444: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "O444"},
            100: {"city": "CDMX", "city_norm": "CDMX", "warehouse_name": "STORE CDMX"},
            200: {"city": "Guadalajara", "city_norm": "GDL", "warehouse_name": "STORE GDL"},
        },
        storage={},
        warnings=[],
        excluded_products=set(),
    )
    result = SimpleNamespace(
        allocation_rows=[
            {"WAREHOUSE_DESTINATION": 100, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 999, "QUANTITY": 1},
            {"WAREHOUSE_DESTINATION": 200, "WAREHOUSE_SOURCE": 444, "RETAIL_ID": 999, "QUANTITY": 1},
        ],
        base_rows=[],
        warnings=[],
    )
    insumos_rows = [
        {"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 90532, "QUANTITY": 1050},
        {"WAREHOUSE_DESTINATION": 200, "RETAIL_ID": 90532, "QUANTITY": 1050},
        {"WAREHOUSE_DESTINATION": 100, "RETAIL_ID": 82126, "QUANTITY": 1050},
        {"WAREHOUSE_DESTINATION": 200, "RETAIL_ID": 82126, "QUANTITY": 1050},
    ]

    bulk_path = tmp_path / "BulkCD_444.csv"
    engine.write_csv(bulk_path, [], engine.OUTPUT_COLUMNS)

    summary = m.append_insumos_to_bulk_444(
        [bulk_path], result, catalogs, insumos_rows, (444,), True
    )

    import csv as csv_module
    with bulk_path.open(newline="", encoding="utf-8-sig") as handle:
        written_rows = list(csv_module.DictReader(handle))
    dest_by_sku = {
        (int(row["WAREHOUSE_DESTINATION"]), int(row["RETAIL_ID"]))
        for row in written_rows
        if int(row["RETAIL_ID"]) in (82126, 90532)
    }
    assert (100, 90532) in dest_by_sku  # CDMX: permitido
    assert (200, 90532) not in dest_by_sku  # GDL: bloqueado
    assert (100, 82126) in dest_by_sku  # 82126 sin restricción: ambas tiendas
    assert (200, 82126) in dest_by_sku
    assert summary["lines_blocked_city_restriction"] == 1
