import socket
import ssl
import urllib.error
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .qrz_service import QRZUnavailableError, _request


class QRZTransportLoggingTests(SimpleTestCase):
    secret_parameters = {
        "username": "SECRET-CALLSIGN",
        "password": "SECRET-PASSWORD",
        "s": "SECRET-SESSION-KEY",
    }

    def assert_logged_category(self, error, category):
        with patch("core.qrz_service.urllib.request.urlopen", side_effect=error):
            with self.assertLogs("core.qrz_service", level="WARNING") as captured:
                with self.assertRaises(QRZUnavailableError) as raised:
                    _request(self.secret_parameters)

        self.assertIs(raised.exception.__cause__, error)
        raised_message = str(raised.exception)
        self.assertNotIn("SECRET-PASSWORD", raised_message)
        self.assertNotIn("xmldata.qrz.com", raised_message)
        output = "\n".join(captured.output)
        self.assertIn(f"category={category}", output)
        self.assertIn(f"exception_type={type(error).__name__}", output)
        self.assertNotIn("SECRET-CALLSIGN", output)
        self.assertNotIn("SECRET-PASSWORD", output)
        self.assertNotIn("SECRET-SESSION-KEY", output)
        self.assertNotIn("xmldata.qrz.com", output)

    def test_transport_errors_are_safely_classified_and_chained(self):
        cases = [
            (socket.timeout("timed out"), "timeout"),
            (urllib.error.URLError(socket.gaierror(-2, "host not found")), "dns_failure"),
            (urllib.error.URLError(ssl.SSLError("certificate failure")), "tls_failure"),
            (urllib.error.URLError(ConnectionRefusedError("refused")), "connection_refused"),
            (
                urllib.error.URLError(PermissionError("socket access denied")),
                "network_permission_denied",
            ),
            (
                urllib.error.HTTPError(
                    "https://example.invalid/?password=SECRET-PASSWORD",
                    503,
                    "Service Unavailable",
                    None,
                    None,
                ),
                "http_status",
            ),
            (RuntimeError("other failure"), "transport_error"),
        ]
        for error, category in cases:
            with self.subTest(category=category):
                self.assert_logged_category(error, category)


class QRZSafeRegistrationMessageTests(TestCase):
    @patch("core.account_views.lookup_callsign")
    def test_transport_failure_keeps_safe_member_message(self, lookup):
        lookup.side_effect = QRZUnavailableError(
            "internal transport detail that must not be shown"
        )
        response = self.client.post(
            reverse("register"),
            {
                "callsign": "DL1ABC",
                "email": "transport@example.com",
                "password1": "SafeTransportPass!942",
                "password2": "SafeTransportPass!942",
                "policy_accepted": "on",
                "age_confirmed": "on",
            },
        )
        self.assertContains(
            response,
            "QRZ is temporarily unavailable. No account was created; please try again later.",
        )
        self.assertNotContains(response, "internal transport detail")
