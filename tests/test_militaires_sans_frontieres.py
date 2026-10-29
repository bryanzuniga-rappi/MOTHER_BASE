"""Contrato de partición de destinos para la salida de DispatchTrack."""

import io

import openpyxl

from tests._streamlit_stub import install

install()

from modules.militaires_sans_frontieres import (
    DISPATCHTRACK_OUTPUT_HEADERS,
    _assign_and_split,
    _round_down_small_capacity_tail,
    _selected_fleet,
    _cap_final_output_parts,
    _guarantee_priority_torton_coverage,
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
    ], mother_base_routes=True)

    assert [item['CÓDIGO DE PARADA*'] for item in output] == ['PEDIDO-1', 'PEDIDO-1-1']
    assert sum(float(item['CAPACIDAD UNO']) for item in output) == 3.85
    assert sum(float(item['CAPACIDAD DOS']) for item in output) == 7.7
    assert sum(float(item['COSTO ITEM']) for item in output) == 385
    assert [item['CAPACIDAD UNO'] for item in output] == ['2.8875', '0.9625']


def test_first_torton_turn_uses_all_priority_capacity_before_non_priority_filler():
    headers = ['CÓDIGO DE PARADA*', 'IDENTIFICADOR CONTACTO*', 'CAPACIDAD UNO', 'Tipo camion', 'IMPORTANCIA']
    rows = [
        {'CÓDIGO DE PARADA*': f'P-{store}', 'IDENTIFICADOR CONTACTO*': store, 'CAPACIDAD UNO': '6'}
        for store in ('A', 'B', 'C', 'D', 'E', 'F')
    ]
    directions = {store.lower(): {'PRIORITY': 1} for store in ('A', 'B', 'C', 'D', 'E')}
    output, _ = _assign_and_split(headers, rows, [
        {'UNIDAD': 'TORTON_1', 'CANTIDAD': 1, 'CAPACIDAD': 8, 'VUELTAS': 2},
        {'UNIDAD': 'TORTON_2', 'CANTIDAD': 1, 'CAPACIDAD': 8, 'VUELTAS': 2},
        {'UNIDAD': 'TORTON_3', 'CANTIDAD': 1, 'CAPACIDAD': 8, 'VUELTAS': 2},
        {'UNIDAD': '3.5', 'CANTIDAD': 19, 'CAPACIDAD': 4, 'VUELTAS': 2},
    ], directions, mother_base_routes=True)
    truck_by_store = {}
    for item in output:
        store=item['IDENTIFICADOR CONTACTO*'].split('-')[0]
        truck_by_store.setdefault(store,set()).add(item['Tipo camion'])

    assert all(next(iter(truck_by_store[store])).startswith('TORTON_') for store in ('A','B','C'))
    assert {next(iter(truck_by_store[store])) for store in ('A','B','C')} == {'TORTON_1','TORTON_2','TORTON_3'}
    assert all(next(iter(truck_by_store['D'])).startswith('TORTON_') for _ in [0])
    assert truck_by_store['E']=={'3.5'}
    assert all(next(iter(truck_by_store[store])).startswith('TORTON_') for store in ('A','B','C','F'))
    assert sum(float(item['CAPACIDAD UNO']) for item in output if item['Tipo camion'].startswith('TORTON_') and item['IDENTIFICADOR CONTACTO*'].split('-')[0] in {'A','B','C','D'}) == 24
    assert {item['IMPORTANCIA'] for item in output if item['IDENTIFICADOR CONTACTO*'].split('-')[0] in {'A','B','C','D','E'}} == {'1'}
    assert {item['IMPORTANCIA'] for item in output if item['IDENTIFICADOR CONTACTO*'].split('-')[0]=='F'} == {''}


def test_all_selected_tortons_are_dynamic_and_unused_v1_capacity_fills_non_priority():
    headers = ['CÓDIGO DE PARADA*', 'IDENTIFICADOR CONTACTO*', 'CAPACIDAD UNO', 'Tipo camion']
    rows = [
        {'CÓDIGO DE PARADA*':f'P-{store}','IDENTIFICADOR CONTACTO*':store,'CAPACIDAD UNO':'4'}
        for store in ('A','B','C','D')
    ]
    output, _ = _assign_and_split(headers, rows, [
        {'UNIDAD':'TORTON_1','CANTIDAD':1,'CAPACIDAD':8,'VUELTAS':2},
        {'UNIDAD':'TORTON_2','CANTIDAD':1,'CAPACIDAD':8,'VUELTAS':2},
        {'UNIDAD':'TORTON_3','CANTIDAD':1,'CAPACIDAD':8,'VUELTAS':2},
        {'UNIDAD':'TORTON_4','CANTIDAD':1,'CAPACIDAD':8,'VUELTAS':2},
    ], {store.lower():{'PRIORITY':1} for store in ('A','B','C')}, mother_base_routes=False)

    assert {item['Tipo camion'] for item in output} == {'TORTON_1','TORTON_2','TORTON_3','TORTON_4'}


def test_large_priority_store_uses_free_torton_before_non_priority_filler():
    headers=['CÓDIGO DE PARADA*','IDENTIFICADOR CONTACTO*','CAPACIDAD UNO','Tipo camion','IMPORTANCIA']
    rows=[
        {'CÓDIGO DE PARADA*':'ANGEL-8','IDENTIFICADOR CONTACTO*':'ANGEL','CAPACIDAD UNO':'8'},
        {'CÓDIGO DE PARADA*':'ANGEL-4','IDENTIFICADOR CONTACTO*':'ANGEL','CAPACIDAD UNO':'4'},
        {'CÓDIGO DE PARADA*':'B','IDENTIFICADOR CONTACTO*':'B','CAPACIDAD UNO':'4'},
        {'CÓDIGO DE PARADA*':'C','IDENTIFICADOR CONTACTO*':'C','CAPACIDAD UNO':'4'},
        {'CÓDIGO DE PARADA*':'D','IDENTIFICADOR CONTACTO*':'D','CAPACIDAD UNO':'4'},
        {'CÓDIGO DE PARADA*':'N','IDENTIFICADOR CONTACTO*':'N','CAPACIDAD UNO':'3'},
    ]
    fleet=[{'UNIDAD':f'TORTON_{index}','CANTIDAD':1,'CAPACIDAD':8,'VUELTAS':2} for index in range(1,5)]
    directions={store.lower():{'PRIORITY':1} for store in ('ANGEL','B','C','D')}
    output,_=_assign_and_split(headers,rows,fleet,directions,split_orders=False,mother_base_routes=False)
    by_stop={row['CÓDIGO DE PARADA*']:row for row in output}
    assert by_stop['ANGEL-8']['Tipo camion']=='TORTON_4'
    assert by_stop['ANGEL-4']['Tipo camion'] in {'TORTON_1','TORTON_2','TORTON_3'}
    assert by_stop['N']['Tipo camion']==''


def test_routes_off_reserves_torton_capacity_when_priority_store_overflows():
    headers = ['CÓDIGO DE PARADA*', 'IDENTIFICADOR CONTACTO*', 'CAPACIDAD UNO', 'Tipo camion', 'IMPORTANCIA']
    rows = [
        {'CÓDIGO DE PARADA*':'P','IDENTIFICADOR CONTACTO*':'P','CAPACIDAD UNO':'9'},
        {'CÓDIGO DE PARADA*':'N','IDENTIFICADOR CONTACTO*':'N','CAPACIDAD UNO':'3'},
    ]
    output, _ = _assign_and_split(headers, rows, [
        {'UNIDAD':'TORTON_1','CANTIDAD':1,'CAPACIDAD':8,'VUELTAS':2},
        {'UNIDAD':'3.5','CANTIDAD':2,'CAPACIDAD':4,'VUELTAS':1},
    ], {'p':{'PRIORITY':1},'n':{'PRIORITY':0}}, mother_base_routes=False)
    by_store={}
    for item in output:
        by_store.setdefault(item['IDENTIFICADOR CONTACTO*'].split('-')[0],[]).append(item)

    assert {item['Tipo camion'] for item in by_store['P']} == {'TORTON_1',''}
    assert {item['IMPORTANCIA'] for item in by_store['P']} == {'1'}
    assert {item['Tipo camion'] for item in by_store['N']} == {''}
    assert {item['IMPORTANCIA'] for item in by_store['N']} == {''}


def test_final_capacity_cap_never_discards_a_small_remainder():
    headers = ['CÓDIGO DE PARADA*', 'IDENTIFICADOR CONTACTO*', 'CAPACIDAD UNO']
    result = _cap_final_output_parts(headers, [{
        'CÓDIGO DE PARADA*':'A', 'IDENTIFICADOR CONTACTO*':'A', 'CAPACIDAD UNO':'4.05',
    }], 4)

    assert [float(row['CAPACIDAD UNO']) for row in result] == [4,0.05]
    assert sum(float(row['CAPACIDAD UNO']) for row in result) == 4.05


def test_final_priority_coverage_assigns_missing_physical_torton_to_an_untyped_p1_store():
    headers = ['IDENTIFICADOR CONTACTO*', 'CAPACIDAD UNO', 'IMPORTANCIA', 'Tipo camion']
    rows = [
        {'IDENTIFICADOR CONTACTO*':'A','CAPACIDAD UNO':'3','IMPORTANCIA':'1','Tipo camion':'TORTON_1'},
        {'IDENTIFICADOR CONTACTO*':'B','CAPACIDAD UNO':'3','IMPORTANCIA':'1','Tipo camion':'TORTON_3'},
        {'IDENTIFICADOR CONTACTO*':'C','CAPACIDAD UNO':'3','IMPORTANCIA':'1','Tipo camion':''},
    ]
    forced = _guarantee_priority_torton_coverage(headers, rows, [
        {'UNIDAD':'TORTON_1','CAPACIDAD':8},
        {'UNIDAD':'TORTON_2','CAPACIDAD':8},
        {'UNIDAD':'TORTON_3','CAPACIDAD':8},
    ])

    assert forced == ['TORTON_2']
    assert rows[2]['Tipo camion'] == 'TORTON_2'


def test_torton_routes_fill_first_turn_before_second_and_write_delivery_windows():
    headers = [
        'CÓDIGO DE PARADA*', 'IDENTIFICADOR CONTACTO*', 'CAPACIDAD UNO',
        'Tipo camion', 'IMPORTANCIA', 'MIN VENTANA HORARIA 1*', 'MAX VENTANA HORARIA 1*',
    ]
    rows = [
        {'CÓDIGO DE PARADA*':'A','IDENTIFICADOR CONTACTO*':'A','CAPACIDAD UNO':'4'},
        {'CÓDIGO DE PARADA*':'B','IDENTIFICADOR CONTACTO*':'B','CAPACIDAD UNO':'3'},
        {'CÓDIGO DE PARADA*':'C','IDENTIFICADOR CONTACTO*':'C','CAPACIDAD UNO':'5'},
    ]
    output, _ = _assign_and_split(headers, rows, [
        {'UNIDAD':'TORTON_1','CANTIDAD':1,'CAPACIDAD':8,'VUELTAS':2},
        {'UNIDAD':'3.5','CANTIDAD':4,'CAPACIDAD':4,'VUELTAS':2},
    ], {'a':{'PRIORITY':1},'b':{'PRIORITY':0},'c':{'PRIORITY':0}}, mother_base_routes=True)
    by_store={}
    for item in output:
        by_store.setdefault(item['IDENTIFICADOR CONTACTO*'].split('-')[0],[]).append(item)

    for store in ('A','B'):
        assert {item['Tipo camion'] for item in by_store[store]} == {'TORTON_1'}
        assert {(item['MIN VENTANA HORARIA 1*'],item['MAX VENTANA HORARIA 1*']) for item in by_store[store]} == {('00:00','03:00')}
    assert {item['IMPORTANCIA'] for item in by_store['A']} == {'1'}
    assert {item['IMPORTANCIA'] for item in by_store['B']} == {''}
    assert {item['Tipo camion'] for item in by_store['C']} == {'TORTON_1'}
    assert {(item['MIN VENTANA HORARIA 1*'],item['MAX VENTANA HORARIA 1*']) for item in by_store['C']} == {('03:00','06:00')}


def test_split_controls_only_split_when_the_toggle_is_on():
    headers = ['CÓDIGO DE PARADA*', 'IDENTIFICADOR CONTACTO*', 'CAPACIDAD UNO', 'Tipo camion']
    regular = [{'UNIDAD': '3.5', 'CANTIDAD': 2, 'CAPACIDAD': 4, 'VUELTAS': 1}]
    row = {'CÓDIGO DE PARADA*': 'A', 'IDENTIFICADOR CONTACTO*': 'A', 'CAPACIDAD UNO': '5'}
    split, _ = _assign_and_split(headers, [row], regular, split_orders=True, split_capacity=2)
    assert [float(item['CAPACIDAD UNO']) for item in split] == [2, 2, 1]

    unsplit, _ = _assign_and_split(headers, [row], [{'UNIDAD': '3.5', 'CANTIDAD': 1, 'CAPACIDAD': 8, 'VUELTAS': 1}], split_orders=False)
    assert [float(item['CAPACIDAD UNO']) for item in unsplit] == [5]
    oversized_setting, _ = _assign_and_split(headers, [row], [{'UNIDAD': '3.5', 'CANTIDAD': 1, 'CAPACIDAD': 8, 'VUELTAS': 1}], split_orders=True, split_capacity=9)
    assert [float(item['CAPACIDAD UNO']) for item in oversized_setting] == [4, 1]

    constrained, _ = _assign_and_split(headers, [
        {'CÓDIGO DE PARADA*': 'B', 'IDENTIFICADOR CONTACTO*': 'B', 'CAPACIDAD UNO': '3'},
    ], [{'UNIDAD': '1.5', 'CANTIDAD': 2, 'CAPACIDAD': 2, 'VUELTAS': 1}], {
        'b': {'CONSTRAIN': '1.5'},
    }, split_orders=False)
    assert [float(item['CAPACIDAD UNO']) for item in constrained] == [3]
    assert {item['Tipo camion'] for item in constrained} == {'1.5'}


def test_selected_fleet_never_readds_a_torton_removed_from_the_menu():
    fleet=[
        {'UNIDAD':'TORTON','CANTIDAD':1,'CAPACIDAD':8,'VUELTAS':2},
        {'UNIDAD':'TORTON_1','CANTIDAD':1,'CAPACIDAD':8,'VUELTAS':2},
        {'UNIDAD':'TORTON_2','CANTIDAD':1,'CAPACIDAD':8,'VUELTAS':2},
    ]
    selected=_selected_fleet(fleet,['TORTON_1','TORTON_2'])
    assert [item['UNIDAD'] for item in selected] == ['TORTON_1','TORTON_2']


def test_small_capacity_tail_rounds_down_only_above_one_pallet():
    headers=['CÓDIGO DE PARADA*','CAPACIDAD UNO']
    rows=[
        {'CÓDIGO DE PARADA*':'ANGEL','CAPACIDAD UNO':'8.02'},
        {'CÓDIGO DE PARADA*':'LOW','CAPACIDAD UNO':'1.09'},
        {'CÓDIGO DE PARADA*':'TINY','CAPACIDAD UNO':'0.10'},
        {'CÓDIGO DE PARADA*':'KEEP','CAPACIDAD UNO':'3.20'},
    ]
    _round_down_small_capacity_tail(rows,headers)
    assert [row['CAPACIDAD UNO'] for row in rows] == ['8','1','0.10','3.20']

