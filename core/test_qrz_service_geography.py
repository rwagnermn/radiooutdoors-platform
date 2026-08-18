from unittest.mock import patch

from django.test import SimpleTestCase

from core.qrz_service import lookup_callsign


class QRZServiceGeographyTests(SimpleTestCase):
    @patch("core.qrz_service._request")
    @patch("core.qrz_service._login", return_value="test-session-key")
    def test_lookup_parses_qrz_grid_latitude_and_longitude(self, login, request):
        request.return_value = b"""<?xml version='1.0'?>
        <QRZDatabase><Callsign>
          <call>KF0DEK</call><state>MN</state><country>United States</country>
          <grid>EN35im</grid><lat>45.123456</lat><lon>-93.654321</lon>
        </Callsign><Session /></QRZDatabase>"""
        result = lookup_callsign("kf0dek")
        self.assertEqual(result.grid, "EN35im")
        self.assertEqual(result.latitude, "45.123456")
        self.assertEqual(result.longitude, "-93.654321")
        login.assert_called_once_with()
