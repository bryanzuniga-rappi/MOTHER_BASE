"""Las tablas de resultados no dependen del componente DataFrame de Streamlit."""

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


def test_static_table_escapes_cell_values_and_keeps_columns():
    rendered = []
    original_markdown = m.st.markdown
    try:
        m.st.markdown = lambda content, **_kwargs: rendered.append(content)
        m.render_static_table(
            [{"TIENDA": "<script>", "UNIDADES": 3}, {"TIENDA": "A", "EXTRA": "sí"}]
        )
    finally:
        m.st.markdown = original_markdown

    html = rendered[0]
    assert "mb-static-table" in html
    assert "&lt;script&gt;" in html
    assert "UNIDADES" in html and "EXTRA" in html
