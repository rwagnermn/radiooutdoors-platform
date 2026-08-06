from dataclasses import dataclass
from pathlib import Path
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


QRZ_URL = "https://xmldata.qrz.com/xml/current/"
USER_AGENT = "RadioOutdoors/0.32"


class QRZError(Exception):
    pass


class QRZConfigurationError(QRZError):
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


def _read_secret(filename):
    path = Path(filename)
    if not path.exists():
        raise QRZConfigurationError(
            f"Missing {filename}. Add the QRZ credential file in the project folder."
        )
    value = path.read_text(encoding="utf-8-sig").strip()
    if not value:
        raise QRZConfigurationError(f"{filename} is empty.")
    return value


def _request(params):
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{QRZ_URL}?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.read()
    except Exception as exc:
        raise QRZError(f"QRZ could not be reached: {exc}") from exc


def _nodes(xml_bytes):
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise QRZError("QRZ returned unreadable XML.") from exc

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
    username = _read_secret("qrz_username.txt")
    password = _read_secret("qrz_password.txt")
    xml_bytes = _request(
        {
            "username": username,
            "password": password,
            "agent": USER_AGENT,
        }
    )
    _, node = _nodes(xml_bytes)
    session = node("Session")
    key = _text(session, "Key")
    error = _text(session, "Error")
    message = _text(session, "Message")

    if not key:
        raise QRZError(error or message or "QRZ login failed.")

    return key


def lookup_callsign(callsign):
    normalized = callsign.strip().upper()
    if not normalized:
        raise QRZError("Enter a callsign.")

    key = _login()
    xml_bytes = _request(
        {
            "s": key,
            "callsign": normalized,
            "agent": USER_AGENT,
        }
    )
    _, node = _nodes(xml_bytes)
    session = node("Session")
    call = node("Callsign")

    error = _text(session, "Error")
    if error and call is None:
        raise QRZError(error)

    if call is None:
        raise QRZError("Callsign not found in QRZ.")

    returned_call = _text(call, "call") or normalized

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
    )
