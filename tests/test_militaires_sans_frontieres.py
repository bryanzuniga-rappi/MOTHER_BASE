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


def test_split_conserves_capacity_cost_and_secondary_capacity_when_fleet_is_fragmented():
    headers = [
        'CÓDIGO DE PARADA*', 'IDENTIFICADOR CONTACTO*', 'CAPACIDAD UNO',
        'CAPACIDAD DOS', 'COSTO ITEM', 'Tipo camion', 'IMPORTANCIA',
    ]
    rows = [{
        'CÓDIGO DE PARADA*': 'PEDIDO-1',
        'IDENTIFICADOR CONTACTO*': 'TIENDA',
        'CAPACIDAD UNO': '3.85',
        'CAPACIDAD DOS': '7.7',
        'COSTO ITEM': '385',
    }]
    # La primera parte toma 3 de los 4 pallets redondeados; el restante cae
    # fuera de flota. Antes se clonaban 3.85 unidades en ambas partes.
    output, _ = _assign_and_split(headers, rows, [
        {'UNIDAD': '3.5', 'CANTIDAD': 1, 'CAPACIDAD': 3},
    ])

    assert [item['CÓDIGO DE PARADA*'] for item in output] == ['PEDIDO-1', 'PEDIDO-1-1']
    assert sum(float(item['CAPACIDAD UNO']) for item in output) == 3.85
    assert sum(float(item['CAPACIDAD DOS']) for item in output) == 7.7
    assert sum(float(item['COSTO ITEM']) for item in output) == 385
    assert [item['CAPACIDAD UNO'] for item in output] == ['2.8875', '0.9625']


def test_first_torton_turn_maximizes_complete_priority_stores_then_sends_overflow_in_3_5():
    headers = ['CÓDIGO DE PARADA*', 'IDENTIFICADOR CONTACTO*', 'CAPACIDAD UNO', 'Tipo camion']
    rows = [
        {'CÓDIGO DE PARADA*': f'P-{store}', 'IDENTIFICADOR CONTACTO*': store, 'CAPACIDAD UNO': '6'}
        for store in ('A', 'B', 'C', 'D', 'E', 'F')
    ]
    directions = {store.lower(): {'PRIORITY': 1} for store in ('A', 'B', 'C', 'D', 'E')}
    output, _ = _assign_and_split(headers, rows, [
        {'UNIDAD': 'Torton', 'CANTIDAD': 3, 'CAPACIDAD': 8, 'VUELTAS': 2},
        {'UNIDAD': '3.5', 'CANTIDAD': 19, 'CAPACIDAD': 4, 'VUELTAS': 2},
    ], directions)
    truck_by_store = {}
    for item in output:
        store=item['IDENTIFICADOR CONTACTO*'].split('-')[0]
        truck_by_store.setdefault(store,set()).add(item['Tipo camion'])

    assert all(next(iter(truck_by_store[store])).startswith('TORTON_') for store in ('A','B','C'))
    assert truck_by_store['D']=={'3.5'}
    assert truck_by_store['E']=={'3.5'}
    assert truck_by_store['F']=={''}
    assert sum(float(item['CAPACIDAD UNO']) for item in output if item['Tipo camion'].startswith('TORTON_')) == 18


def test_split_controls_use_selected_limit_and_constraint_1_5_remains_blocking():
    headers = ['CÓDIGO DE PARADA*', 'IDENTIFICADOR CONTACTO*', 'CAPACIDAD UNO', 'Tipo camion']
    regular = [{'UNIDAD': '3.5', 'CANTIDAD': 2, 'CAPACIDAD': 4, 'VUELTAS': 1}]
    row = {'CÓDIGO DE PARADA*': 'A', 'IDENTIFICADOR CONTACTO*': 'A', 'CAPACIDAD UNO': '5'}
    split, _ = _assign_and_split(headers, [row], regular, split_orders=True, split_capacity=2)
    assert [float(item['CAPACIDAD UNO']) for item in split] == [2, 2, 1]

    unsplit, _ = _assign_and_split(headers, [row], [{'UNIDAD': '3.5', 'CANTIDAD': 1, 'CAPACIDAD': 8, 'VUELTAS': 1}], split_orders=False)
    assert [float(item['CAPACIDAD UNO']) for item in unsplit] == [4, 1]

    constrained, _ = _assign_and_split(headers, [
        {'CÓDIGO DE PARADA*': 'B', 'IDENTIFICADOR CONTACTO*': 'B', 'CAPACIDAD UNO': '3'},
    ], [{'UNIDAD': '1.5', 'CANTIDAD': 2, 'CAPACIDAD': 2, 'VUELTAS': 1}], {
        'b': {'CONSTRAIN': '1.5'},
    }, split_orders=False)
    assert [float(item['CAPACIDAD UNO']) for item in constrained] == [2, 1]
    assert {item['Tipo camion'] for item in constrained} == {'1.5'}

