"""Pruebas del fix de freeze de navegador: las tablas grandes ya no deben
mandar más de MAX_DISPLAY_ROWS filas al frontend, sin importar cuántas
filas reales tenga el dataset."""

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


class _patched:
    """Sustituye temporalmente atributos de m.st, sin depender del fixture
    monkeypatch de pytest (el runner de este proyecto es un script propio)."""

    def __init__(self, **overrides):
        self._overrides = overrides
        self._saved = {}

    def __enter__(self):
        for name, value in self._overrides.items():
            self._saved[name] = getattr(m.st, name)
            setattr(m.st, name, value)
        return self

    def __exit__(self, *exc_info):
        for name, value in self._saved.items():
            setattr(m.st, name, value)


def test_max_display_rows_is_100():
    assert m.MAX_DISPLAY_ROWS == 100


def test_rows_to_csv_bytes_empty():
    assert m.rows_to_csv_bytes([]) == b""


def test_rows_to_csv_bytes_roundtrip():
    import csv
    import io

    rows = [{"A": 1, "B": "x"}, {"A": 2, "B": "y"}]
    payload = m.rows_to_csv_bytes(rows)
    assert payload.startswith(b"\xef\xbb\xbf")  # BOM, igual que el resto de la app
    text = payload.decode("utf-8-sig")
    reader = list(csv.DictReader(io.StringIO(text)))
    assert reader == [{"A": "1", "B": "x"}, {"A": "2", "B": "y"}]


def test_render_capped_dataframe_never_exceeds_max_display():
    """El punto central del bug: antes se mandaban TODAS las filas al
    frontend aunque la altura estuviera acotada. Ahora la lista que
    realmente llega a st.dataframe debe estar truncada."""
    captured = {}

    def fake_dataframe(data, **kwargs):
        captured["data"] = data
        captured["height"] = kwargs.get("height")

    with _patched(
        dataframe=fake_dataframe,
        caption=lambda *a, **k: None,
        download_button=lambda *a, **k: None,
    ):
        big_dataset = [{"ID": i} for i in range(5000)]
        m.render_capped_dataframe(big_dataset, key="test_big")

    assert len(captured["data"]) == 100
    assert captured["height"] == (100 + 1) * 36 + 4


def test_render_capped_dataframe_shows_everything_when_small():
    captured = {}
    with _patched(dataframe=lambda data, **k: captured.update(data=data)):
        small_dataset = [{"ID": i} for i in range(5)]
        m.render_capped_dataframe(small_dataset, key="test_small")

    assert len(captured["data"]) == 5


def test_render_capped_dataframe_offers_download_only_when_requested():
    download_calls = []
    with _patched(
        dataframe=lambda *a, **k: None,
        caption=lambda *a, **k: None,
        download_button=lambda *a, **k: download_calls.append(k),
    ):
        big_dataset = [{"ID": i} for i in range(500)]
        m.render_capped_dataframe(big_dataset, key="no_download")
        assert download_calls == []

        m.render_capped_dataframe(
            big_dataset, key="with_download", offer_download=True, file_label="test"
        )
    assert len(download_calls) == 1


def test_report_table_caps_rows_too():
    """report_table es el helper compartido preexistente (ciudad/tienda) que
    tenía el mismo bug: acotaba altura pero no filas reales."""
    captured = {}
    with _patched(
        dataframe=lambda data, **k: captured.update(data=data),
        caption=lambda *a, **k: None,
    ):
        big_dataset = [{"CIUDAD": f"C{i}"} for i in range(3000)]
        m.report_table(big_dataset)

    assert len(captured["data"]) == m.MAX_DISPLAY_ROWS
