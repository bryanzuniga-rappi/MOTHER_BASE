"""Contrato de partición de destinos para la salida de DispatchTrack."""

import io

import openpyxl

from tests._streamlit_stub import install

install()

from modules.militaires_sans_frontieres import (
    DISPATCHTRACK_OUTPUT_HEADERS,
    _mark_split_destination,
    _to_xlsx,
)


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


def test_output_uses_the_exact_spanish_dispatchtrack_headers_and_text_dates():
    headers = [
        "FECHA MIN ENTREGA*",
        "FECHA MAX ENTREGA*",
        "MIN VENTANA HORARIO 1*",
        "MAX VENTANA HORARIA 1*",
        "NOMBRE CONTACTO*",
    ]
    content = _to_xlsx(headers, [{
        "FECHA MIN ENTREGA*": "23/10/2026",
        "FECHA MAX ENTREGA*": "24/10/2026",
        "MIN VENTANA HORARIO 1*": "00:00",
        "MAX VENTANA HORARIA 1*": "07:00",
        "NOMBRE CONTACTO*": "Ángel",
    }])
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    worksheet = workbook['Sheet1']

    assert tuple(cell.value for cell in worksheet[1]) == DISPATCHTRACK_OUTPUT_HEADERS
    assert worksheet['H2'].value == '23/10/2026'
    assert worksheet['I2'].value == '24/10/2026'
    assert worksheet['J2'].value == '00:00'
    assert worksheet['K2'].value == '07:00'
    assert all(worksheet[cell].data_type == 's' for cell in ('H2','I2','J2','K2'))
    assert all(worksheet[cell].number_format == '@' for cell in ('H2','I2','J2','K2'))
    assert worksheet['T2'].value == 'Ángel'
    workbook.close()

