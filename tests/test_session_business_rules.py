"""Pruebas de los ajustes de negocio de esta sesión:

- SKUs excluidos permanentemente a nivel backend.
- Restricciones exclusivas del perfil Raiden (orígenes default, ciudades
  protegidas, bloqueo de Solidus/Liquid).
- Validación de COPÉRNICO por warehouse antes de ejecutar.
- MOQ especial del SKU 86195 en INSUMOS.
"""

import io

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

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
