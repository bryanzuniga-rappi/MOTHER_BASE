"""Contrato de partición de destinos para la salida de DispatchTrack."""

from tests._streamlit_stub import install

install()

from modules.militaires_sans_frontieres import _mark_split_destination, _to_csv


HEADERS = [
    "CÓDIGO DE PARADA*",
    "DIRECCION*",
    "IDENTIFICADOR CONTACTO*",
    "NOMBRE CONTACTO*",
]


def test_split_destination_marks_both_contact_fields_and_increments_street_number():
    row = {
        "CÓDIGO DE PARADA*": "160644-1",
        "DIRECCION*": "Calle Huicholes, 27A, Santa Cruz Acatlán, 53150",
        "IDENTIFICADOR CONTACTO*": "Huicholes",
        "NOMBRE CONTACTO*": "Huicholes",
    }

    _mark_split_destination(row, HEADERS, 1)

    assert row["CÓDIGO DE PARADA*"] == "160644-1"
    assert row["DIRECCION*"] == "Calle Huicholes, 28A, Santa Cruz Acatlán, 53150"
    assert row["IDENTIFICADOR CONTACTO*"] == "Huicholes-1"
    assert row["NOMBRE CONTACTO*"] == "Huicholes-1"


def test_second_split_uses_its_own_suffix_and_address_increment():
    row = {
        "DIRECCION*": "Calle Jalapa, 151, Roma Norte, 06700",
        "IDENTIFICADOR CONTACTO*": "Ángel de Independencia",
        "NOMBRE CONTACTO*": "Ángel de Independencia",
    }

    _mark_split_destination(row, HEADERS, 2)

    assert row["DIRECCION*"] == "Calle Jalapa, 153, Roma Norte, 06700"
    assert row["IDENTIFICADOR CONTACTO*"] == "Ángel de Independencia-2"
    assert row["NOMBRE CONTACTO*"] == "Ángel de Independencia-2"


def test_csv_is_utf8_with_bom_and_preserves_accents_for_excel():
    content = _to_csv(
        ["NOMBRE CONTACTO*", "DIRECCION*"],
        [{"NOMBRE CONTACTO*": "Ángel de Independencia", "DIRECCION*": "Peña, 151"}],
    )

    assert content.startswith(b"\xef\xbb\xbf")
    assert content.decode("utf-8-sig") == (
        "NOMBRE CONTACTO*,DIRECCION*\r\n"
        'Ángel de Independencia,"Peña, 151"\r\n'
    )
