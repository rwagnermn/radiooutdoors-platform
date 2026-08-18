from django.test import SimpleTestCase

from adventures.adif_parser import maidenhead_to_latlon, normalize_maidenhead_grid
from adventures.contact_geography import (
    sanitize_qrz_geography,
    sign_geography,
    verified_geography,
)


class ContactGeographyTests(SimpleTestCase):
    def test_four_six_and_eight_character_grids_are_normalized_and_centered(self):
        for raw, normalized in (
            ("en35", "EN35"),
            ("en35im", "EN35IM"),
            ("en35im12", "EN35IM12"),
        ):
            with self.subTest(grid=raw):
                self.assertEqual(normalize_maidenhead_grid(raw), normalized)
                latitude, longitude = maidenhead_to_latlon(raw)
                self.assertGreaterEqual(latitude, -90)
                self.assertLessEqual(latitude, 90)
                self.assertGreaterEqual(longitude, -180)
                self.assertLessEqual(longitude, 180)

    def test_invalid_or_partial_grid_is_rejected_safely(self):
        for grid in ("", "EN3", "EN35I", "SN35", "EN35YZ", "EN35IM1", "EN35IM123"):
            with self.subTest(grid=grid):
                self.assertEqual(normalize_maidenhead_grid(grid), "")
                self.assertIsNone(maidenhead_to_latlon(grid))

    def test_valid_direct_coordinates_take_precedence_and_preserve_grid(self):
        geography = sanitize_qrz_geography(
            grid="en35im", latitude="45.1234564", longitude="-93.6543214"
        )
        self.assertEqual(geography.grid_square, "EN35IM")
        self.assertEqual(str(geography.latitude), "45.123456")
        self.assertEqual(str(geography.longitude), "-93.654321")

    def test_grid_center_is_used_when_coordinates_are_missing_or_invalid(self):
        missing = sanitize_qrz_geography(grid="EN35IM")
        invalid = sanitize_qrz_geography(
            grid="EN35IM", latitude="91", longitude="-181"
        )
        self.assertEqual(missing, invalid)
        self.assertEqual(str(missing.latitude), "45.520833")
        self.assertEqual(str(missing.longitude), "-93.291667")

    def test_no_usable_geography_remains_empty(self):
        for geography in (
            sanitize_qrz_geography(),
            sanitize_qrz_geography(grid="INVALID"),
            sanitize_qrz_geography(latitude="91", longitude="181"),
        ):
            self.assertEqual(geography.grid_square, "")
            self.assertIsNone(geography.latitude)
            self.assertIsNone(geography.longitude)

    def test_signed_geography_is_bound_to_callsign_and_values(self):
        geography = sanitize_qrz_geography(grid="EN35IM")
        token = sign_geography("KF0DEK", geography)
        verified = verified_geography(
            "KF0DEK", "EN35IM", geography.latitude, geography.longitude, token
        )
        self.assertEqual(verified, geography)
        self.assertIsNone(verified_geography(
            "N2JIM", "EN35IM", geography.latitude, geography.longitude, token
        ))
        self.assertIsNone(verified_geography(
            "KF0DEK", "EN35IM", geography.latitude, "-90", token
        ))
