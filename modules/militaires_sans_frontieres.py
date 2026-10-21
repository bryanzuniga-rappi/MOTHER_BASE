"""Militaires Sans Frontières — primera capa de asignación de rutas."""
from __future__ import annotations
import csv, io, urllib.request
from datetime import datetime
from pathlib import Path
import openpyxl
import streamlit as st
from mother_base_theme import render_system_stamp

def _inject_style():
    st.markdown('<style>.msf-shell{border:3px solid #111;background:#fffdf5;padding:28px;box-shadow:8px 8px 0 #111;margin-bottom:28px}.msf-label{display:inline-block;background:#5f7cff;color:#111;border:3px solid #111;padding:8px 12px;font-weight:800;letter-spacing:.08em}.msf-note{border:2px solid #111;background:#e8edff;padding:14px;margin-top:16px}</style>', unsafe_allow_html=True)

def _secret(name):
    try: return str(st.secrets.get(name, '')).strip()
    except Exception: return ''

def _read_csv_dispatchtrack(uploaded_file):
    rows=list(csv.reader(io.StringIO(uploaded_file.getvalue().decode('utf-8-sig'))))
    if len(rows)<2: raise ValueError('El CSV debe tener marcadores y encabezados.')
    markers,headers=rows[0],rows[1]
    selected=[i for i,v in enumerate(markers) if v.strip()=='DispatchTrack']
    if not selected: raise ValueError('No encontré columnas marcadas como DispatchTrack en la fila 1.')
    names=[headers[i].strip() or f'COLUMNA_{i+1}' for i in selected]
    return names,[{n:(row[i].strip() if i<len(row) else '') for n,i in zip(names,selected)} for row in rows[2:] if any(x.strip() for x in row)]

def _read_excel_dispatchtrack(uploaded_file):
    raw=uploaded_file.getvalue(); wb=openpyxl.load_workbook(io.BytesIO(raw),read_only=True,data_only=True,keep_links=False)
    try: rows=[list(r) for r in wb[wb.sheetnames[0]].iter_rows(values_only=True)]
    finally: wb.close(); del raw
    if not rows: raise ValueError('El Excel está vacío.')
    markers=[str(v or '').strip() for v in rows[0]]
    if 'DispatchTrack' in markers and len(rows)>=2: header,selected,data=rows[1],[i for i,v in enumerate(markers) if v=='DispatchTrack'],rows[2:]
    else: header,selected,data=rows[0],list(range(len(rows[0]))),rows[1:]
    names=[str(header[i] or f'COLUMNA_{i+1}').strip() for i in selected]
    return names,[{n:str(row[i] if i<len(row) and row[i] is not None else '').strip() for n,i in zip(names,selected)} for row in data if any(row)]

def _read_dispatchtrack_file(uploaded_file):
    return _read_csv_dispatchtrack(uploaded_file) if Path(uploaded_file.name).suffix.lower()=='.csv' else _read_excel_dispatchtrack(uploaded_file)

def _load_logistics_book():
    sheet_id=_secret('DATA_LOGISTICS_ID')
    if not sheet_id: raise ValueError('Falta DATA_LOGISTICS_ID en Secrets.')
    with urllib.request.urlopen(f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx',timeout=60) as response: raw=response.read()
    return raw

def _load_fleet():
    raw=_load_logistics_book(); wb=openpyxl.load_workbook(io.BytesIO(raw),read_only=True,data_only=True,keep_links=False)
    try:
        if 'FLOTA' not in wb.sheetnames: raise ValueError('DATA_LOGISTICS no contiene la hoja FLOTA.')
        rows=list(wb['FLOTA'].iter_rows(values_only=True))
    finally: wb.close(); del raw
    headers=[str(v or '').strip().upper() for v in rows[0]]; required={'UNIDAD','CANTIDAD','CAPACIDAD UNO','VUELTAS'}
    if not required.issubset(headers): raise ValueError('FLOTA debe contener UNIDAD, CANTIDAD, CAPACIDAD UNO y VUELTAS.')
    pos={h:headers.index(h) for h in required}; fleet=[]
    for row in rows[1:]:
        try: qty=int(float(row[pos['CANTIDAD']] or 0)); turns=int(float(row[pos['VUELTAS']] or 1)); cap=float(row[pos['CAPACIDAD UNO']] or 0)
        except (TypeError,ValueError): continue
        if qty>0 and turns>0 and cap>0: fleet.append({'UNIDAD':str(row[pos['UNIDAD']]).strip(),'CANTIDAD':qty*turns,'CAPACIDAD':cap})
    if not fleet: raise ValueError('FLOTA no tiene unidades válidas.')
    return sorted(fleet,key=lambda x:float(x['CAPACIDAD']),reverse=True)

def _load_directions():
    raw=_load_logistics_book(); wb=openpyxl.load_workbook(io.BytesIO(raw),read_only=True,data_only=True,keep_links=False)
    try:
        if 'DIRECCIONES' not in wb.sheetnames: return {}
        rows=list(wb['DIRECCIONES'].iter_rows(values_only=True))
    finally: wb.close(); del raw
    if not rows: return {}
    headers=[str(v or '').strip().upper() for v in rows[0]]; pos={h:headers.index(h) for h in headers}
    if 'WAREHOUSE_ID' not in pos: return {}
    result={}
    for row in rows[1:]:
        key=str(row[pos['WAREHOUSE_ID']] or '').strip().replace('.0','')
        if key: result[key]={'CONSTRAIN':str(row[pos['CONSTRAIN']]).strip() if 'CONSTRAIN' in pos and row[pos['CONSTRAIN']] is not None else '', 'PRIORITY':_number(row[pos['PRIORITY']]) if 'PRIORITY' in pos else 0}
    return result

def _number(value):
    if value is None: return 0.0
    text=str(value).strip().replace(',','.')
    if not text or text.lower() in {'none','nan','null'}: return 0.0
    try: return float(text)
    except (TypeError,ValueError): return 0.0


def _assign_and_split(headers,rows,fleet,directions=None):
    directions=directions or {}; cap_header=next((h for h in headers if h.upper()=='CAPACIDAD UNO'),None)
    id_header=next((h for h in headers if h.upper() in {'CÓDIGO DE PARADA*','CODIGO DE PARADA*','TRANSFER ID'}),headers[0])
    origin_header=next((h for h in headers if h.upper() in {'CT ORIGEN*','CT ORIGEN','WAREHOUSE_ID'}),None); type_header=next((h for h in headers if h.upper()=='TIPO CAMION'),None)
    if not cap_header: raise ValueError('El archivo no tiene CAPACIDAD UNO.')
    remaining=[dict(x) for x in fleet]; output=[]; warnings=[]
    for row in rows:
        required=_number(row.get(cap_header,'')); info=directions.get(str(row.get(origin_header,'')).strip().replace('.0',''),{}) if origin_header else {}
        if required<=0: output.append(row); continue
        allowed=str(info.get('CONSTRAIN','')).strip().lower(); candidates=[u for u in remaining if not allowed or str(u['UNIDAD']).strip().lower()==allowed]
        if not candidates: warnings.append(f"{row.get(id_header,'')}: no hay unidad compatible con CONSTRAIN={allowed}."); output.append(row); continue
        candidates=sorted(candidates,key=lambda x:(str(x['UNIDAD']).strip().lower()!='torton',-float(x['CAPACIDAD'])) if info.get('PRIORITY',0)>0 else -float(x['CAPACIDAD']))
        chunks=[]; left=required
        while left>1e-9:
            available=[u for u in candidates if u['CANTIDAD']>0]
            if not available: break
            fitting=[u for u in available if float(u['CAPACIDAD'])<=left+1e-9]
            if fitting:
                unit=max(fitting,key=lambda x:float(x['CAPACIDAD']))
            else:
                # El último camión puede tener más capacidad que el remanente.
                # Esto cubre pedidos pequeños (por ejemplo 0.22) con una unidad 2.
                unit=min(available,key=lambda x:float(x['CAPACIDAD']))
            capacity=float(unit['CAPACIDAD']); chunks.append((capacity,str(unit['UNIDAD']))); unit['CANTIDAD']-=1; left-=capacity
        if left>1e-9: warnings.append(f"{row.get(id_header,'')}: faltan {left:g} unidades de capacidad; no se asignó completamente."); output.append(row); continue
        for index,(capacity,unit_name) in enumerate(chunks):
            clone=dict(row); clone[id_header]=row.get(id_header,'') if index==0 else f"{row.get(id_header,'')}-{index}"; clone[cap_header]=f'{capacity:g}'
            if type_header: clone[type_header]=unit_name
            output.append(clone)
    return output,warnings

def _to_csv(headers,rows):
    output=io.StringIO(newline=''); writer=csv.DictWriter(output,fieldnames=headers,extrasaction='ignore'); writer.writeheader(); writer.writerows(rows); return output.getvalue().encode('utf-8-sig')

def render():
    render_system_stamp('MODULE 02 / MILITAIRES SANS FRONTIÈRES'); _inject_style()
    st.markdown('<section class="mb-hero"><span class="mb-kicker">MODULE / 02 · INTELLIGENCE</span><h1>MILITAIRES SANS<br>FRONTIÈRES.</h1><p>Asignación inicial de pedidos a la flota y preparación de archivos DispatchTrack.</p></section>',unsafe_allow_html=True)
    st.markdown('<div class="msf-shell">',unsafe_allow_html=True); st.markdown('<span class="msf-label">CARGA DE PEDIDOS</span>',unsafe_allow_html=True)
    uploaded=st.file_uploader('Archivo de pedidos',type=['xlsx','xlsm','csv'],accept_multiple_files=False,key='msf_excel_inputs',help='Se conservan únicamente las columnas marcadas como DispatchTrack en la fila 1.')
    run=st.button('EJECUTAR PLANEACIÓN →',type='primary',use_container_width=True,disabled=uploaded is None,key='msf_run_excel_shell')
    st.markdown('<div class="msf-note">La flota se lee desde FLOTA en el Sheet indicado por DATA_LOGISTICS_ID.</div>',unsafe_allow_html=True); st.markdown('</div>',unsafe_allow_html=True)
    if run and uploaded is not None:
        with st.spinner('Leyendo pedidos, FLOTA y asignando unidades…'):
            try: headers,rows=_read_dispatchtrack_file(uploaded); result,warnings=_assign_and_split(headers,rows,_load_fleet(),_load_directions()); csv_bytes=_to_csv(headers,result)
            except Exception as exc: st.error(f'No se pudo ejecutar la planeación: {exc}'); return
        st.success(f'Planeación generada: {len(rows):,} pedidos de entrada → {len(result):,} líneas de salida.')
        for warning in warnings: st.warning(warning)
        st.download_button('DESCARGAR CSV DISPATCHTRACK →',data=csv_bytes,file_name=f'MSF_DISPATCHTRACK_{datetime.now():%Y%m%d_%H%M%S}.csv',mime='text/csv',use_container_width=True,key='msf_download_shell_csv')
    if st.button('← Volver a Mother Base',key='msf_back_home'): st.session_state['mb_module']='MOTHER BASE'; st.rerun()

