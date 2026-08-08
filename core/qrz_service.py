from dataclasses import dataclass
import logging
from pathlib import Path
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


QRZ_URL = "https://xmldata.qrz.com/xml/current/"
USER_AGENT = "RadioOutdoors/0.32"
logger = logging.getLogger(__name__)


class QRZError(Exception):
    pass


class QRZConfigurationError(QRZError):
    pass


class QRZNotFoundError(QRZError):
    pass


class QRZUnavailableError(QRZError):
    pass


@dataclass
class QRZResult:
    callsign: str
    first_name: str = ""
    last_name: str = ""
    city: str = ""
    state: str = ""
    country: str = ""
    grid: str = ""
    license_class: str = ""
    expires: str = ""
    record_type: str = ""

    @property
    def is_person_identity(self):
        """Return whether QRZ identifies this record as an individual operator."""
        record_type = self.record_type.strip().upper()
        if record_type:
            return record_type == "P"
        # Some QRZ special-event records omit ``type`` and place an
        # organization phrase in ``fname``. Be conservative: a multi-word
        # first-name field is not safe to promote automatically into a
        # person's account identity or welcome greeting.
        return bool(
            len(self.first_name.strip().split()) == 1
            and self.last_name.strip()
        )


def _read_secret(filename):
    path = Path(filename)
    if not path.exists():
        raise QRZConfigurationError(
            f"Missing {filename}. Add the QRZ credential file in the project folder."
        )
    value = path.read_text(encoding="utf-8-sig").strip()
    if not value:
        raise QRZConfigurationError(f"{filename} is empty.")
    logger.info("QRZ credential file loaded file=%s nonempty=true", filename)
    return value


def _request(params, operation="unspecified"):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{QRZ_URL}?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    logger.info("QRZ request starting operation=%s", operation)
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = response.read()
            logger.info(
                "QRZ HTTP response received operation=%s status=%s",
                operation,
                getattr(response, "status", "unknown"),
            )
            return payload
    except Exception as exc:
        category, detail = _transport_error_details(exc)
        logger.warning(
            "QRZ transport error operation=%s category=%s exception_type=%s detail=%s",
            operation,
            category,
            type(exc).__name__,
            detail,
        )
        raise QRZUnavailableError(
            f"QRZ could not be reached ({category}): {detail}"
        ) from exc


def _transport_error_details(exc):
    """Return useful diagnostics without URLs, credentials, keys, or bodies."""
    if isinstance(exc, urllib.error.HTTPError):
        return "http_status", f"QRZ returned HTTP status {exc.code}."

    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout", "The QRZ request timed out."
    if isinstance(reason, socket.gaierror):
        return "dns_failure", "DNS resolution for the QRZ service failed."
    if isinstance(reason, ssl.SSLError):
        return "tls_failure", "TLS negotiation with the QRZ service failed."
    if isinstance(reason, ConnectionRefusedError):
        return "connection_refused", "The QRZ service refused the connection."
    if isinstance(reason, PermissionError):
        return (
            "network_permission_denied",
            "The local environment denied outbound network access to QRZ.",
        )
    if isinstance(reason, ConnectionError):
        return "connection_error", "A connection error occurred while contacting QRZ."
    if isinstance(exc, urllib.error.URLError):
        return (
            "url_error",
            f"The QRZ request failed with {type(reason).__name__}.",
        )
    return "transport_error", f"The QRZ request failed with {type(exc).__name__}."


def _nodes(xml_bytes, operation="unspecified"):
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning(
            "QRZ XML parse failure operation=%s exception_type=%s",
            operation,
            type(exc).__name__,
        )
        raise QRZUnavailableError("QRZ returned unreadable XML.") from exc

    logger.info("QRZ XML parsed operation=%s", operation)

    def node(name):
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == name:
                return element
        return None

    return root, node


def _text(parent, name):
    if parent is None:
        return ""
    for element in parent:
        if element.tag.rsplit("}", 1)[-1] == name:
            return (element.text or "").strip()
    return ""


def _login():
    logger.info("QRZ authentication starting")
    username = _read_secret("qrz_username.txt")
    password = _read_secret("qrz_password.txt")
    xml_bytes = _request(
        {
            "username": username,
            "password": password,
            "agent": USER_AGENT,
        },
        operation="authentication",
    )
    _, node = _nodes(xml_bytes, operation="authentication")
    session = node("Session")
    key = _text(session, "Key")
    error = _text(session, "Error")
    message = _text(session, "Message")

    if not key:
        logger.warning(
            "QRZ authentication rejected session_key_returned=false xml_error_present=%s",
            bool(error or message),
        )
        raise QRZError(error or message or "QRZ login failed.")

    logger.info("QRZ authentication succeeded session_key_returned=true")
    return key


def lookup_callsign(callsign):
    normalized = callsign.strip().upper()
    if not normalized:
        raise QRZError("Enter a callsign.")

    logger.info("QRZ callsign lookup starting callsign=%s", normalized)
    key = _login()
    logger.info("QRZ callsign lookup request reached callsign=%s", normalized)
    xml_bytes = _request(
        {
            "s": key,
            "callsign": normalized,
            "agent": USER_AGENT,
        },
        operation="callsign_lookup",
    )
    _, node = _nodes(xml_bytes, operation="callsign_lookup")
    session = node("Session")
    call = node("Callsign")

    error = _text(session, "Error")
    if error and call is None:
        logger.warning(
            "QRZ callsign lookup XML error callsign=%s error_present=true",
            normalized,
        )
        if "not found" in error.lower():
            raise QRZNotFoundError("Callsign not found in QRZ.")
        raise QRZError(error)

    if call is None:
        logger.warning(
            "QRZ callsign lookup returned no record callsign=%s",
            normalized,
        )
        raise QRZNotFoundError("Callsign not found in QRZ.")

    returned_call = _text(call, "call") or normalized
    logger.info("QRZ callsign lookup succeeded callsign=%s", returned_call.upper())

    return QRZResult(
        callsign=returned_call.upper(),
        first_name=_text(call, "fname"),
        last_name=_text(call, "name"),
        city=_text(call, "addr2"),
        state=_text(call, "state"),
        country=_text(call, "country") or _text(call, "land"),
        grid=_text(call, "grid"),
        license_class=_text(call, "class"),
        expires=_text(call, "expdate"),
        record_type=_text(call, "type"),
    )
