import socket
import ssl
import urllib.error
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .qrz_service import (
    QRZConfigurationError,
    QRZUnavailableError,
    _read_secret,
    _request,
    lookup_callsign,
)


class QRZConfigurationTests(SimpleTestCase):
    def test_missing_configuration_identifies_key_without_a_value(self):
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.txt"
            with override_settings(QRZ_USERNAME="", QRZ_USERNAME_FILE=missing):
                with self.assertRaises(QRZConfigurationError) as raised:
                    _read_secret("QRZ_USERNAME", "QRZ_USERNAME_FILE")
        self.assertEqual(raised.exception.configuration_key, "QRZ_USERNAME")
        self.assertIn("Missing QRZ_USERNAME", str(raised.exception))

    def test_environment_setting_takes_precedence_over_missing_file(self):
        with override_settings(
            QRZ_USERNAME="configured-value",
            QRZ_USERNAME_FILE=Path("does-not-exist.txt"),
        ):
            self.assertEqual(
                _read_secret("QRZ_USERNAME", "QRZ_USERNAME_FILE"),
                "configured-value",
            )

    @override_settings(QRZ_USERNAME="configured-user", QRZ_PASSWORD="configured-password")
    @patch("core.qrz_service._request")
    def test_configured_credentials_reach_successful_callsign_verification(self, request):
        request.side_effect = [
            b"<QRZDatabase><Session><Key>session-key</Key></Session></QRZDatabase>",
            b"<QRZDatabase><Callsign><call>VK5CP</call><fname>Test</fname><name>Operator</name><country>Australia</country><type>P</type></Callsign><Session /></QRZDatabase>",
        ]
        result = lookup_callsign("vk5cp")
        self.assertEqual(result.callsign, "VK5CP")
        self.assertTrue(result.is_person_identity)
        self.assertEqual(request.call_count, 2)


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
