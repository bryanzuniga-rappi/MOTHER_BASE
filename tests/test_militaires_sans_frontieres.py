"""Contrato de partición de destinos para la salida de DispatchTrack."""

import io

import openpyxl

from tests._streamlit_stub import install

install()

from modules.militaires_sans_frontieres import (
    DISPATCHTRACK_OUTPUT_HEADERS,
    _assign_and_split,
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


def test_priority_one_uses_only_first_torton_turn_then_falls_back_to_blank():
    headers = [
        'CÓDIGO DE PARADA*', 'CAPACIDAD UNO', 'IDENTIFICADOR CONTACTO*',
        'NOMBRE CONTACTO*', 'Tipo camion', 'IMPORTANCIA',
    ]
    rows = [
        {
            'CÓDIGO DE PARADA*': 'P1', 'CAPACIDAD UNO': '12',
            'IDENTIFICADOR CONTACTO*': 'P1', 'NOMBRE CONTACTO*': 'P1',
        },
        {
            'CÓDIGO DE PARADA*': 'P2', 'CAPACIDAD UNO': '8',
            'IDENTIFICADOR CONTACTO*': 'P2', 'NOMBRE CONTACTO*': 'P2',
        },
    ]
    fleet = [{'UNIDAD': 'Torton', 'CANTIDAD': 1, 'VUELTAS': 2, 'CAPACIDAD': 8}]
    directions = {'P1': {'PRIORITY': 1}, 'P2': {'PRIORITY': 0}}

    output, warnings = _assign_and_split(headers, rows, fleet, directions)
    priority_one = [row for row in output if str(row['CÓDIGO DE PARADA*']).startswith('P1')]
    other_stores = [row for row in output if str(row['CÓDIGO DE PARADA*']).startswith('P2')]

    assert sum(float(row['CAPACIDAD UNO']) for row in priority_one if row['Tipo camion'] == 'Torton') == 8
    assert sum(float(row['CAPACIDAD UNO']) for row in priority_one if not row['Tipo camion']) == 4
    assert sum(float(row['CAPACIDAD UNO']) for row in other_stores if row['Tipo camion'] == 'Torton') == 8
    assert not warnings


def test_three_tortons_with_two_turns_reserve_exactly_24_pallets_for_priority_one():
    headers = [
        'CÓDIGO DE PARADA*', 'CAPACIDAD UNO', 'IDENTIFICADOR CONTACTO*',
        'NOMBRE CONTACTO*', 'Tipo camion', 'IMPORTANCIA',
    ]
    rows = [
        {
            'CÓDIGO DE PARADA*': 'P1', 'CAPACIDAD UNO': '30',
            'IDENTIFICADOR CONTACTO*': 'P1', 'NOMBRE CONTACTO*': 'P1',
        },
        {
            'CÓDIGO DE PARADA*': 'REGULAR', 'CAPACIDAD UNO': '24',
            'IDENTIFICADOR CONTACTO*': 'REGULAR', 'NOMBRE CONTACTO*': 'REGULAR',
        },
    ]
    fleet = [{'UNIDAD': 'Torton', 'CANTIDAD': 3, 'VUELTAS': 2, 'CAPACIDAD': 8}]
    directions = {'P1': {'PRIORITY': 1}, 'REGULAR': {'PRIORITY': 0}}

    output, _warnings = _assign_and_split(headers, rows, fleet, directions)
    priority_one = [row for row in output if str(row['CÓDIGO DE PARADA*']).startswith('P1')]
    regular = [row for row in output if str(row['CÓDIGO DE PARADA*']).startswith('REGULAR')]

    assert sum(float(row['CAPACIDAD UNO']) for row in priority_one if row['Tipo camion'] == 'Torton') == 24
    assert sum(float(row['CAPACIDAD UNO']) for row in priority_one if not row['Tipo camion']) == 6
    assert sum(float(row['CAPACIDAD UNO']) for row in regular if row['Tipo camion'] == 'Torton') == 24


def test_priority_one_with_1_5_constraint_never_uses_torton_or_blank_type():
    headers = [
        'CÓDIGO DE PARADA*', 'CAPACIDAD UNO', 'IDENTIFICADOR CONTACTO*',
        'NOMBRE CONTACTO*', 'Tipo camion', 'IMPORTANCIA',
    ]
    row = {
        'CÓDIGO DE PARADA*': 'P1-15', 'CAPACIDAD UNO': '3',
        'IDENTIFICADOR CONTACTO*': 'P1-15', 'NOMBRE CONTACTO*': 'P1-15',
    }
    fleet = [
        {'UNIDAD': 'Torton', 'CANTIDAD': 1, 'VUELTAS': 2, 'CAPACIDAD': 8},
        {'UNIDAD': '1.5', 'CANTIDAD': 1, 'VUELTAS': 1, 'CAPACIDAD': 2},
    ]

    output, _warnings = _assign_and_split(
        headers, [row], fleet, {'P1-15': {'PRIORITY': 1, 'CONSTRAIN': '1.5'}}
    )

    assert output and {item['Tipo camion'] for item in output} == {'1.5'}
    assert {item['IMPORTANCIA'] for item in output} == {'1'}

