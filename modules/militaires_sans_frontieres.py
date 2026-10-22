"""Militaires Sans Frontières — primera capa de asignación de rutas."""
from __future__ import annotations
import csv, io, os, unicodedata, urllib.request
from datetime import datetime
from pathlib import Path
import openpyxl
import streamlit as st
from mother_base_theme import render_system_stamp

def _inject_style():
    st.markdown('<style>.msf-shell{border:3px solid #111;background:#fffdf5;padding:28px;box-shadow:8px 8px 0 #111;margin-bottom:28px}.msf-label{display:inline-block;background:#5f7cff;color:#111;border:3px solid #111;padding:8px 12px;font-weight:800;letter-spacing:.08em}.msf-note{border:2px solid #111;background:#e8edff;padding:14px;margin-top:16px}</style>', unsafe_allow_html=True)

def _secret(name):
    def find(value):
        if isinstance(value, dict):
            for key,item in value.items():
                if str(key).strip().upper()==name.upper() and item not in (None,''):
                    return str(item).strip()
                found=find(item)
                if found: return found
        return ''
    try:
        found=find(st.secrets.to_dict() if hasattr(st.secrets,'to_dict') else st.secrets)
        if found: return found
    except Exception:
        pass
    return os.environ.get(name,'').strip()

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
        data={'CITY':str(row[pos['CITY']]).strip() if 'CITY' in pos and row[pos['CITY']] is not None else '', 'CONSTRAIN':str(row[pos['CONSTRAIN']]).strip() if 'CONSTRAIN' in pos and row[pos['CONSTRAIN']] is not None else '', 'PRIORITY':_number(row[pos['PRIORITY']]) if 'PRIORITY' in pos else 0}
        if key: result[key]=data
        if 'WAREHOUSE_NAME' in pos and row[pos['WAREHOUSE_NAME']]: result[_norm(row[pos['WAREHOUSE_NAME']])]=data
    return result

def _norm(value):
    return ''.join(ch for ch in unicodedata.normalize('NFKD',str(value or '')) if not unicodedata.combining(ch)).strip().casefold()

def _number(value):
    if value is None: return 0.0
    text=str(value).strip().replace(',','.')
    if not text or text.lower() in {'none','nan','null'}: return 0.0
    try: return float(text)
    except (TypeError,ValueError): return 0.0


def _round_pallets(value):
    value=_number(value)
    if value<=0: return 0
    whole=int(value); return max(1,whole+(1 if value-whole>=0.3 else 0))

def _assign_and_split(headers,rows,fleet,directions=None,allowed_cities=None):
    directions=directions or {}; cap_header=next((h for h in headers if h.upper()=='CAPACIDAD UNO'),None)
    id_header=next((h for h in headers if h.upper() in {'CÓDIGO DE PARADA*','CODIGO DE PARADA*','TRANSFER ID'}),headers[0])
    origin_header=next((h for h in headers if h.upper() in {'IDENTIFICADOR CONTACTO*','IDENTIFICADOR CONTACTO','WAREHOUSE_NAME'}),None) or next((h for h in headers if h.upper() in {'CT ORIGEN*','CT ORIGEN','WAREHOUSE_ID'}),None)
    type_header=next((h for h in headers if _norm(h).replace(' ','') in {'tipocamion','tipodecamion'}),None)
    if not cap_header: raise ValueError('El archivo no tiene CAPACIDAD UNO.')
    bins=[]
    for item in fleet:
        for _ in range(int(item['CANTIDAD'])): bins.append({'UNIDAD':item['UNIDAD'],'CAPACIDAD':float(item['CAPACIDAD']),'LIBRE':float(item['CAPACIDAD']),'ORIGEN':None})
    output=[]; warnings=[]; split_counts={}
    ordered=[]
    for row in rows:
        origin=str(row.get(origin_header,'')).strip() if origin_header else ''
        info=dict(directions.get(origin.replace('.0',''),directions.get(_norm(origin),{})))
        info['_STORE']=_norm(origin)
        if allowed_cities and _norm(info.get('CITY','')) not in {_norm(city) for city in allowed_cities}:
            continue
        ordered.append((row,info))
    if not ordered:
        ordered=[(row,{}) for row in rows]
    ordered.sort(key=lambda x:(-float(x[1].get('PRIORITY',0)), _norm(x[1].get('_STORE','')), -_round_pallets(x[0].get(cap_header,''))))
    for row,info in ordered:
        original_capacity=_number(row.get(cap_header,'')); pallets=_round_pallets(original_capacity); left=pallets; original_left=original_capacity
        allowed=_norm(info.get('CONSTRAIN',''))
        while left>0:
            if info.get('PRIORITY',0)>0:
                candidates=[b for b in bins if b['LIBRE']>=1 and _norm(b['UNIDAD'])=='torton']
                candidates.sort(key=lambda b:(0 if b.get('ORIGEN')==info.get('_STORE') else 1,b['LIBRE']))
            else:
                candidates=[b for b in bins if b['LIBRE']>=1 and (not allowed or _norm(b['UNIDAD'])==allowed)]
                if allowed=='1.5': candidates.sort(key=lambda b:(0 if _norm(b['UNIDAD'])=='1.5' else 1,b['LIBRE']))
                else: candidates.sort(key=lambda b:(0 if b.get('ORIGEN')==info.get('_STORE') else 1,-b['CAPACIDAD']))
            if not candidates:
                warnings.append(f"{row.get(id_header,'')}: faltan {left} pallets; no se asignó completamente."); break
            bin_=candidates[0]; amount=min(left,4,int(bin_['LIBRE']))
            clone=dict(row)
            base_id=str(row.get(id_header,'')); split_index=split_counts.get(base_id,0)
            if split_index>0: clone[id_header]=f"{base_id}-{split_index}"
            split_counts[base_id]=split_index+1
            clone[cap_header]=row.get(cap_header,'') if pallets<=4 else (str(min(4,original_left)).rstrip('0').rstrip('.') if original_left>0 else '0'); original_left=max(0,original_left-4); 
            if type_header: clone[type_header]=bin_['UNIDAD']
            output.append(clone); bin_['ORIGEN']=info.get('_STORE'); bin_['LIBRE']-=amount; left-=amount
    return output,warnings

def _to_csv(headers,rows):
    output=io.StringIO(newline=''); writer=csv.DictWriter(output,fieldnames=headers,extrasaction='ignore'); writer.writeheader(); writer.writerows(rows); return output.getvalue().encode('utf-8-sig')

def render():
    render_system_stamp('MODULE 02 / MILITAIRES SANS FRONTIÈRES'); _inject_style()
    st.markdown('<section class="mb-hero"><span class="mb-kicker">MODULE / 02 · INTELLIGENCE</span><h1>MILITAIRES SANS<br>FRONTIÈRES.</h1><p>Asignación inicial de pedidos a la flota y preparación de archivos DispatchTrack.</p></section>',unsafe_allow_html=True)
    st.markdown('<div class="msf-shell">',unsafe_allow_html=True); st.markdown('<span class="msf-label">CARGA DE PEDIDOS</span>',unsafe_allow_html=True)
    try:
        fleet_config=_load_fleet(); direction_config=_load_directions()
        cities=sorted({str(v.get('CITY','')).strip() for v in direction_config.values() if v.get('CITY')})
        units=sorted({str(v.get('UNIDAD','')).strip() for v in fleet_config if v.get('UNIDAD')})
    except Exception as exc:
        st.error(f'No se pudo leer DATA_LOGISTICS: {exc}'); fleet_config=[]; direction_config={}; cities=[]; units=[]
    with st.expander('CONFIGURACIÓN DE PLANEACIÓN',expanded=True):
        c1,c2=st.columns(2)
        selected_cities=c1.multiselect('Ciudades',cities,default=cities,key='msf_cities')
        selected_units=c2.multiselect('Unidades disponibles',units,default=units,key='msf_units')
        c3,c4=st.columns(2)
        use_constraints=c3.checkbox('Aplicar CONSTRAIN por tienda',value=True,key='msf_constraints')
        prioritize=c4.checkbox('Priorizar tiendas con PRIORITY usando Torton',value=True,key='msf_priority')
    uploaded=st.file_uploader('Archivo de pedidos',type=['xlsx','xlsm','csv'],accept_multiple_files=False,key='msf_excel_inputs',help='Se conservan únicamente las columnas marcadas como DispatchTrack en la fila 1.')
    run=st.button('EJECUTAR PLANEACIÓN →',type='primary',use_container_width=True,disabled=uploaded is None,key='msf_run_excel_shell')
    st.markdown('<div class="msf-note">La configuración se lee desde FLOTA y DIRECCIONES en DATA_LOGISTICS.</div>',unsafe_allow_html=True); st.markdown('</div>',unsafe_allow_html=True)
    if run and uploaded is not None:
        with st.spinner('Leyendo pedidos, FLOTA y asignando unidades…'):
            try:
                headers,rows=_read_dispatchtrack_file(uploaded)
                filtered_fleet=[u for u in fleet_config if u['UNIDAD'] in selected_units]
                filtered_directions={k:dict(v) for k,v in direction_config.items() if (not selected_cities or _norm(v.get('CITY','')) in {_norm(city) for city in selected_cities}) and (use_constraints or not v.get('CONSTRAIN'))}
                if not prioritize:
                    for value in filtered_directions.values(): value['PRIORITY']=0
                result,warnings=_assign_and_split(headers,rows,filtered_fleet,filtered_directions,selected_cities); csv_bytes=_to_csv(headers,result)
            except Exception as exc: st.error(f'No se pudo ejecutar la planeación: {exc}'); return
        st.success(f'Planeación generada: {len(rows):,} pedidos de entrada → {len(result):,} líneas de salida.')
        for warning in warnings: st.warning(warning)
        st.download_button('DESCARGAR CSV DISPATCHTRACK →',data=csv_bytes,file_name=f'MSF_DISPATCHTRACK_{datetime.now():%Y%m%d_%H%M%S}.csv',mime='text/csv',use_container_width=True,key='msf_download_shell_csv')
    if st.button('← Volver a Mother Base',key='msf_back_home'): st.session_state['mb_module']='MOTHER BASE'; st.rerun()






