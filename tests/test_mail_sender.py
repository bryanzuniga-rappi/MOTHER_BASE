"""Envío por correo del paquete de una corrida (Gmail API), sin red.

El servicio de Gmail es un doble de prueba: se decodifica el mensaje que se le
entrega y se revisa destinatarios, asunto y adjuntos."""

import ast
import base64
import email
import email.policy
import io
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from tests._streamlit_stub import install

install()

import openpyxl  # noqa: E402

import modules.les_enfants_terribles as m  # noqa: E402
from modules import mail_sender as ms  # noqa: E402
from tests import test_copernico_856_storage as support  # noqa: E402

DATE = "05-10-2026"


# --- doble de Gmail ------------------------------------------------------------------

class FakeGmail:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def users(self):
        return SimpleNamespace(messages=lambda: self)

    def send(self, userId, body=None, media_body=None):
        self.calls.append({"userId": userId, "body": body, "media_body": media_body})
        if self.fail:
            raise self.fail
        return SimpleNamespace(execute=lambda: {"id": "msg-123"})

    def sent_message(self):
        call = self.calls[-1]
        raw = base64.urlsafe_b64decode(call["body"]["raw"]) if call["body"] else call["media_body"]
        return email.message_from_bytes(raw, policy=email.policy.default)


def attachments_of(message):
    return {part.get_filename(): part.get_content() for part in message.iter_attachments()}


def real_run():
    """Una corrida completa (origen 856, COPÉRNICO con apóstrofes, AVL y Preventivo).

    Sin caché: cada corrida nueva limpia el espacio de trabajo de las anteriores."""
    return support.run_856(
        [(100, 7235, 5)], include_solidus_engine=True, include_avl_fill=True,
        include_preventive_fill=True, avl_doh=3.0,
    )


# --- destinatarios ----------------------------------------------------------------------

def test_default_recipients_are_the_three_requested():
    assert ms.DEFAULT_RECIPIENTS == (
        "javier.ballesteros@rappi.com", "bryan.zuniga@rappi.com", "dorian.santiago@rappi.com",
    )


def test_parse_recipients_accepts_any_separator_and_normalizes():
    valid, invalid = ms.parse_recipients("A@rappi.com, b@rappi.com;c@rappi.com\n d@rappi.com\ta@rappi.com")
    assert valid == ["a@rappi.com", "b@rappi.com", "c@rappi.com", "d@rappi.com"]
    assert invalid == []


def test_parse_recipients_reports_invalid_addresses():
    valid, invalid = ms.parse_recipients("ok@rappi.com, sin-arroba, otro@, @rappi.com, x@y")
    assert valid == ["ok@rappi.com"]
    assert invalid == ["sin-arroba", "otro@", "@rappi.com", "x@y"]
    assert ms.parse_recipients("") == ([], [])


# --- nombres ---------------------------------------------------------------------------------

def test_copernico_names_use_the_warehouse_and_the_date():
    items = [
        {"path": "in/COPERNICO_444.csv", "warehouses": [444]},
        {"path": "in/otro.csv", "warehouses": [444]},
        {"path": "in/doble.csv", "warehouses": [831, 444]},
        {"path": "in/Mi archivo (1).csv", "warehouses": []},
    ]
    names = [n for _i, n in ms.copernico_attachment_names(items, DATE)]
    assert names == [
        f"Copernico_444_{DATE}.csv", f"Copernico_444_{DATE}_2.csv",
        f"Copernico_444-831_{DATE}.csv", f"Copernico_Mi_archivo_1_{DATE}.csv",
    ]


def test_date_label_prefers_run_date_then_the_zip_name():
    assert ms.date_label({"run_date": "2026-10-05"}) == "05-10-2026"
    assert ms.date_label({"zip": "/tmp/x/Planeacion_02-10-2026.zip"}) == "02-10-2026"


# --- paquete de una corrida real -----------------------------------------------------------------

def test_the_run_remembers_its_date_and_copernico_inputs():
    run = real_run()
    assert run["run_date"] == "2026-10-05"
    assert [item["warehouses"] for item in run["copernico_inputs"]] == [[856]]
    assert Path(run["copernico_inputs"][0]["path"]).exists()


def test_package_has_the_four_requested_files_with_the_requested_names():
    package = ms.build_package(real_run())
    assert [a.name for a in package.attachments] == [
        f"Copernico_856_{DATE}.csv", f"Reporte_Planeación_{DATE}.xlsx",
        f"Sin_Recomendación_{DATE}.csv", f"OVERVIEW_{DATE}.csv",
    ]
    assert ms.preview_names(real_run()) == [a.name for a in package.attachments]


def test_copernico_is_attached_unchanged_but_renamed():
    run = real_run()
    original = Path(run["copernico_inputs"][0]["path"]).read_bytes()
    package = ms.build_package(run)
    assert package.attachments[0].data == original == support.copernico_upload().getvalue()


def test_report_attachment_has_only_base_transfers_with_identical_rows():
    run = real_run()
    package = ms.build_package(run)
    sent = openpyxl.load_workbook(io.BytesIO(package.attachments[1].data), read_only=True, data_only=True)
    assert sent.sheetnames == ["BASE_TRANSFERS"]
    original = openpyxl.load_workbook(ms._find_output(run, "Reporte_Planeacion_"), read_only=True, data_only=True)
    assert "DETALLE_ASIGNACION" in original.sheetnames          # el original sí trae más hojas
    assert list(sent["BASE_TRANSFERS"].iter_rows(values_only=True)) == list(
        original["BASE_TRANSFERS"].iter_rows(values_only=True)
    )


def test_no_recommendation_csv_is_the_fountain9_file_renamed():
    run = real_run()
    package = ms.build_package(run)
    assert package.attachments[2].data == ms._find_output(run, "Fountain9_Sin_Recomendacion").read_bytes()


def test_overview_csv_is_the_same_table_shown_on_screen():
    run = real_run()
    package = ms.build_package(run)
    expected = m.rows_to_csv_bytes(m.ordered_breakdown_rows(run["status_counts"], run.get("status_swa")))
    assert package.attachments[3].data == expected
    header = package.attachments[3].data.decode("utf-8-sig").splitlines()[0]
    assert header.startswith("BREAKDOWN,FILAS")


def test_a_missing_report_or_simulation_fails_with_a_clear_message():
    run = real_run()
    no_report = {**run, "files": [f for f in run["files"] if not Path(f).name.startswith("Reporte_Planeacion_")]}
    for bad, fragment in ((no_report, "reporte de planeación"), ({**run, "simulation": True}, "simulación")):
        try:
            ms.build_package(bad)
        except ms.MailPackageError as error:
            assert fragment in str(error)
        else:
            raise AssertionError("debía fallar")


def test_a_run_without_copernico_still_sends_and_says_so():
    package = ms.build_package({**real_run(), "copernico_inputs": []})
    assert not [a for a in package.attachments if a.name.startswith("Copernico_")]
    assert any("No se subió COPÉRNICO" in note for note in package.notes)


# --- mensaje y envío ---------------------------------------------------------------------------

def test_the_message_reaches_gmail_with_all_recipients_and_attachments():
    gmail = FakeGmail()
    recipients = list(ms.DEFAULT_RECIPIENTS)
    result = ms.send_run_package(real_run(), recipients, service=gmail)
    call = gmail.calls[0]
    assert call["userId"] == "me" and call["media_body"] is None
    message = gmail.sent_message()
    assert [a.strip() for a in message["To"].split(",")] == recipients
    assert DATE in message["Subject"] and "Les Enfants Terribles" in message["Subject"]
    assert list(attachments_of(message)) == [name for name, _size in result.attachments]
    assert result.message_id == "msg-123" and result.zipped is False


def test_the_body_summarizes_the_run_and_lists_the_files():
    gmail = FakeGmail()
    run = real_run()
    ms.send_run_package(run, ["a@rappi.com"], service=gmail)
    body = gmail.sent_message().get_body(preferencelist=("plain",)).get_content()
    assert f"Unidades planeadas: {run['units']:,}" in body
    assert f"Tareas: {run['tasks']:,}" in body
    assert f"Reporte_Planeación_{DATE}.xlsx" in body and run["build"] in body


def test_large_messages_go_through_the_upload_route():
    gmail = FakeGmail()
    original = ms.INLINE_SEND_LIMIT_BYTES
    ms.INLINE_SEND_LIMIT_BYTES = 10
    seen = []
    try:
        ms.send_run_package(real_run(), ["a@rappi.com"], service=gmail,
                            media_factory=lambda data: seen.append(data) or data)
    finally:
        ms.INLINE_SEND_LIMIT_BYTES = original
    assert gmail.calls[0]["body"] is None and gmail.calls[0]["media_body"] == seen[0]
    assert list(attachments_of(gmail.sent_message()))       # el mensaje completo viaja intacto


def test_too_big_even_zipped_fails_with_the_sizes():
    original = ms.MAX_RAW_ATTACHMENT_BYTES
    ms.MAX_RAW_ATTACHMENT_BYTES = 1000
    try:
        # El ZIP tampoco cabe en 1000 bytes: debe fallar con los tamaños
        try:
            ms.build_package(real_run())
        except ms.MailPackageError as error:
            assert "MB" in str(error) and "Gmail acepta" in str(error)
        else:
            raise AssertionError("debía fallar")
    finally:
        ms.MAX_RAW_ATTACHMENT_BYTES = original


def test_zip_fallback_when_only_the_raw_total_is_too_big():
    run = real_run()
    total = sum(a.size for a in ms.build_package(run).attachments)
    original = ms.MAX_RAW_ATTACHMENT_BYTES
    ms.MAX_RAW_ATTACHMENT_BYTES = total - 1                 # no caben sueltos pero sí comprimidos
    try:
        package = ms.build_package(run)
    finally:
        ms.MAX_RAW_ATTACHMENT_BYTES = original
    assert package.zipped and [a.name for a in package.attachments] == [f"Planeacion_{DATE}.zip"]
    inside = zipfile.ZipFile(io.BytesIO(package.attachments[0].data)).namelist()
    assert inside == ms.preview_names(run)
    assert any("comprimidos en un solo ZIP" in note for note in package.notes)


def test_sending_without_recipients_is_rejected():
    try:
        ms.send_run_package(real_run(), [], service=FakeGmail())
    except ms.MailError as error:
        assert "destinatario" in str(error)
    else:
        raise AssertionError("debía fallar")


def test_files_are_built_before_authenticating():
    """Si falta el reporte no se toca Google: el error es de archivos, no de OAuth."""
    run = {**real_run(), "simulation": True}
    try:
        ms.send_run_package(run, ["a@rappi.com"])              # sin servicio: no debe llegar a build_gmail_service
    except ms.MailPackageError:
        pass
    else:
        raise AssertionError("debía fallar por el paquete")


# --- autenticación -------------------------------------------------------------------------------

class Creds:
    kwargs = None

    def __init__(self, token, **kwargs):
        Creds.kwargs = kwargs
        self.error = kwargs.pop("_error", None)

    def refresh(self, _request):
        if Creds.error_to_raise:
            raise Exception(Creds.error_to_raise)


Creds.error_to_raise = None
SECRETS = {
    "DATA_DASHBOARD_OAUTH_CLIENT_ID": "id", "DATA_DASHBOARD_OAUTH_CLIENT_SECRET": "secret",
    "DATA_DASHBOARD_OAUTH_REFRESH_TOKEN": "drive-token",
}


def gmail_service(secrets=SECRETS, error=None):
    Creds.error_to_raise = error
    built = {}

    def builder(api, version, credentials=None, cache_discovery=None):
        built.update(api=api, version=version, credentials=credentials)
        return "SERVICE"

    service = ms.build_gmail_service(secrets, credentials_factory=Creds, service_builder=builder)
    return service, built


def test_missing_secrets_are_named():
    try:
        ms.build_gmail_service({}, credentials_factory=Creds, service_builder=lambda *a, **k: None)
    except ms.MailConfigError as error:
        for name in ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"):
            assert name in str(error)
    else:
        raise AssertionError("debía fallar")


def test_gmail_client_requests_only_the_send_scope_and_reuses_the_oauth_client():
    service, built = gmail_service()
    assert service == "SERVICE" and (built["api"], built["version"]) == ("gmail", "v1")
    assert Creds.kwargs["scopes"] == [ms.GMAIL_SEND_SCOPE] == ["https://www.googleapis.com/auth/gmail.send"]
    assert Creds.kwargs["refresh_token"] == "drive-token" and Creds.kwargs["client_id"] == "id"


def test_a_dedicated_mail_token_takes_precedence():
    gmail_service({**SECRETS, "MAIL_OAUTH_REFRESH_TOKEN": "mail-token"})
    assert Creds.kwargs["refresh_token"] == "mail-token"


def test_a_drive_only_token_gets_a_reauthorization_message():
    for error in ("invalid_scope: Bad Request", "unauthorized_client: Client is unauthorized"):
        try:
            gmail_service(error=error)
        except ms.MailAuthError as exc:
            assert "solo tiene permiso de Drive" in str(exc) and "Conectar mi cuenta" in str(exc)
        else:
            raise AssertionError("debía fallar")


def test_an_expired_token_is_explained():
    try:
        gmail_service(error="invalid_grant: Token has been expired or revoked.")
    except ms.MailAuthError as exc:
        assert "invalid_grant" in str(exc) and "revocado" in str(exc)
    else:
        raise AssertionError("debía fallar")


def test_gmail_api_errors_become_actionable_messages():
    cases = {
        "Request had insufficient authentication scopes.": ms.MailAuthError,
        "Gmail API has not been used in project 123 (accessNotConfigured)": ms.MailConfigError,
        "Rate Limit Exceeded (userRateLimitExceeded)": ms.MailError,
        "algo raro": ms.MailError,
    }
    for text, kind in cases.items():
        error = ms.friendly_send_error(Exception(text))
        assert isinstance(error, kind), text
    assert "autorizarlo" in str(ms.friendly_send_error(Exception("insufficient authentication scopes")))
    assert "no está habilitada" in str(ms.friendly_send_error(Exception("accessNotConfigured")))


def test_send_failures_surface_as_mail_errors_not_raw_exceptions():
    gmail = FakeGmail(fail=Exception("Request had insufficient authentication scopes."))
    try:
        ms.send_run_package(real_run(), ["a@rappi.com"], service=gmail)
    except ms.MailAuthError as error:
        assert "Drive" in str(error)
    else:
        raise AssertionError("debía fallar")


# --- OAuth de Militaires -------------------------------------------------------------------------

def test_militaires_authorization_url_requests_drive_and_gmail_send():
    source = (Path(m.__file__).parent / "militaires_sans_frontieres.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_oauth_authorization_url")
    names = {n.id for n in ast.walk(function) if isinstance(n, ast.Name)}
    assert {"OAUTH_SCOPE", "GMAIL_SEND_SCOPE"} <= names
    assert "from modules.mail_sender import GMAIL_SEND_SCOPE" in source
    # la lectura/escritura de Drive sigue pidiendo solo su propio permiso
    assert re.search(r'scopes=\[OAUTH_SCOPE\]', source)


# --- componente de pantalla ----------------------------------------------------------------------

def run_section(run, text=None, click=False, send=None):
    fake = MagicMock()
    fake.session_state = {}
    fake.text_area.side_effect = lambda label, value="", **kw: value if text is None else text
    buttons = []
    fake.button.side_effect = lambda label, **kw: buttons.append((label, kw)) or (click and not kw.get("disabled"))
    original_st, original_send = m.st, ms.send_run_package
    m.st = fake
    if send:
        ms.send_run_package = send
    try:
        m.render_mail_section(run)
    finally:
        m.st, ms.send_run_package = original_st, original_send
    return fake, buttons


def ok_result(recipients):
    return ms.MailResult(recipients, "s", [("a.csv", 1_500_000)], False, "id", ["nota de prueba"])


def test_section_prefills_the_default_recipients_and_lists_the_files():
    fake, buttons = run_section(real_run())
    caption = " ".join(str(c.args[0]) for c in fake.caption.call_args_list)
    assert f"Reporte_Planeación_{DATE}.xlsx" in caption and f"OVERVIEW_{DATE}.csv" in caption
    label, kwargs = fake.text_area.call_args.args[0], fake.text_area.call_args.kwargs
    assert label == "Destinatarios (uno por línea)"
    assert kwargs["value"].split("\n") == list(ms.DEFAULT_RECIPIENTS)
    assert buttons == [("Enviar por mail", {"key": "mb_mail_send", "disabled": False})]


def test_one_click_sends_one_consolidated_mail_to_the_listed_recipients():
    calls = []
    fake, _ = run_section(
        real_run(), text="x@rappi.com\ny@rappi.com", click=True,
        send=lambda run, recipients: calls.append(recipients) or ok_result(recipients),
    )
    assert calls == [["x@rappi.com", "y@rappi.com"]]
    success = fake.success.call_args.args[0]
    assert "2 destinatario(s)" in success and "x@rappi.com" in success and "a.csv (1.4 MB)" in success


def test_invalid_addresses_warn_and_block_the_button():
    sent = []
    fake, buttons = run_section(real_run(), text="ok@rappi.com, roto", click=True,
                                send=lambda *a: sent.append(a))
    assert "roto" in fake.warning.call_args.args[0]
    assert buttons[0][1]["disabled"] is True and sent == []


def test_empty_recipient_list_blocks_the_button():
    _fake, buttons = run_section(real_run(), text="   ")
    assert buttons[0][1]["disabled"] is True


def test_known_errors_are_shown_as_messages_without_crashing():
    def boom(run, recipients):
        raise ms.MailAuthError(ms.REAUTH_MESSAGE)
    fake, _ = run_section(real_run(), click=True, send=boom)
    assert "solo tiene permiso de Drive" in fake.error.call_args.args[0]
    fake.success.assert_not_called()


def test_unexpected_errors_never_break_the_results_screen():
    def boom(run, recipients):
        raise RuntimeError("inesperado")
    fake, _ = run_section(real_run(), click=True, send=boom)
    assert "No se pudo enviar el correo: inesperado" in fake.error.call_args.args[0]


def test_simulation_runs_have_nothing_to_send():
    fake, buttons = run_section({**real_run(), "simulation": True})
    assert buttons == [] and not fake.text_area.called
    assert "simulación" in fake.caption.call_args.args[0]


def test_section_sits_right_after_the_swa_kpi_block_and_before_cities():
    from tests.test_engine_report_layout import _render, _run_with_everything_enabled

    calls = [c for c in _render(_run_with_everything_enabled()) if isinstance(c, str)]
    labels = [i for i, c in enumerate(calls) if "ENVIAR POR MAIL" in c]
    cities = [i for i, c in enumerate(calls) if "CIUDADES + TIENDAS ATENDIDAS" in c]
    swa = [i for i, c in enumerate(calls) if "SWA · SALES WEIGHTED AVAILABILITY" in c]
    assert labels and cities and swa
    assert swa[0] < labels[0] < cities[0]


# --- reportes enormes: falla rápido ---------------------------------------------------------------

def test_sheet_size_estimate_is_a_lower_bound_of_the_real_attachment():
    """Es una cota para fallar rápido (en reportes reales coincide con el archivo
    final: 2.2 vs 2.2 MB y 35.5 vs 35.6 MB); el tamaño ya armado se revisa aparte."""
    run = real_run()
    report = ms._find_output(run, "Reporte_Planeacion_")
    estimate = ms.estimated_sheet_bytes(report)
    real = len(ms.base_transfers_xlsx_bytes(report))
    assert estimate and 0 < estimate <= real * 1.5


def test_estimate_is_none_for_unreadable_files(tmp_path):
    bad = tmp_path / "no_es_xlsx.xlsx"
    bad.write_bytes(b"no soy un zip")
    assert ms.estimated_sheet_bytes(bad) is None
    assert ms.estimated_sheet_bytes(tmp_path / "no_existe.xlsx") is None


def test_a_sheet_that_cannot_fit_fails_before_reading_the_workbook():
    calls = []
    original_xlsx, original_limit = ms.base_transfers_xlsx_bytes, ms.MAX_RAW_ATTACHMENT_BYTES
    ms.base_transfers_xlsx_bytes = lambda path: calls.append(path) or b""
    ms.MAX_RAW_ATTACHMENT_BYTES = 100                   # nada cabe
    try:
        ms.build_package(real_run())
    except ms.MailPackageError as error:
        assert "BASE_TRANSFERS pesa unos" in str(error) and "Drive" in str(error)
    else:
        raise AssertionError("debía fallar")
    finally:
        ms.base_transfers_xlsx_bytes, ms.MAX_RAW_ATTACHMENT_BYTES = original_xlsx, original_limit
    assert calls == []                                  # no gastó minutos reescribiendo el libro
