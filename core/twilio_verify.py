import base64
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TwilioVerifyConfiguration:
    account_sid: str
    api_key_sid: str
    api_key_secret: str
    service_sid: str

    @property
    def complete(self):
        return all((self.account_sid, self.api_key_sid, self.api_key_secret, self.service_sid))


class TwilioVerifyError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


def load_twilio_configuration(*, base_dir=None, environ=None):
    base_dir = Path(base_dir or settings.BASE_DIR)
    environ = os.environ if environ is None else environ
    mapping = {
        "account_sid": ("TWILIO_ACCOUNT_SID", "twilio_account_sid.txt"),
        "api_key_sid": ("TWILIO_API_KEY_SID", "twilio_api_key_sid.txt"),
        "api_key_secret": ("TWILIO_API_KEY_SECRET", "twilio_api_key_secret.txt"),
        "service_sid": ("TWILIO_VERIFY_SERVICE_SID", "twilio_verify_service_sid.txt"),
    }
    values = {}
    for field, (environment_name, filename) in mapping.items():
        value = environ.get(environment_name, "").strip()
        path = base_dir / filename
        if not value and path.is_file():
            value = path.read_text(encoding="utf-8").strip()
        values[field] = value
    return TwilioVerifyConfiguration(**values)


def configuration_diagnostics(configuration=None):
    configuration = configuration or load_twilio_configuration()
    return {
        "Twilio Account SID configured": bool(configuration.account_sid),
        "Twilio API Key SID configured": bool(configuration.api_key_sid),
        "Twilio API Key Secret configured": bool(configuration.api_key_secret),
        "Twilio Verify Service SID configured": bool(configuration.service_sid),
    }


class TwilioVerifyClient:
    def __init__(self, configuration=None, opener=urlopen):
        self.configuration = configuration or load_twilio_configuration()
        self.opener = opener

    def _post(self, endpoint, data):
        if not self.configuration.complete:
            raise TwilioVerifyError("configuration_missing")
        url = (
            "https://verify.twilio.com/v2/Services/"
            f"{self.configuration.service_sid}/{endpoint}"
        )
        credentials = base64.b64encode(
            f"{self.configuration.api_key_sid}:{self.configuration.api_key_secret}".encode()
        ).decode()
        request = Request(
            url,
            data=urlencode(data).encode(),
            headers={"Authorization": f"Basic {credentials}"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=15) as response:
                return json.loads(response.read().decode())
        except HTTPError as exc:
            if exc.code in (401, 403):
                category = "authentication_rejected"
            elif exc.code == 429:
                category = "rate_limited"
            elif exc.code == 400:
                category = "invalid_phone"
            else:
                category = "provider_error"
            raise TwilioVerifyError(category) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TwilioVerifyError("network_unavailable") from exc
        except (ValueError, TypeError) as exc:
            raise TwilioVerifyError("provider_error") from exc

    def send_code(self, phone):
        payload = self._post("Verifications", {"To": phone, "Channel": "sms"})
        if payload.get("status") not in {"pending", "approved"}:
            raise TwilioVerifyError("provider_error")

    def check_code(self, phone, code):
        payload = self._post("VerificationCheck", {"To": phone, "Code": code})
        status = payload.get("status")
        if status == "approved":
            return True
        if status in {"canceled", "expired"}:
            raise TwilioVerifyError("verification_expired")
        raise TwilioVerifyError("verification_failed")
