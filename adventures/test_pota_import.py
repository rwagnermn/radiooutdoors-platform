from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from unittest.mock import patch
from django.core.cache import cache
import json
from django.urls import reverse

from core.models import Adventure, Location, MemberProfile
from .pota_import import parse_pota_history
from .pota_views import _park_key

SAMPLE = "My Activations\n2024-06-01\tW5TEST\tUS-1234\tPike Lake\tUS-MN\t4\t1\t5\t10\nCopyright POTA"
SUPPLIED_SAMPLE = """2025-06-04 W5RIK US-12388 Caribou Falls Unique Area US-MN 0 0 15 15
2025-06-04 W5RIK US-12394 Ray Berglund Unique Area US-MN 0 0 16 16
2025-06-03 W5RIK US-12390 Flood Bay Unique Area US-MN 0 0 14 14
2025-04-29 W5RIK US-12058 Gordie Mikkelson Wildlife Management Area US-MN 0 0 77 77
2025-04-25 W5RIK US-12058 Gordie Mikkelson Wildlife Management Area US-MN 0 0 11 11
2025-02-14 KF0RIK US-10308 Carlos Avery WMA Wildlife Management Area US-MN 0 0 15 15
2025-01-30 KF0RIK US-12058 Gordie Mikkelson Wildlife Management Area US-MN 0 0 18 18
2024-11-24 KF0RIK US-12058 Gordie Mikkelson Wildlife Management Area US-MN 0 0 13 13
2024-09-20 KF0RIK US-10308 Carlos Avery WMA Wildlife Management Area US-MN 0 0 40 40
2024-04-11 KF0RIK US-0370 Sherburne National Wildlife Refuge US-MN 0 0 11 11
2024-01-02 KF0RIK US-10308 Carlos Avery WMA Wildlife Management Area US-MN 0 0 44 44
2023-12-14 KF0RIK US-10308 Carlos Avery WMA Wildlife Management Area US-MN 0 0 69 69
2023-11-30 KF0RIK US-10308 Carlos Avery WMA Wildlife Management Area US-MN 0 0 15 15
2023-11-22 KF0RIK US-10308 Carlos Avery WMA Wildlife Management Area US-MN 0 0 13 13"""

class PotaParserTests(TestCase):
    def test_parser_ignores_page_chrome_and_reads_counts(self):
        rows, ignored, invalid = parse_pota_history(SAMPLE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(ignored, 2)
        self.assertFalse(invalid)
        self.assertEqual(rows[0].park_reference, "US-1234")
        self.assertEqual(rows[0].total, 10)

    def test_count_mismatch_is_warning_not_error(self):
        rows, _, _ = parse_pota_history(SAMPLE.replace("\t10", "\t11"))
        self.assertFalse(rows[0].errors)
        self.assertTrue(rows[0].warnings)

    def test_all_fourteen_supplied_rows_and_long_names(self):
        rows, ignored, invalid = parse_pota_history(SUPPLIED_SAMPLE)
        self.assertEqual(len(rows), 14)
        self.assertEqual(ignored, 0)
        self.assertEqual(invalid, [])
        self.assertEqual(rows[0].park_name, "Caribou Falls Unique Area")
        self.assertEqual(rows[3].park_name, "Gordie Mikkelson Wildlife Management Area")
        self.assertEqual(rows[5].callsign, "KF0RIK")
        self.assertEqual(rows[3].total, 77)

    def test_tabs_spaces_nbsp_and_line_endings(self):
        variants = [
            "2025-06-04\tW5RIK\tUS-12388\tCaribou Falls Unique Area\tUS-MN\t0\t0\t15\t15",
            "2025-06-04    W5RIK    US-12388 Caribou Falls Unique Area    US-MN    0 0 15 15",
            "2025-06-04\u00a0W5RIK\u00a0US-12388\u00a0Caribou Falls Unique Area\u00a0US-MN\u00a00\u00a00\u00a015\u00a015",
        ]
        rows, ignored, invalid = parse_pota_history("\r\n".join(variants) + "\n")
        self.assertEqual(len(rows), 3)
        self.assertEqual((ignored, invalid), (0, []))

    def test_malformed_dated_line_is_reported(self):
        rows, ignored, invalid = parse_pota_history("Heading\n2025-06-04 W5RIK broken row\nFooter")
        self.assertEqual(rows, [])
        self.assertEqual(ignored, 2)
        self.assertEqual(invalid[0]["line_number"], 2)

@override_settings(GOOGLE_MAPS_API_KEY="")
class PotaImportEntryPointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="W5TEST", password="password")
        MemberProfile.objects.create(user=self.user, callsign="W5TEST", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)

    def test_verified_member_sees_working_import_links(self):
        self.client.force_login(self.user)
        import_url = reverse("import_pota_history")
        self.assertEqual(import_url, "/adventures/import/pota/")

        shared_header_response = self.client.get(reverse("home"))
        self.assertEqual(shared_header_response.status_code, 200)
        self.assertContains(shared_header_response, "Import POTA History")
        self.assertContains(shared_header_response, f'href="{import_url}"')

        adventures_response = self.client.get(reverse("my_adventures"))
        self.assertEqual(adventures_response.status_code, 200)
        self.assertContains(adventures_response, "Import POTA History", count=2)
        self.assertContains(adventures_response, f'href="{import_url}"', count=2)

        importer_response = self.client.get(import_url)
        self.assertEqual(importer_response.status_code, 200)
        self.assertContains(importer_response, "Copy the activation table from POTA My Activations")

    def test_visitor_does_not_see_entry_and_direct_access_requires_login(self):
        home_response = self.client.get(reverse("home"))
        self.assertNotContains(home_response, "Import POTA History")
        import_url = reverse("import_pota_history")
        direct_response = self.client.get(import_url)
        self.assertEqual(direct_response.status_code, 302)
        self.assertIn(f"next={import_url}", direct_response.url)

    def test_pending_member_matches_create_adventure_permission(self):
        pending_user = get_user_model().objects.create_user(username="K0PEND", password="password")
        MemberProfile.objects.create(user=pending_user, callsign="K0PEND", callsign_verified=False)
        self.client.force_login(pending_user)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Import POTA History")
        self.assertNotContains(response, "Create Adventure")
        self.assertEqual(self.client.get(reverse("import_pota_history")).status_code, 403)
        self.assertEqual(self.client.get(reverse("add_adventure")).status_code, 403)

    def test_supplied_sample_previews_fourteen_without_writes(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("import_pota_history"), {"pota_history": SUPPLIED_SAMPLE})
        self.assertEqual(response.status_code, 302)
        preview = self.client.get(response.url)
        self.assertContains(preview, "14 recognized activation rows")
        self.assertContains(preview, "Caribou Falls Unique Area")
        self.assertContains(preview, "Gordie Mikkelson Wildlife Management Area")
        self.assertContains(preview, "W5RIK")
        self.assertContains(preview, "KF0RIK")
        self.assertEqual(Adventure.objects.count(), 0)

    def test_complete_failure_preserves_text_and_accessible_error(self):
        self.client.force_login(self.user)
        pasted = "This is not a POTA activation row"
        response = self.client.post(reverse("import_pota_history"), {"pota_history": pasted})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, pasted)
        self.assertContains(response, "We couldn’t recognize the pasted POTA activations.")
        self.assertContains(response, "No recognizable POTA activation rows were found.", count=1)
        self.assertContains(response, 'role="alert"')
        self.assertContains(response, 'aria-live="assertive"')

    def test_partial_failure_preserves_exact_text_and_reports_line(self):
        self.client.force_login(self.user)
        pasted = SUPPLIED_SAMPLE.splitlines()[0] + "\r\n2025-06-05 W5RIK malformed"
        response = self.client.post(reverse("import_pota_history"), {"pota_history": pasted})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2025-06-05 W5RIK malformed")
        self.assertContains(response, "1 recognized; 0 ignored; 1 invalid.")
        self.assertContains(response, "Line 2:")
        self.assertEqual(Adventure.objects.count(), 0)

    def test_busy_indicator_markup_is_accessible(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("import_pota_history"))
        self.assertContains(response, 'id="pota-review-button"')
        self.assertContains(response, 'aria-live="polite"')
        self.assertContains(response, "Please wait while Radio Outdoors reviews the pasted activation history.")
        self.assertContains(response, "pota-import-review.js")

    def test_existing_location_is_matched_once_for_repeated_reference(self):
        location = Location.objects.create(name="Existing Pike Lake", reference_code=" us-1234 ", created_by=self.user)
        self.client.force_login(self.user)
        repeated = "2024-06-01 W5TEST US-1234 Pike Lake US-MN 0 0 10 10\n2024-06-02 W5TEST US-1234 Pike Lake US-MN 0 0 11 11"
        start = self.client.post(reverse("import_pota_history"), {"pota_history": repeated})
        preview = self.client.get(start.url)
        self.assertContains(preview, "Matched existing Location")
        self.assertContains(preview, f'value="existing:{location.pk}" selected')
        self.assertContains(preview, 'name="park_resolution_', count=1)
        self.assertNotContains(preview, 'name="park_latitude_')

    def test_review_proposes_one_location_without_inventing_coordinates(self):
        self.client.force_login(self.user)
        repeated = "2024-06-01 W5TEST US-9999 Long Park Name US-MN 0 0 10 10\n2024-06-02 W5TEST US-9999 Long Park Name US-MN 0 0 11 11"
        start = self.client.post(reverse("import_pota_history"), {"pota_history": repeated})
        preview = self.client.get(start.url)
        self.assertContains(preview, "Create Location — Long Park Name (pin needed)")
        self.assertContains(preview, "Location not found")
        self.assertContains(preview, 'name="park_resolution_', count=1)
        self.assertContains(preview, 'name="park_latitude_', count=1)
        self.assertContains(preview, 'name="park_longitude_', count=1)
        self.assertEqual(Location.objects.count(), 0)
        self.assertEqual(Adventure.objects.count(), 0)

    @override_settings(POTA_PARK_REFERENCE_DATA={"US-9999": {"name": "Lookup Park", "entity": "US-MN", "latitude": "46.123456", "longitude": "-92.654321"}})
    def test_configured_public_reference_data_is_labeled_approximate(self):
        self.client.force_login(self.user)
        start = self.client.post(reverse("import_pota_history"), {"pota_history": "2024-06-01 W5TEST US-9999 Clipboard Name US-MN 0 0 10 10"})
        preview = self.client.get(start.url)
        self.assertContains(preview, "Create Location — Lookup Park (approximate park pin)")
        self.assertContains(preview, "Approximate pin—review")
        self.assertContains(preview, 'value="46.123456"')
        self.assertContains(preview, 'value="-92.654321"')

    def test_confirmation_creates_one_location_and_reuses_it(self):
        self.client.force_login(self.user)
        repeated = "2024-06-01 W5TEST US-9999 Long Park Name US-MN 0 0 10 10\n2024-06-02 W5TEST US-9999 Long Park Name US-MN 0 0 11 11"
        start = self.client.post(reverse("import_pota_history"), {"pota_history": repeated})
        token = start.url.rstrip("/").split("/")[-1]
        key = _park_key("US-9999")
        post = {"selected": ["0", "1"], f"park_resolution_{key}": "create", f"park_latitude_{key}": "46.123456", f"park_longitude_{key}": "-92.654321"}
        result = self.client.post(reverse("confirm_pota_history", args=[token]), post)
        self.assertRedirects(result, reverse("pota_history_result"))
        self.assertEqual(Location.objects.filter(reference_code="US-9999").count(), 1)
        location = Location.objects.get(reference_code="US-9999")
        self.assertEqual(location.name, "Long Park Name")
        self.assertEqual(location.state, "MN")
        self.assertEqual(location.location_type, Location.LocationType.PARK)
        self.assertEqual(str(location.latitude), "46.123456")
        self.assertEqual(str(location.longitude), "-92.654321")
        self.assertEqual(set(Adventure.objects.values_list("location_id", flat=True)), {location.pk})
        self.assertEqual(Adventure.objects.count(), 2)
        self.client.post(reverse("confirm_pota_history", args=[token]), post)
        self.assertEqual(Location.objects.filter(reference_code="US-9999").count(), 1)

    @override_settings(GOOGLE_MAPS_API_KEY="test-key")
    @patch("adventures.pota_geocoding.urlopen")
    def test_geocodes_once_per_unique_park_and_renders_review_map(self, mocked_open):
        response = mocked_open.return_value.__enter__.return_value
        response.read.return_value = json.dumps({"results": [{
            "formatted_address": "Caribou Falls Unique Area, Minnesota, USA",
            "geometry": {"location": {"lat": 47.2, "lng": -91.3}},
            "address_components": [
                {"short_name": "MN", "types": ["administrative_area_level_1"]},
                {"short_name": "US", "types": ["country"]},
            ],
        }]}).encode()
        self.client.force_login(self.user)
        rows = "2025-06-04 W5TEST US-12388 Caribou Falls Unique Area US-MN 0 0 15 15\n2025-06-05 W5TEST US-12388 Caribou Falls Unique Area US-MN 0 0 16 16"
        start = self.client.post(reverse("import_pota_history"), {"pota_history": rows})
        preview = self.client.get(start.url)
        self.assertEqual(mocked_open.call_count, 1)
        self.assertContains(preview, "Approximate park location found")
        self.assertContains(preview, "data-pota-park-map")
        self.assertContains(preview, "Remove Pin")
        self.assertContains(preview, "This pin identifies the general park location")
        self.assertEqual(Location.objects.count(), 0)

    @override_settings(GOOGLE_MAPS_API_KEY="test-key")
    @patch("adventures.pota_geocoding.urlopen")
    def test_wrong_state_geocode_result_requires_manual_review(self, mocked_open):
        response = mocked_open.return_value.__enter__.return_value
        response.read.return_value = json.dumps({"results": [{
            "formatted_address": "Wrong Park, Wisconsin, USA",
            "geometry": {"location": {"lat": 44, "lng": -89}},
            "address_components": [
                {"short_name": "WI", "types": ["administrative_area_level_1"]},
                {"short_name": "US", "types": ["country"]},
            ],
        }]}).encode()
        self.client.force_login(self.user)
        start = self.client.post(reverse("import_pota_history"), {"pota_history": "2025-06-04 W5TEST US-12388 Caribou Falls Unique Area US-MN 0 0 15 15"})
        preview = self.client.get(start.url)
        self.assertContains(preview, "Location not found—place pin")
        self.assertContains(preview, 'value=""', count=2)
