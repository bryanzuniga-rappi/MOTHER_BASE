"""Dashboard de comando AVL/SWA para Militaires Sans Frontières (Mother Base)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
import html
import io
import re
import urllib.error
import urllib.request
import zipfile

import openpyxl
import polars as pl
import plotly.graph_objects as go
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build as build_drive_service
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from mother_base_theme import render_system_stamp
from modules.les_enfants_terribles import render_capped_dataframe, rows_to_csv_bytes


def configured_data_dashboard_spreadsheet_id() -> str:
    """Lee el ID del Google Sheet DATA_DASHBOARD desde Streamlit Secrets.

    Igual que DATA_TRANSFERS_SPREADSHEET_ID en les_enfants_terribles.py: no
    hardcodear el ID real en el código fuente de un repo compartido. Ver
    .streamlit/secrets.toml.example.
    """
    try:
        return str(st.secrets.get("DATA_DASHBOARD_SPREADSHEET_ID", ""))
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Google Drive — snapshots diarios crudos + rollup histórico acumulado
# ---------------------------------------------------------------------------
#
# Un solo folder de Drive compartido guarda dos tipos de archivo, ambos
# planos (sin subcarpetas, para no depender de lógica extra de find-or-create
# de carpetas):
#   - "RAW_YYYY-MM-DD.csv": la subida cruda de ese día, tal cual. Si se sube
#     dos veces el mismo día, la segunda SOBREESCRIBE la primera (gana la
#     última subida del día).
#   - "ROLLUP.csv": un solo archivo que acumula un resumen por día, usado
#     para la tendencia histórica. Cada subida le agrega/actualiza la fila
#     de ese día, nunca borra días anteriores.
#
# Nada de esto se ha podido probar contra la API real de Google desde este
# entorno (sin acceso a red) — el patrón sigue la documentación oficial de
# google-api-python-client al pie de la letra, pero la primera conexión real
# debe validarla quien lo despliegue (por eso el botón "Probar conexión").

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
RAW_FILENAME_PREFIX = "RAW_"
ROLLUP_FILENAME = "ROLLUP.csv"


def configured_data_dashboard_drive_folder_id() -> str:
    """Lee el ID del folder de Drive compartido desde Streamlit Secrets."""
    try:
        return str(st.secrets.get("DATA_DASHBOARD_DRIVE_FOLDER_ID", ""))
    except Exception:
        return ""


def _drive_service_account_info() -> dict | None:
    """Lee el bloque [gcp_service_account] de Secrets como dict plano.

    A propósito NO atrapa cualquier excepción en silencio: si la tabla
    existe pero algo en ella truena (una llave TOML mal formada, por
    ejemplo), eso debe verse en el mensaje de error real en vez de
    disfrazarse siempre como "falta configurar" — ese mensaje genérico solo
    debe aparecer cuando la tabla de verdad no está.
    """
    try:
        available_keys = list(st.secrets.keys())
    except Exception as exc:
        raise RuntimeError(
            f"No pude leer Secrets en absoluto (TOML inválido a nivel "
            f"archivo, revisa que todo el secrets.toml tenga sintaxis "
            f"correcta): {exc}"
        ) from exc
    if "gcp_service_account" not in available_keys:
        return None
    try:
        raw = st.secrets["gcp_service_account"]
        return dict(raw)
    except Exception as exc:
        raise RuntimeError(
            "La tabla [gcp_service_account] existe en Secrets, pero no se "
            f"pudo leer correctamente — revisa su formato TOML: {exc}"
        ) from exc


def get_drive_service():
    """Construye el cliente de la API de Drive v3 con la cuenta de servicio.

    Lanza RuntimeError con un mensaje claro (no una excepción críptica de
    Google) si falta cualquier pieza de configuración, para que el error se
    entienda sin tener que leer el traceback.
    """
    info = _drive_service_account_info()
    if not info:
        raise RuntimeError(
            "Falta configurar [gcp_service_account] en Secrets. Ver "
            ".streamlit/secrets.toml.example."
        )
    folder_id = configured_data_dashboard_drive_folder_id()
    if not folder_id:
        raise RuntimeError(
            "Falta configurar DATA_DASHBOARD_DRIVE_FOLDER_ID en Secrets."
        )
    try:
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=DRIVE_SCOPES
        )
    except Exception as exc:
        raise RuntimeError(
            "Las credenciales de [gcp_service_account] no son válidas: "
            f"{exc}"
        ) from exc
    try:
        return build_drive_service(
            "drive", "v3", credentials=credentials, cache_discovery=False
        )
    except Exception as exc:
        raise RuntimeError(f"No pude iniciar el cliente de Drive: {exc}") from exc


def _resolve_shared_drive_id(service, folder_id: str) -> str | None:
    """Devuelve el ID del Drive compartido que contiene ``folder_id``, o
    None si es una carpeta normal de Mi unidad.

    Esto es lo oficialmente recomendado por Google para listar contenido
    de un Drive compartido de forma confiable: ``corpora="drive"`` +
    ``driveId=<id del Drive compartido>`` — NO el ID de la subcarpeta
    (en este proyecto, la carpeta configurada es "SWA", que vive DENTRO
    del Drive compartido "MOTHER-BASE"; son IDs distintos). El intento
    anterior con ``corpora="allDrives"`` sin ``driveId`` no es tan
    confiable — Google la documenta como más lenta/menos consistente que
    apuntar directo al Drive compartido correcto.
    """
    folder = (
        service.files()
        .get(fileId=folder_id, fields="id, driveId", supportsAllDrives=True)
        .execute()
    )
    return folder.get("driveId")


def _drive_list_query(service, folder_id: str, q: str, **list_kwargs) -> dict:
    """Ejecuta ``files().list()`` apuntando correctamente al Drive
    compartido de ``folder_id`` (ver _resolve_shared_drive_id). Centraliza
    esto en un solo lugar para no repetir la resolución de driveId en cada
    función que necesita listar/buscar archivos."""
    drive_id = _resolve_shared_drive_id(service, folder_id)
    kwargs = {
        "q": q,
        "supportsAllDrives": True,
        "includeItemsFromAllDrives": True,
        **list_kwargs,
    }
    if drive_id:
        kwargs["corpora"] = "drive"
        kwargs["driveId"] = drive_id
    else:
        # Carpeta normal de Mi unidad — no hay Drive compartido que resolver.
        kwargs["corpora"] = "user"
    return service.files().list(**kwargs).execute()


def _drive_find_file(service, folder_id: str, filename: str) -> dict | None:
    """Busca un archivo por nombre EXACTO dentro del folder. Devuelve
    {"id", "name", "modifiedTime"} o None. ``supportsAllDrives`` es
    obligatorio para que esto funcione con Drives compartidos, no solo Mi
    unidad — omitirlo es el error más común con este tipo de integración.
    """
    safe_name = filename.replace("'", "\\'")
    query = (
        f"'{folder_id}' in parents and name = '{safe_name}' and trashed = false"
    )
    response = _drive_list_query(
        service,
        folder_id,
        query,
        fields="files(id, name, modifiedTime, properties)",
        pageSize=1,
    )
    files = response.get("files", [])
    return files[0] if files else None


def _drive_list_files(service, folder_id: str, prefix: str = "") -> list[dict]:
    """Lista archivos del folder (opcionalmente filtrados por prefijo de
    nombre), ordenados por nombre descendente — con nombres tipo
    RAW_YYYY-MM-DD.csv, eso equivale a orden cronológico descendente."""
    query = f"'{folder_id}' in parents and trashed = false"
    if prefix:
        safe_prefix = prefix.replace("'", "\\'")
        query += f" and name contains '{safe_prefix}'"
    response = _drive_list_query(
        service,
        folder_id,
        query,
        fields="files(id, name, modifiedTime, properties)",
        orderBy="name desc",
        pageSize=200,
    )
    return response.get("files", [])


def _drive_upload_or_replace(
    service,
    folder_id: str,
    filename: str,
    content_bytes: bytes,
    mime_type: str = "text/csv",
    properties: dict[str, str] | None = None,
) -> str:
    """Crea el archivo si no existe, o sobreescribe su contenido si ya
    existe con ese nombre exacto. Devuelve el file id."""
    existing = _drive_find_file(service, folder_id, filename)
    media = MediaIoBaseUpload(
        io.BytesIO(content_bytes), mimetype=mime_type, resumable=False
    )
    if existing:
        update_kwargs: dict[str, Any] = {
            "fileId": existing["id"],
            "media_body": media,
            "supportsAllDrives": True,
        }
        if properties:
            # No pasar body=None explícito: algunas versiones del cliente
            # intentan serializarlo como metadata real y la API lo rechaza.
            # Si no hay properties nuevas, simplemente se omite el kwarg.
            update_kwargs["body"] = {"properties": properties}
        updated = service.files().update(**update_kwargs).execute()
        return updated["id"]
    metadata: dict[str, Any] = {"name": filename, "parents": [folder_id]}
    if properties:
        metadata["properties"] = properties
    created = (
        service.files()
        .create(body=metadata, media_body=media, supportsAllDrives=True, fields="id")
        .execute()
    )
    return created["id"]


def _drive_download(service, file_id: str) -> bytes:
    """Descarga el contenido completo de un archivo de Drive."""
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    return buffer.getvalue()


def test_direct_file_access(file_id: str) -> str:
    """Diagnóstico: intenta leer un archivo por ID directo (.get + descarga
    de contenido), sin pasar por búsqueda/list en absoluto. Si esto
    funciona mientras "Probar conexión" sigue viendo 0 archivos, confirma
    que el problema es específico de list()/búsqueda (por ejemplo, DLP
    ligado a una etiqueta de clasificación que oculta contenido de
    búsquedas por API pero no bloquea el acceso directo por ID) y no un
    problema de permisos generales de la cuenta de servicio."""
    try:
        service = get_drive_service()
    except RuntimeError as exc:
        return str(exc)
    try:
        metadata = (
            service.files()
            .get(
                fileId=file_id,
                fields="id, name, size, driveId, trashed",
                supportsAllDrives=True,
            )
            .execute()
        )
    except HttpError as exc:
        status = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "resp", None), "status", None
        )
        return (
            f"NO pude acceder al archivo por ID directo (HTTP {status}). "
            "Esto apunta a un bloqueo de permisos/DLP real, no solo de "
            f"búsqueda: {exc}"
        )
    except Exception as exc:
        return f"Error inesperado: {exc}"
    try:
        content = _drive_download(service, file_id)
        content_note = f"Contenido descargado: {len(content):,} bytes."
    except Exception as exc:
        content_note = f"Metadata OK pero la descarga del contenido falló: {exc}"
    return (
        f"Metadata OK por ID directo: '{metadata.get('name')}' "
        f"({metadata.get('size', '?')} bytes reportados, trashed="
        f"{metadata.get('trashed')}). {content_note} — si esto funcionó y "
        '"Probar conexión" sigue en 0, el problema es específico de '
        "list()/búsqueda, no de acceso al archivo en sí."
    )


def test_drive_connection() -> str:
    """Prueba end-to-end mínima: conecta, y confirma que el folder
    configurado existe y es alcanzable. No sube ni descarga nada. Pensada
    para el botón "Probar conexión" — devuelve un mensaje humano, nunca
    lanza una excepción cruda a la UI."""
    try:
        service = get_drive_service()
        folder_id = configured_data_dashboard_drive_folder_id()
        folder = (
            service.files()
            .get(fileId=folder_id, fields="id, name, driveId", supportsAllDrives=True)
            .execute()
        )
        existing_files = _drive_list_files(service, folder_id)
        drive_note = (
            f"Drive compartido detectado (driveId {folder['driveId']})."
            if folder.get("driveId")
            else "Esta carpeta NO está dentro de un Drive compartido (es de "
            "Mi unidad) — confirma que sea la carpeta correcta."
        )
        return (
            f"Conexión OK. Carpeta encontrada: '{folder.get('name', folder_id)}'. "
            f"{len(existing_files)} archivo(s) existente(s) en ella. {drive_note}"
        )
    except HttpError as exc:
        status = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "resp", None), "status", None
        )
        if status == 404:
            return (
                "Conectó con Google, pero no encontró la carpeta — revisa "
                "que DATA_DASHBOARD_DRIVE_FOLDER_ID sea el ID correcto (el "
                "de la URL de la carpeta, no un nombre) y que la cuenta de "
                "servicio esté agregada como miembro del Drive compartido."
            )
        if status == 403:
            return (
                "Conectó con Google, pero el acceso fue rechazado (403) — "
                "confirma que la cuenta de servicio esté agregada al Drive "
                "compartido como Content Manager o superior."
            )
        return f"Error de la API de Drive: {exc}"
    except RuntimeError as exc:
        return str(exc)
    except Exception as exc:
        return f"Error inesperado probando la conexión: {exc}"


def upload_daily_snapshot(
    file_bytes: bytes, filename: str, uploaded_by: str
) -> tuple[str, dict[str, Any]]:
    """Parsea, valida, y sube el snapshot del día a Drive (RAW_<fecha>.csv,
    sobreescribe si ya se subió algo ese mismo día), y actualiza el rollup
    histórico con el resumen de ese día. Devuelve (fecha, resumen_del_día).

    No usa caché — cada subida debe golpear Drive de verdad.
    """
    df = parse_daily_snapshot(file_bytes, filename)
    date_str = snapshot_date(df)
    if not date_str:
        raise SnapshotValidationError("No pude determinar la fecha (columna DATE vacía).")

    service = get_drive_service()
    folder_id = configured_data_dashboard_drive_folder_id()

    raw_csv_bytes = df.write_csv().encode("utf-8")
    uploaded_at = datetime.now(timezone.utc).isoformat()
    _drive_upload_or_replace(
        service,
        folder_id,
        f"{RAW_FILENAME_PREFIX}{date_str}.csv",
        raw_csv_bytes,
        mime_type="text/csv",
        properties={"uploaded_by": uploaded_by, "uploaded_at": uploaded_at},
    )

    rollup_row = build_rollup_row(df, date_str)
    _append_rollup_row(service, folder_id, rollup_row)

    return date_str, rollup_row


def _append_rollup_row(service, folder_id: str, new_row: dict[str, Any]) -> None:
    """Agrega o actualiza la fila de un día en ROLLUP.csv. Si el archivo no
    existe todavía, lo crea con esa sola fila. Si el día ya tenía una fila
    (re-subida del mismo día), la reemplaza en vez de duplicarla."""
    existing = _drive_find_file(service, folder_id, ROLLUP_FILENAME)
    rows: list[dict[str, Any]] = []
    if existing:
        raw = _drive_download(service, existing["id"])
        rows = pl.read_csv(io.BytesIO(raw)).to_dicts()
    rows = [row for row in rows if row.get("FECHA") != new_row["FECHA"]]
    rows.append(new_row)
    rows.sort(key=lambda row: row["FECHA"])
    updated_df = pl.DataFrame(rows)
    _drive_upload_or_replace(
        service, folder_id, ROLLUP_FILENAME, updated_df.write_csv().encode("utf-8")
    )


@st.cache_data(ttl=300, show_spinner=False)
def list_available_snapshot_dates() -> list[str]:
    """Fechas (YYYY-MM-DD) de los snapshots RAW disponibles en Drive, más
    reciente primero."""
    service = get_drive_service()
    folder_id = configured_data_dashboard_drive_folder_id()
    files = _drive_list_files(service, folder_id, prefix=RAW_FILENAME_PREFIX)
    dates = []
    for f in files:
        name = f["name"]
        if name.startswith(RAW_FILENAME_PREFIX) and name.endswith(".csv"):
            dates.append(name[len(RAW_FILENAME_PREFIX):-4])
    return sorted(dates, reverse=True)


@st.cache_data(ttl=300, show_spinner=False)
def read_snapshot_for_date(date_str: str) -> pl.DataFrame:
    """Descarga y parsea el snapshot RAW de una fecha específica."""
    service = get_drive_service()
    folder_id = configured_data_dashboard_drive_folder_id()
    filename = f"{RAW_FILENAME_PREFIX}{date_str}.csv"
    found = _drive_find_file(service, folder_id, filename)
    if not found:
        raise RuntimeError(f"No existe un snapshot subido para {date_str}.")
    raw = _drive_download(service, found["id"])
    return parse_daily_snapshot(raw, filename)


@st.cache_data(ttl=300, show_spinner=False)
def read_rollup_history() -> list[dict]:
    """Lee el rollup histórico completo (chico, un renglón por día) para
    alimentar la tendencia. Lista vacía si todavía no existe."""
    service = get_drive_service()
    folder_id = configured_data_dashboard_drive_folder_id()
    found = _drive_find_file(service, folder_id, ROLLUP_FILENAME)
    if not found:
        return []
    raw = _drive_download(service, found["id"])
    return pl.read_csv(io.BytesIO(raw)).sort("FECHA").to_dicts()


# --- PALETA OBLIGATORIA (Brutalismo táctico de Mother Base) ---
INK = "#111111"
ACID = "#D4FF2A"
BLUE = "#5B7CFA"
CORAL = "#FF5A4A"
ORANGE = "#FFB000"
WHITE = "#FFFDF7"
BG = "#F2EFE6"

# --- Umbrales de semáforo operativo ---
AVL_HEALTHY, AVL_WARNING = 95.0, 90.0
SWA_HEALTHY, SWA_WARNING = 90.0, 80.0

HISTORY_WINDOWS = {"7 DÍAS": 7, "14 DÍAS": 14, "28 DÍAS": 28}


# ---------------------------------------------------------------------------
# Capa de datos
# ---------------------------------------------------------------------------

def _header(value: object) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip().upper())

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_dashboard() -> bytes:
    spreadsheet_id = configured_data_dashboard_spreadsheet_id()
    if not spreadsheet_id:
        raise RuntimeError(
            "Falta configurar DATA_DASHBOARD_SPREADSHEET_ID en Secrets "
            "(.streamlit/secrets.toml en local, o App settings → Secrets en "
            "Streamlit Community Cloud)."
        )
    url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{spreadsheet_id}/export?format=xlsx"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 MotherBase/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(
            "No pude leer DATA_DASHBOARD. Confirma que el Sheet sea público para lectura."
        ) from exc
    if not payload or not zipfile.is_zipfile(io.BytesIO(payload)):
        raise RuntimeError("DATA_DASHBOARD no devolvió un archivo Excel válido.")
    return payload

def _records(workbook, sheet_name: str, required: set[str]):
    if sheet_name not in workbook.sheetnames:
        raise ValueError(f"Falta la hoja {sheet_name!r} en DATA_DASHBOARD.")
    ws = workbook[sheet_name]
    positions = None
    header_row = None
    for idx, row in enumerate(ws.iter_rows(min_row=1, max_row=20, max_col=45, values_only=True), 1):
        found = {_header(value): col for col, value in enumerate(row) if _header(value)}
        if required.issubset(found):
            positions, header_row = found, idx
            break
    if positions is None:
        raise ValueError(f"{sheet_name}: no encontré encabezados {sorted(required)}.")
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        record = {name: row[index] if index < len(row) else None for name, index in positions.items()}
        if any(value is not None and str(value).strip() for value in record.values()):
            yield record

def _number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Snapshot diario de Snowflake (grano producto-tienda) — reemplaza el Sheet
# viejo (CURRENT_DATE/28D) como fuente real. Diseñado para ~200K filas/día:
# todo el procesamiento pesado usa polars, nunca listas de dicts de Python.
# ---------------------------------------------------------------------------

# Columnas que el dashboard necesita sí o sí. Si faltan, se rechaza el
# archivo con un mensaje claro en vez de fallar más adelante con un
# KeyError críptico en medio de una agregación.
SNAPSHOT_REQUIRED_COLUMNS = {
    "DATE", "CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME", "PRODUCT_ID",
    "PRODUCT_NAME", "MACRO_CATEGORY", "CATEGORY", "SUB_CATEGORY", "MAKER",
    "FINAL_PROVEEDOR_NAME", "BLOCKING_REASON", "IS_INFALTABLE", "IS_GOLDEN",
    "IS_ANCHOR", "STOCK_UNITS", "ADU", "AVL_COUNTRY", "SWA_COUNTRY",
    "AVL_CITY", "SWA_CITY", "AVL_WH", "SWA_WH", "COMENTARIO",
}

# Columnas numéricas: se fuerzan a float al leer, cualquier valor no
# parseable (vacío, texto) se vuelve null sin tronar la carga completa.
SNAPSHOT_NUMERIC_COLUMNS = [
    "STOCK_UNITS", "FULL_SALES_28", "FULL_SALES_56", "AVG_SALES", "ADU",
    "AVL_LAST_DAY", "SWA_COUNTRY", "SWA_CITY", "SWA_WH", "SWA_MAKER_COUNTRY",
    "SWA_MAKER_CITY", "SWA_MAKER_WH", "SWA_PROVEEDOR_COUNTRY",
    "SWA_PROVEEDOR_CITY", "SWA_PROVEEDOR_WH", "AVL_COUNTRY", "AVL_CITY",
    "AVL_WH", "AVL_MAKER_COUNTRY", "AVL_MAKER_CITY", "AVL_MAKER_WH",
    "AVL_PROVEEDOR_COUNTRY", "AVL_PROVEEDOR_CITY", "AVL_PROVEEDOR_WH",
    "AVL_28D", "INCOMING_TOTAL", "STOCK_CEDIS_444", "STOCK_CEDIS_831",
    "STOCK_CEDIS_811", "STOCK_CEDIS_834", "INCOMING_CEDIS_TOTAL",
]


class SnapshotValidationError(ValueError):
    """El archivo subido no tiene la forma que el dashboard espera."""


def parse_daily_snapshot(file_bytes: bytes, filename: str) -> pl.DataFrame:
    """Lee el export diario de Snowflake (CSV, el formato real confirmado
    con la muestra) a un DataFrame de polars, valida columnas mínimas y
    normaliza tipos. No agrega ni resume nada — eso lo hacen las funciones
    build_* de abajo, cada una sobre este mismo DataFrame ya limpio."""
    lower_name = filename.lower()
    try:
        if lower_name.endswith((".xlsx", ".xls")):
            df = pl.read_excel(io.BytesIO(file_bytes))
        else:
            df = pl.read_csv(
                io.BytesIO(file_bytes),
                infer_schema_length=0,  # todo string primero; se tipa explícito abajo
                encoding="utf8-lossy",
            )
    except Exception as exc:
        raise SnapshotValidationError(
            f"No pude leer el archivo como CSV/Excel: {exc}"
        ) from exc

    if df.is_empty():
        raise SnapshotValidationError("El archivo no tiene filas.")

    missing = SNAPSHOT_REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise SnapshotValidationError(
            "Al archivo le faltan columnas que el dashboard necesita: "
            f"{', '.join(sorted(missing))}."
        )

    numeric_present = [c for c in SNAPSHOT_NUMERIC_COLUMNS if c in df.columns]
    df = df.with_columns(
        [
            pl.col(c).cast(pl.Float64, strict=False).fill_null(0.0)
            for c in numeric_present
        ]
    )
    for bool_col in ("IS_INFALTABLE", "IS_GOLDEN", "IS_ANCHOR", "IS_BLACKLIST"):
        if bool_col in df.columns:
            df = df.with_columns(
                (pl.col(bool_col).str.to_uppercase() == "YES").alias(bool_col)
            )
    return df


def snapshot_date(df: pl.DataFrame) -> str:
    """La fecha del snapshot, normalizada a YYYY-MM-DD sin importar el
    formato en que Snowflake la exportó (se asume un solo día por archivo,
    que es el contrato acordado con negocio).

    El export real trae DATE como texto "28/09/2026" (DD/MM/YYYY) — nunca
    se debe usar tal cual en el nombre del archivo ni para ordenar: como
    texto libre, "28/09/2026" no ordena cronológicamente contra otras
    fechas (compara caracter por caracter, no como fecha), y las diagonales
    además rompen la convención de nombre de archivo del resto del código.
    """
    values = df.get_column("DATE").unique().to_list()
    if not values:
        return ""
    raw = str(values[0]).strip()
    candidate_formats = ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y")
    for fmt in candidate_formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise SnapshotValidationError(
        f"No reconozco el formato de la columna DATE: {raw!r}. Formatos "
        "soportados: DD/MM/AAAA, AAAA-MM-DD, MM/DD/AAAA, DD-MM-AAAA."
    )


def build_country_kpis(df: pl.DataFrame) -> dict[str, float]:
    """AVL/SWA país: ya vienen calculados y repetidos en cada fila, así que
    basta con tomar el primer valor no nulo, no hay que promediar nada."""
    if df.is_empty():
        return {"AVL_COUNTRY": 0.0, "SWA_COUNTRY": 0.0}
    first = df.row(0, named=True)
    return {
        "AVL_COUNTRY": _number(first.get("AVL_COUNTRY")),
        "SWA_COUNTRY": _number(first.get("SWA_COUNTRY")),
    }


def build_city_breakdown(df: pl.DataFrame) -> list[dict]:
    """Una fila por CITY con su AVL/SWA ya calculado (mismo insumo que
    antes alimentaba el waterfall) — compatible tal cual con
    _build_waterfall, que espera CITY + SWA_CITY."""
    if df.is_empty():
        return []
    grouped = (
        df.group_by("CITY")
        .agg(pl.col("AVL_CITY").first(), pl.col("SWA_CITY").first())
        .sort("SWA_CITY")
    )
    return grouped.to_dicts()


def build_blocking_reason_breakdown(df: pl.DataFrame) -> list[dict]:
    """Cuántas líneas caen en cada BLOCKING_REASON, con un comentario de
    ejemplo real para dar contexto sin tener que abrir el detalle."""
    if df.is_empty():
        return []
    grouped = (
        df.filter(pl.col("BLOCKING_REASON").is_not_null())
        .group_by("BLOCKING_REASON")
        .agg(
            pl.len().alias("LINEAS"),
            pl.col("COMENTARIO").drop_nulls().first().alias("EJEMPLO_COMENTARIO"),
        )
        .sort("LINEAS", descending=True)
    )
    return grouped.to_dicts()


def build_stockout_rate_breakdown(df: pl.DataFrame, group_col: str) -> list[dict]:
    """% de líneas con STOCK_UNITS = 0 por categoría/maker/proveedor.

    Deliberadamente NO se llama SWA: SWA por país/ciudad/tienda ya viene
    calculado por Snowflake con su propia fórmula de ponderación (por
    venta, seguramente), pero esa fórmula no existe a nivel categoría/maker/
    proveedor en los datos que llegan — inventarla aquí sería adivinar un
    número que alguien podría tomar como oficial. Este es un proxy honesto
    y 100% verificable: cuántas líneas están literalmente en cero.
    """
    if df.is_empty() or group_col not in df.columns:
        return []
    grouped = (
        df.group_by(group_col)
        .agg(
            pl.len().alias("LINEAS_TOTALES"),
            (pl.col("STOCK_UNITS") <= 0).sum().alias("LINEAS_EN_QUIEBRE"),
        )
        .with_columns(
            (pl.col("LINEAS_EN_QUIEBRE") / pl.col("LINEAS_TOTALES") * 100)
            .round(1)
            .alias("PCT_EN_QUIEBRE")
        )
        .sort("PCT_EN_QUIEBRE", descending=True)
    )
    return grouped.to_dicts()


def build_drilldown_rows(
    df: pl.DataFrame,
    *,
    city: str | None = None,
    macro_category: str | None = None,
    maker: str | None = None,
    proveedor: str | None = None,
    only_blocked: bool = False,
    only_golden_infaltable_anchor: bool = False,
) -> list[dict]:
    """Detalle producto-tienda filtrado — esto es lo que responde "¿dónde
    exactamente está el problema?". Se filtra en polars (rápido incluso con
    200K filas) y el resultado ya capado (render_capped_dataframe) es lo
    único que se manda al navegador."""
    result = df
    if city:
        result = result.filter(pl.col("CITY") == city)
    if macro_category:
        result = result.filter(pl.col("MACRO_CATEGORY") == macro_category)
    if maker:
        result = result.filter(pl.col("MAKER") == maker)
    if proveedor:
        result = result.filter(pl.col("FINAL_PROVEEDOR_NAME") == proveedor)
    if only_blocked:
        result = result.filter(pl.col("BLOCKING_REASON").is_not_null())
    if only_golden_infaltable_anchor:
        result = result.filter(
            pl.col("IS_GOLDEN") | pl.col("IS_INFALTABLE") | pl.col("IS_ANCHOR")
        )
    columns = [
        "CITY", "WAREHOUSE_NAME", "PRODUCT_ID", "PRODUCT_NAME",
        "MACRO_CATEGORY", "MAKER", "FINAL_PROVEEDOR_NAME", "STOCK_UNITS",
        "ADU", "SWA_WH", "AVL_WH", "BLOCKING_REASON", "COMENTARIO",
    ]
    columns = [c for c in columns if c in result.columns]
    return result.select(columns).sort("SWA_WH").to_dicts()


def build_rollup_row(df: pl.DataFrame, date_str: str) -> dict[str, Any]:
    """Una sola fila resumen del día completo, para acumular en el rollup
    histórico de Drive. Grano: un día = una fila (tendencia país)."""
    kpis = build_country_kpis(df)
    return {
        "FECHA": date_str,
        "AVL": round(kpis["AVL_COUNTRY"], 2),
        "SWA": round(kpis["SWA_COUNTRY"], 2),
        "FILAS": df.height,
    }


@st.cache_data(ttl=300, show_spinner=False)
def _load_metrics(payload: bytes) -> tuple[list[dict], list[dict]]:
    wb = openpyxl.load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    try:
        current = list(_records(
            wb, "CURRENT_DATE",
            {"CITY", "WAREHOUSE_ID", "AVL_COUNTRY", "SWA_COUNTRY", "AVL_CITY", "SWA_CITY", "AVL_WH", "SWA_WH"},
        ))
        history = list(_records(
            wb, "28D",
            {"MAIN_DATE", "CITY", "WAREHOUSE_ID", "WAREHOUSE_NAME", "BUCKET_TYPE", "AVL", "SWA"},
        ))
    finally:
        wb.close()
    return current, history


# ---------------------------------------------------------------------------
# Visual & CSS Agresivo (Estricto Mother Base Brutalism)
# ---------------------------------------------------------------------------

def _inject_style() -> None:
    st.markdown(
        f"""
        <style>
        /* 1. Fondo general beige papel cálido con CUADRÍCULA MUY SUTIL */
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
            background-color: {BG} !important;
            background-image: 
                linear-gradient(rgba(17, 17, 17, 0.04) 1px, transparent 1px),
                linear-gradient(90deg, rgba(17, 17, 17, 0.04) 1px, transparent 1px) !important;
            background-size: 20px 20px !important;
        }}

        /* 2. Forzar alineación a la izquierda y eliminar centrados automáticos */
        [data-testid="stVerticalBlock"] {{
            align-items: flex-start !important;
            text-align: left !important;
        }}

        /* 3. Títulos grandes, negros, pesados */
        h1, h2, h3, h4, h5, h6 {{
            font-family: "Archivo Black", sans-serif !important;
            text-transform: uppercase !important;
            color: {INK} !important;
            text-align: left !important;
            margin-top: 1.5rem !important;
            margin-bottom: 1rem !important;
        }}

        /* 4. Textos estándar en Mono */
        p, span, div, label {{
            font-family: "IBM Plex Mono", monospace !important;
            text-align: left;
            color: {INK};
        }}

        /* 5. Contenedores de Filtros (Nativos de Streamlit override) */
        .st-key-msf_filters [data-testid="stVerticalBlockBorderWrapper"],
        .st-key-msf_history [data-testid="stVerticalBlockBorderWrapper"] {{
            background: {WHITE} !important;
            border: 3px solid {INK} !important;
            border-radius: 0px !important; /* BRUTALISMO: Sin bordes redondeados */
            box-shadow: 7px 7px 0 {INK} !important;
            padding: 15px !important;
        }}

        /* 6. Estilo de Filtros (Selectbox nativo) */
        .stSelectbox label p {{
            font-weight: 800 !important;
            font-size: 0.8rem !important;
            text-transform: uppercase !important;
            letter-spacing: 0.05em !important;
        }}
        div[data-baseweb="select"] > div {{
            background-color: {WHITE} !important;
            border: 3px solid {INK} !important;
            border-radius: 0px !important;
            box-shadow: 4px 4px 0 {INK} !important;
            color: {INK} !important;
            font-weight: 700 !important;
        }}

        /* 7. Botón de Acción Brutalista (Rectangular, verde ácido) */
        .stButton > button {{
            background-color: {ACID} !important;
            color: {INK} !important;
            border: 3px solid {INK} !important;
            border-radius: 0px !important; /* Rectangular obligatorio */
            box-shadow: 5px 5px 0 {INK} !important;
            font-weight: 900 !important;
            text-transform: uppercase !important;
            font-size: 0.9rem !important;
            padding: 0.5rem 1rem !important;
            transition: all 0.1s ease !important;
            width: 100% !important;
        }}
        .stButton > button:active {{
            transform: translate(3px, 3px) !important;
            box-shadow: 2px 2px 0 {INK} !important;
        }}
        .stButton > button p {{
            font-family: "IBM Plex Mono", monospace !important;
            font-weight: 900 !important;
            margin: 0 !important;
            text-align: center !important; /* Única excepción: texto del botón centrado internamente */
        }}

        /* 8. Tarjetas HTML (Insights y Tablas) */
        .mb-card-solid {{
            background: {WHITE};
            border: 3px solid {INK};
            box-shadow: 7px 7px 0 {INK};
            padding: 20px;
            margin-bottom: 20px;
            color: {INK};
            border-radius: 0px;
        }}
        .mb-card-solid:hover {{
            transform: translate(-2px, -2px);
            box-shadow: 9px 9px 0 {INK};
            transition: all 0.15s ease;
        }}

        /* 9. Microcopy */
        .msf-note {{
            font-size: 0.75rem !important;
            font-weight: 600;
            opacity: 0.8;
            margin: 8px 0 4px 0;
            text-transform: uppercase;
        }}

        /* 10. KPIs Grandes */
        .msf-kpi-row {{ display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 25px; width: 100%; }}
        .msf-kpi {{ 
            position: relative; flex: 1 1 200px; 
            background: {WHITE};
            border: 3px solid {INK};
            box-shadow: 7px 7px 0 {INK};
            padding: 20px;
            border-radius: 0px;
        }}
        .msf-kpi-label {{
            display: block;
            font-weight: 800;
            font-size: 0.8rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 12px;
            color: {INK};
        }}
        .msf-kpi-value {{
            font-family: "Archivo Black", sans-serif !important;
            font-size: 3rem;
            line-height: 1;
            display: block;
        }}
        .kpi-acid .msf-kpi-value {{ color: {ACID}; -webkit-text-stroke: 2px {INK}; }}
        .kpi-blue .msf-kpi-value {{ color: {BLUE}; -webkit-text-stroke: 2px {INK}; }}

        /* Tooltips nativos CSS */
        .msf-kpi[data-tip]::after {{
            content: attr(data-tip);
            position: absolute;
            left: 0;
            top: calc(100% + 12px);
            z-index: 50;
            width: max-content;
            max-width: 300px;
            background: {INK};
            color: {WHITE};
            font-size: 0.75rem;
            padding: 12px;
            border: 3px solid {INK};
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
            transition: opacity 0.15s ease, visibility 0.15s ease;
        }}
        .msf-kpi[data-tip]:hover::after {{
            opacity: 1;
            visibility: visible;
            transition-delay: 0.8s;
        }}

        /* 11. Tablas Operativas Brutalistas */
        table.msf-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }}
        table.msf-table th {{
            background: {INK};
            color: {WHITE};
            text-transform: uppercase;
            padding: 12px;
            border: 3px solid {INK};
            font-weight: 800;
        }}
        table.msf-table td {{
            background: {WHITE};
            color: {INK};
            padding: 12px;
            border: 3px solid {INK};
            font-weight: 600;
        }}

        /* 12. Badges/Chips tácticos */
        .msf-badge {{
            display: inline-block;
            font-weight: 900;
            padding: 2px 8px;
            border: 2px solid {INK};
            font-size: 0.7rem;
            text-transform: uppercase;
            color: {INK};
        }}
        .bg-ok {{ background: {ACID}; }}
        .bg-warn {{ background: {ORANGE}; }}
        .bg-crit {{ background: {CORAL}; }}
        .bg-blue {{ background: {BLUE}; }}

        .msf-error-card {{
            background: {CORAL};
            border: 3px solid {INK};
            box-shadow: 7px 7px 0 {INK};
            padding: 20px;
            font-weight: 800;
            color: {INK};
            margin-bottom: 20px;
            border-radius: 0px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def _status(value: float, healthy: float, warning: float) -> tuple[str, str]:
    if value >= healthy: return "SANO", "bg-ok"
    if value >= warning: return "RIESGO", "bg-warn"
    return "CRÍTICO", "bg-crit"

def _kpi_card(label: str, value: str, tooltip: str, color_class: str) -> str:
    return (
        f'<div class="msf-kpi {color_class}" data-tip="{html.escape(tooltip)}">'
        f'<span class="msf-kpi-label">{html.escape(label)}</span>'
        f'<span class="msf-kpi-value">{html.escape(value)}</span>'
        f"</div>"
    )

# --- Gráficos Plotly Brutalistas ---
def _build_waterfall(current_data, overall_swa):
    city_swa = {}
    for row in current_data:
        city = str(row.get("CITY") or "").strip()
        val = _number(row.get("SWA_CITY"))
        if city and val > 0 and city not in city_swa:
            city_swa[city] = val
            
    if not city_swa or overall_swa >= 100:
        return None
        
    sorted_cities = sorted(city_swa.items(), key=lambda x: x[1])
    total_drop = 100.0 - overall_swa
    
    gaps = {c: 100.0 - v for c, v in sorted_cities}
    sum_gaps = sum(gaps.values())
    impacts = {c: (g / sum_gaps) * total_drop for c, g in gaps.items()} if sum_gaps > 0 else {}
    
    top_4 = list(impacts.items())[:4]
    others_impact = sum(v for k, v in list(impacts.items())[4:])
    
    x, y, measure, text = ["SWA IDEAL"], [100.0], ["absolute"], ["100%"]
    
    for c, imp in top_4:
        x.append(c)
        y.append(-imp)
        measure.append("relative")
        text.append(f"-{imp:.1f}%")
        
    if others_impact > 0:
        x.append("OTROS")
        y.append(-others_impact)
        measure.append("relative")
        text.append(f"-{others_impact:.1f}%")
        
    x.append("SWA ACTUAL")
    y.append(overall_swa)
    measure.append("total")
    text.append(f"{overall_swa:.1f}%")
    
    fig = go.Figure(go.Waterfall(
        name="SWA Bridge", orientation="v", measure=measure, x=x, y=y,
        textposition="outside", text=text,
        connector={"line": {"color": INK, "width": 3}},
        decreasing={"marker": {"color": CORAL, "line": {"color": INK, "width": 3}}},
        increasing={"marker": {"color": ACID, "line": {"color": INK, "width": 3}}},
        totals={"marker": {"color": BLUE, "line": {"color": INK, "width": 3}}}
    ))
    
    fig.update_layout(
        font_family="IBM Plex Mono", font_color=INK,
        plot_bgcolor=WHITE, paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=10, t=20, b=20),
        yaxis=dict(range=[min(overall_swa - 5, 50), 105], showgrid=True, gridcolor='rgba(17,17,17,0.1)', zeroline=False),
        xaxis=dict(showgrid=False, linecolor=INK, linewidth=3),
        shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color=INK, width=3))]
    )
    return fig

def _build_trend(trend_window):
    df = pl.DataFrame(trend_window)
    fig = go.Figure()
    
    fechas = df["FECHA"].to_list()
    avl_vals = df["AVL"].to_list()
    swa_vals = df["SWA"].to_list()
    
    fig.add_trace(go.Scatter(
        x=fechas, y=avl_vals, name="AVL", mode='lines+markers',
        line=dict(color=ACID, width=4), marker=dict(size=8, color=ACID, line=dict(width=3, color=INK))
    ))
    fig.add_trace(go.Scatter(
        x=fechas, y=swa_vals, name="SWA", mode='lines+markers',
        line=dict(color=BLUE, width=4), marker=dict(size=8, color=BLUE, line=dict(width=3, color=INK))
    ))
    
    fig.update_layout(
        font_family="IBM Plex Mono", font_color=INK,
        plot_bgcolor=WHITE, paper_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=10, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(showgrid=True, gridcolor='rgba(17,17,17,0.1)', linecolor=INK, linewidth=3),
        yaxis=dict(showgrid=True, gridcolor='rgba(17,17,17,0.1)', linecolor=INK, linewidth=3),
        shapes=[dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=1, y1=1, line=dict(color=INK, width=3))]
    )
    return fig


# ---------------------------------------------------------------------------
# Render principal
# ---------------------------------------------------------------------------

def render() -> None:
    render_system_stamp("MODULE 02 / INTELLIGENCE")
    _inject_style()

    st.markdown(
        """
        <section class="mb-hero" style="margin-bottom: 30px;">
            <span class="msf-badge bg-ok" style="margin-bottom:15px; display:inline-block;">MILITAIRES SANS FRONTIÈRES</span>
            <h1 style="font-size: 3.5rem; line-height: 0.9; margin: 0 0 15px 0;">NETWORK<br>PERFORMANCE.</h1>
            <p style="font-size: 1rem; max-width: 650px; font-weight: 600;">Control táctico de disponibilidad (AVL), impacto de quiebres (SWA) y detalle producto-tienda para saber exactamente qué accionar.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    is_big_boss = st.session_state.get("mb_profile") == "BIG BOSS"

    if is_big_boss:
        with st.expander("🔧 Conexión a Drive (diagnóstico)", expanded=False):
            st.caption(
                "Prueba que la cuenta de servicio pueda alcanzar el Drive "
                "compartido configurado, sin subir ni descargar nada todavía."
            )
            if st.button("Probar conexión", key="msf_test_drive_connection"):
                with st.spinner("Probando conexión con Drive…"):
                    result_message = test_drive_connection()
                if result_message.startswith("Conexión OK"):
                    st.success(result_message)
                else:
                    st.error(result_message)

            st.divider()
            st.caption(
                "Diagnóstico extra: prueba leer UN archivo por su ID directo "
                "(clic derecho en el archivo en Drive → 'Obtener enlace' → "
                "el ID es la parte entre /d/ y /view o /edit del enlace). "
                "Esto no es sensible, solo identifica el archivo."
            )
            direct_file_id = st.text_input(
                "ID del archivo a probar", key="msf_direct_file_id"
            )
            if st.button("Probar acceso directo por ID", key="msf_test_direct_access"):
                if not direct_file_id.strip():
                    st.warning("Pega un ID de archivo primero.")
                else:
                    with st.spinner("Probando acceso directo…"):
                        direct_result = test_direct_file_access(direct_file_id.strip())
                    if direct_result.startswith("Metadata OK"):
                        st.success(direct_result)
                    else:
                        st.error(direct_result)

        with st.expander("📤 Cargar snapshot diario", expanded=False):
            st.caption(
                "Sube el export de Snowflake del día (CSV). Se guarda "
                "completo en Drive y se agrega un resumen a la tendencia "
                "histórica. Si ya subiste algo hoy, esto lo reemplaza."
            )
            uploaded_file = st.file_uploader(
                "Archivo CSV", type=["csv"], key="msf_snapshot_upload"
            )
            uploader_name = st.text_input(
                "Tu nombre (queda registrado con la carga)",
                key="msf_uploader_name",
            )
            if st.button("Subir a Drive", key="msf_upload_button"):
                if uploaded_file is None:
                    st.warning("Selecciona un archivo primero.")
                elif not uploader_name.strip():
                    st.warning("Escribe tu nombre antes de subir.")
                else:
                    with st.spinner("Subiendo y procesando…"):
                        try:
                            date_str, rollup_row = upload_daily_snapshot(
                                uploaded_file.getvalue(),
                                uploaded_file.name,
                                uploader_name.strip(),
                            )
                        except SnapshotValidationError as exc:
                            st.error(f"Archivo rechazado: {exc}")
                        except Exception as exc:
                            st.error(f"No pude subir el snapshot: {exc}")
                        else:
                            st.success(
                                f"Snapshot del {date_str} subido y procesado "
                                f"({rollup_row['FILAS']:,} filas, AVL "
                                f"{rollup_row['AVL']:.2f}%, SWA "
                                f"{rollup_row['SWA']:.2f}%)."
                            )
                            list_available_snapshot_dates.clear()
                            read_snapshot_for_date.clear()
                            read_rollup_history.clear()
                            st.rerun()

    try:
        available_dates = list_available_snapshot_dates()
    except Exception as exc:
        st.markdown(
            f'<div class="msf-error-card">⚠ No pude listar los snapshots '
            f'disponibles en Drive: {html.escape(str(exc))}</div>',
            unsafe_allow_html=True,
        )
        return

    if not available_dates:
        st.markdown(
            '<div class="msf-error-card">⚠ Todavía no hay ningún snapshot '
            "cargado. Un Big Boss debe subir el primero desde "
            '"Cargar snapshot diario".</div>',
            unsafe_allow_html=True,
        )
        return

    col_date, col_refresh = st.columns([3, 1])
    selected_date = col_date.selectbox(
        "FECHA DEL SNAPSHOT", available_dates, index=0, key="msf_selected_date"
    )
    col_refresh.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
    if col_refresh.button("ACTUALIZAR", key="msf_refresh"):
        list_available_snapshot_dates.clear()
        read_snapshot_for_date.clear()
        read_rollup_history.clear()
        st.rerun()

    with st.spinner("CARGANDO SNAPSHOT…"):
        try:
            df = read_snapshot_for_date(selected_date)
        except Exception as exc:
            st.markdown(
                f'<div class="msf-error-card">⚠ ERROR CRÍTICO: '
                f'{html.escape(str(exc))}</div>',
                unsafe_allow_html=True,
            )
            return

    if df.is_empty():
        st.markdown(
            '<div class="msf-error-card">⚠ El snapshot no tiene filas.</div>',
            unsafe_allow_html=True,
        )
        return

    # --- FILTROS TÁCTICOS ---
    with st.container(border=True, key="msf_filters"):
        col1, col2, col3, col4 = st.columns(4)
        cities = sorted(df.get_column("CITY").drop_nulls().unique().to_list())
        selected_city = col1.selectbox("ZONA OPERATIVA", ["TODAS"] + cities)
        categories = sorted(
            df.get_column("MACRO_CATEGORY").drop_nulls().unique().to_list()
        )
        selected_category = col2.selectbox("CATEGORÍA", ["TODAS"] + categories)
        makers = sorted(df.get_column("MAKER").drop_nulls().unique().to_list())
        selected_maker = col3.selectbox("MAKER", ["TODOS"] + makers)
        proveedores = sorted(
            df.get_column("FINAL_PROVEEDOR_NAME").drop_nulls().unique().to_list()
        )
        selected_proveedor = col4.selectbox("PROVEEDOR", ["TODOS"] + proveedores)

    scoped = df
    if selected_city != "TODAS":
        scoped = scoped.filter(pl.col("CITY") == selected_city)
    if selected_category != "TODAS":
        scoped = scoped.filter(pl.col("MACRO_CATEGORY") == selected_category)
    if selected_maker != "TODOS":
        scoped = scoped.filter(pl.col("MAKER") == selected_maker)
    if selected_proveedor != "TODOS":
        scoped = scoped.filter(pl.col("FINAL_PROVEEDOR_NAME") == selected_proveedor)

    # --- SITUACIÓN ACTUAL (siempre a nivel país completo, sin importar
    # los filtros — los filtros solo acotan las secciones de abajo) ---
    kpis = build_country_kpis(df)
    warehouses_medidos = df.get_column("WAREHOUSE_ID").n_unique()
    avl_country_label = f"{kpis['AVL_COUNTRY']:.2f}%"
    swa_country_label = f"{kpis['SWA_COUNTRY']:.2f}%"
    st.markdown("### SITUACIÓN ACTUAL")
    st.markdown(
        f'<div class="msf-kpi-row">'
        f'{_kpi_card("AVL PAÍS", avl_country_label, "Available: pct de SKUs del catálogo con inventario.", "kpi-acid")}'
        f'{_kpi_card("SWA PAÍS", swa_country_label, "Stockout-Weighted Availability: disponibilidad ponderada por relevancia.", "kpi-blue")}'
        f'{_kpi_card("NODOS MEDIDOS", f"{warehouses_medidos:,}", "Número de tiendas/almacenes en este snapshot.", "")}'
        f'{_kpi_card("LÍNEAS TOTALES", f"{df.height:,}", "Filas producto-tienda en el snapshot completo.", "")}'
        f"</div>",
        unsafe_allow_html=True,
    )

    # --- ANÁLISIS 360 (CHARTS) ---
    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.markdown("### ANÁLISIS DE BRECHA (SWA POR CIUDAD)")
        city_data = build_city_breakdown(df)
        fig_waterfall = _build_waterfall(city_data, kpis["SWA_COUNTRY"])
        if fig_waterfall:
            st.plotly_chart(fig_waterfall, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown('<div class="mb-card-solid">Red SWA al 100% o sin datos suficientes.</div>', unsafe_allow_html=True)

    with col_chart2:
        st.markdown("### TENDENCIA (acumulada por cada subida)")
        rollup = read_rollup_history()
        if len(rollup) >= 2:
            st.plotly_chart(_build_trend(rollup[-28:]), use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown(
                '<div class="mb-card-solid">Necesitas al menos 2 días subidos '
                "para que se vea la tendencia — sube el snapshot de mañana "
                "para empezar a verla.</div>",
                unsafe_allow_html=True,
            )

    # --- MOTIVOS DE BLOQUEO ---
    st.markdown("### MOTIVOS DE BLOQUEO")
    reason_rows = build_blocking_reason_breakdown(scoped)
    if reason_rows:
        render_capped_dataframe(
            reason_rows,
            key="msf_blocking_reasons",
            offer_download=True,
            file_label=f"motivos_bloqueo_{selected_date}",
        )
    else:
        st.markdown('<div class="mb-card-solid">Sin líneas bloqueadas en este filtro.</div>', unsafe_allow_html=True)

    # --- % EN QUIEBRE POR CATEGORÍA / MAKER / PROVEEDOR ---
    st.markdown("### % EN QUIEBRE (proxy directo, no es SWA)")
    st.caption(
        "SWA por país/ciudad/tienda ya viene calculado por Snowflake con su "
        "propia fórmula de ponderación por venta. Esa fórmula no existe a "
        "nivel categoría/maker/proveedor en los datos que llegan, así que "
        "esto NO es SWA — es el % de líneas con 0 unidades de stock, un "
        "número 100% verificable a partir de STOCK_UNITS."
    )
    tab_cat, tab_maker, tab_prov = st.tabs(["CATEGORÍA", "MAKER", "PROVEEDOR"])
    with tab_cat:
        render_capped_dataframe(
            build_stockout_rate_breakdown(scoped, "MACRO_CATEGORY"),
            key="msf_stockout_category",
            offer_download=True,
            file_label=f"quiebre_por_categoria_{selected_date}",
        )
    with tab_maker:
        render_capped_dataframe(
            build_stockout_rate_breakdown(scoped, "MAKER"),
            key="msf_stockout_maker",
            offer_download=True,
            file_label=f"quiebre_por_maker_{selected_date}",
        )
    with tab_prov:
        render_capped_dataframe(
            build_stockout_rate_breakdown(scoped, "FINAL_PROVEEDOR_NAME"),
            key="msf_stockout_proveedor",
            offer_download=True,
            file_label=f"quiebre_por_proveedor_{selected_date}",
        )

    # --- DETALLE PRODUCTO-TIENDA: "¿dónde exactamente está el problema?" ---
    st.markdown("### DETALLE PRODUCTO-TIENDA")
    col_flag1, col_flag2 = st.columns(2)
    only_blocked = col_flag1.checkbox("Solo líneas con motivo de bloqueo", key="msf_only_blocked")
    only_gia = col_flag2.checkbox("Solo Golden/Infaltable/Anchor", key="msf_only_gia")
    drilldown_rows = build_drilldown_rows(
        df,
        city=None if selected_city == "TODAS" else selected_city,
        macro_category=None if selected_category == "TODAS" else selected_category,
        maker=None if selected_maker == "TODOS" else selected_maker,
        proveedor=None if selected_proveedor == "TODOS" else selected_proveedor,
        only_blocked=only_blocked,
        only_golden_infaltable_anchor=only_gia,
    )
    render_capped_dataframe(
        drilldown_rows,
        key="msf_drilldown",
        offer_download=True,
        file_label=f"detalle_producto_tienda_{selected_date}",
    )
