from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from unittest.mock import MagicMock, patch
from django.core.cache import cache
from django.core.management import call_command
import json
import hashlib
from io import StringIO
from django.urls import reverse

from core.models import Adventure, Location, MemberProfile, PotaActivationImport, PotaImportBatch
from .pota_import import parse_pota_history
from .pota_geocoding import geocode_pota_park
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

    def test_reference_and_dash_are_removed_from_clean_park_name(self):
        samples = [
            "2025-06-04 W5RIK US-12388 Caribou Falls Unique Area US-MN 0 0 15 15",
            "2025-06-04 W5RIK US-12388 — Caribou Falls Unique Area US-MN 0 0 15 15",
            "2025-06-04 W5RIK US-12388 US-12388 — Caribou Falls Unique Area US-MN 0 0 15 15",
        ]
        rows, _, invalid = parse_pota_history("\n".join(samples))
        self.assertFalse(invalid)
        self.assertEqual([row.park_reference for row in rows], ["US-12388"] * 3)
        self.assertEqual([row.park_name for row in rows], ["Caribou Falls Unique Area"] * 3)

    def test_malformed_dated_line_is_reported(self):
        rows, ignored, invalid = parse_pota_history("Heading\n2025-06-04 W5RIK broken row\nFooter")
        self.assertEqual(rows, [])
        self.assertEqual(ignored, 2)
        self.assertEqual(invalid[0]["line_number"], 2)

@override_settings(GOOGLE_GEOCODING_API_KEY="")
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
        self.assertNotContains(shared_header_response, "Import POTA History")
        self.assertNotContains(shared_header_response, "Import POTA Hunter Log")

        adventures_response = self.client.get(reverse("my_adventures"))
        self.assertEqual(adventures_response.status_code, 200)
        self.assertContains(adventures_response, "Import POTA History", count=1)
        self.assertContains(adventures_response, f'href="{import_url}"', count=1)

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
        self.assertContains(preview, "14 activations at 6 unique parks")
        self.assertContains(preview, "Caribou Falls Unique Area")
        self.assertContains(preview, "Gordie Mikkelson Wildlife Management Area")
        self.assertContains(preview, "W5RIK")
        self.assertContains(preview, "KF0RIK")
        self.assertEqual(Adventure.objects.count(), 0)

    def test_hundreds_of_activations_render_as_compact_table_without_maps(self):
        self.client.force_login(self.user)
        row = "2024-06-01 W5TEST US-1234 Pike Lake US-MN 0 0 10 10"
        start = self.client.post(reverse("import_pota_history"), {"pota_history": "\n".join([row] * 250)})
        preview = self.client.get(start.url)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "250 activations at 1 unique park")
        self.assertContains(preview, 'name="selected"', count=250)
        self.assertContains(preview, 'name="park_resolution_', count=1)
        self.assertNotContains(preview, "data-pota-park-map")
        self.assertNotContains(preview, "pota-single-park-map")
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
        location = Location.objects.create(
            name="Existing Pike Lake", reference_code=" us-1234 ", created_by=self.user,
            latitude="46.100000", longitude="-92.600000",
        )
        self.client.force_login(self.user)
        repeated = "2024-06-01 W5TEST US-1234 Pike Lake US-MN 0 0 10 10\n2024-06-02 W5TEST US-1234 Pike Lake US-MN 0 0 11 11"
        start = self.client.post(reverse("import_pota_history"), {"pota_history": repeated})
        preview = self.client.get(start.url)
        self.assertContains(preview, "Existing Location matched")
        self.assertContains(preview, f'value="existing:{location.pk}"')
        self.assertContains(preview, 'name="park_resolution_', count=1)
        self.assertContains(preview, 'name="park_latitude_', count=1)

    def test_review_proposes_one_location_without_inventing_coordinates(self):
        self.client.force_login(self.user)
        repeated = "2024-06-01 W5TEST US-9999 Long Park Name US-MN 0 0 10 10\n2024-06-02 W5TEST US-9999 Long Park Name US-MN 0 0 11 11"
        start = self.client.post(reverse("import_pota_history"), {"pota_history": repeated})
        preview = self.client.get(start.url)
        self.assertContains(preview, "Long Park Name")
        self.assertContains(preview, "Lookup unavailable")
        self.assertNotContains(preview, "data-pota-park-map")
        self.assertContains(preview, 'name="park_resolution_', count=1)
        self.assertContains(preview, 'name="park_latitude_', count=1)
        self.assertContains(preview, 'name="park_longitude_', count=1)
        self.assertEqual(Location.objects.count(), 0)
        self.assertEqual(Adventure.objects.count(), 0)

    @override_settings(
        GOOGLE_MAPS_API_KEY="browser-key-sentinel",
        GOOGLE_GEOCODING_API_KEY="server-key-sentinel",
    )
    @patch("adventures.pota_geocoding.urlopen")
    def test_browser_and_server_google_keys_are_separate(self, mocked_open):
        response = mocked_open.return_value.__enter__.return_value
        response.read.return_value = json.dumps({
            "status": "ZERO_RESULTS",
            "results": [],
        }).encode()

        map_response = self.client.get(reverse("map_explorer"))
        self.assertContains(map_response, "browser-key-sentinel")
        self.assertNotContains(map_response, "server-key-sentinel")

        geocode_pota_park(
            "US-12388",
            "Caribou Falls Unique Area",
            "US-MN",
            force_refresh=True,
        )
        requested_url = mocked_open.call_args.args[0]
        self.assertIn("server-key-sentinel", requested_url)
        self.assertNotIn("browser-key-sentinel", requested_url)

    @override_settings(
        GOOGLE_MAPS_API_KEY="browser-key-sentinel",
        GOOGLE_GEOCODING_API_KEY="",
    )
    def test_missing_server_geocoding_key_fails_without_browser_fallback(self):
        result = geocode_pota_park(
            "US-12388",
            "Caribou Falls Unique Area",
            "US-MN",
            force_refresh=True,
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["failure_category"], "configuration_missing")
        self.assertEqual(result["failure_reason"], "Server-side geocoding is not configured.")

    @override_settings(GOOGLE_GEOCODING_API_KEY="test-key")
    @patch("adventures.pota_geocoding.urlopen")
    def test_provider_denial_is_visible_and_safely_categorized(self, mocked_open):
        response = mocked_open.return_value.__enter__.return_value
        response.read.return_value = json.dumps({
            "status": "REQUEST_DENIED",
            "error_message": "secret provider detail",
            "results": [],
        }).encode()
        self.client.force_login(self.user)
        start = self.client.post(reverse("import_pota_history"), {
            "pota_history": "2025-06-04 W5TEST US-12388 Caribou Falls Unique Area US-MN 0 0 15 15"
        })
        preview = self.client.get(start.url)
        self.assertContains(preview, "Lookup unavailable")
        self.assertContains(preview, "Automatic park-location lookup is currently unavailable.", count=1)
        self.assertNotContains(preview, "secret provider detail")

    def test_imported_location_searches_by_reference_and_maps_when_public(self):
        location = Location.objects.create(
            name="Caribou Falls Unique Area — US-12388",
            reference_code="US-12388",
            latitude="47.463000",
            longitude="-91.113000",
            visibility=Location.Visibility.PUBLIC,
            created_by=self.user,
        )
        by_name = self.client.get(reverse("locations"), {"q": "Caribou Falls"})
        by_reference = self.client.get(reverse("locations"), {"q": "US-12388"})
        map_response = self.client.get(reverse("map_explorer"))
        self.assertContains(by_name, location.name)
        self.assertContains(by_reference, location.name)
        self.assertContains(map_response, f'"location_id": {location.pk}')
        self.assertContains(map_response, '"marker_type": "location"')

    @patch("core.management.commands.repair_pota_location_coordinates.geocode_pota_park")
    def test_controlled_repair_updates_proven_location_without_duplicates(self, geocode):
        location = Location.objects.create(
            name="Caribou Falls Unique Area",
            reference_code="US-12388",
            state="MN",
            country="USA",
            created_by=self.user,
            description="Created from POTA historical import. Pin needed.",
        )
        adventure = Adventure.objects.create(owner=self.user, title="Imported activation", location=location)
        batch = PotaImportBatch.objects.create(owner=self.user)
        PotaActivationImport.objects.create(
            adventure=adventure, batch=batch, activation_date="2025-06-04",
            callsign="W5TEST", park_reference="US-12388",
            park_name="Caribou Falls Unique Area", entity="US-MN",
            total_contacts=15, fingerprint="a" * 64, location_resolution="existing",
        )
        geocode.return_value = {
            "status": "found",
            "candidates": [{
                "provider_name": "Caribou Falls State Wayside",
                "latitude": "47.463", "longitude": "-91.113",
            }],
        }
        output = StringIO()
        call_command("repair_pota_location_coordinates", stdout=output)
        location.refresh_from_db()
        self.assertEqual(Location.objects.filter(reference_code="US-12388").count(), 1)
        self.assertEqual(str(location.latitude), "47.463000")
        self.assertEqual(str(location.longitude), "-91.113000")
        self.assertIn("Provider suggestion: Caribou Falls State Wayside", location.description)
        self.assertIn("Repaired: 1; unresolved: 0", output.getvalue())

    @override_settings(POTA_PARK_REFERENCE_DATA={"US-9999": {"name": "Lookup Park", "entity": "US-MN", "latitude": "46.123456", "longitude": "-92.654321"}})
    def test_configured_public_reference_data_is_labeled_approximate(self):
        self.client.force_login(self.user)
        start = self.client.post(reverse("import_pota_history"), {"pota_history": "2024-06-01 W5TEST US-9999 Clipboard Name US-MN 0 0 10 10"})
        preview = self.client.get(start.url)
        self.assertContains(preview, "Clipboard Name")
        self.assertContains(preview, "Approximate pin found")
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
        self.assertEqual(location.name, "Long Park Name — US-9999")
        self.assertEqual(location.state, "MN")
        self.assertEqual(location.location_type, Location.LocationType.PARK)
        self.assertEqual(str(location.latitude), "46.123456")
        self.assertEqual(str(location.longitude), "-92.654321")
        self.assertEqual(set(Adventure.objects.values_list("location_id", flat=True)), {location.pk})
        self.assertEqual(Adventure.objects.count(), 2)
        self.client.post(reverse("confirm_pota_history", args=[token]), post)
        self.assertEqual(Location.objects.filter(reference_code="US-9999").count(), 1)

    def test_preview_selection_posts_to_confirm_and_creates_adventure(self):
        self.client.force_login(self.user)
        start = self.client.post(reverse("import_pota_history"), {"pota_history": SAMPLE})
        token = start.url.rstrip("/").split("/")[-1]
        preview = self.client.get(start.url)
        self.assertContains(preview, 'action="' + reverse("confirm_pota_history", args=[token]) + '"')
        self.assertContains(preview, 'name="selected" value="0" checked')

        result = self.client.post(
            reverse("confirm_pota_history", args=[token]),
            {"selected": ["0"], "publish_pota_batch": "yes", "row_visibility_0": "batch"},
        )

        self.assertRedirects(result, reverse("pota_history_result"))
        self.assertEqual(Adventure.objects.filter(owner=self.user).count(), 1)
        self.assertEqual(PotaActivationImport.objects.filter(adventure__owner=self.user).count(), 1)

    @override_settings(POTA_PARK_REFERENCE_DATA={"US-1234": {"name": "Pike Lake", "entity": "US-MN", "latitude": "46.123456", "longitude": "-92.654321"}})
    def test_imported_coordinates_reach_adventure_and_location_detail_maps(self):
        self.client.force_login(self.user)
        start = self.client.post(reverse("import_pota_history"), {"pota_history": SAMPLE})
        token = start.url.rstrip("/").split("/")[-1]
        key = _park_key("US-1234")
        imported = self.client.post(reverse("confirm_pota_history", args=[token]), {
            "selected": ["0"], f"park_resolution_{key}": "create",
            f"park_latitude_{key}": "46.123456", f"park_longitude_{key}": "-92.654321",
        })
        self.assertRedirects(imported, reverse("pota_history_result"))
        adventure = Adventure.objects.get(owner=self.user)
        location = adventure.location
        self.assertEqual(str(location.latitude), "46.123456")
        self.assertEqual(str(location.longitude), "-92.654321")

        for response in (
            self.client.get(adventure.get_absolute_url()),
            self.client.get(reverse("location_detail", args=[location.pk])),
        ):
            self.assertContains(response, "data-single-location-map", count=1)
            self.assertContains(response, '"latitude": 46.123456')
            self.assertContains(response, '"longitude": -92.654321')
            self.assertContains(response, 'aria-busy="true"')

    def test_no_selection_returns_to_preview_with_meaningful_error(self):
        self.client.force_login(self.user)
        start = self.client.post(reverse("import_pota_history"), {"pota_history": SAMPLE})
        token = start.url.rstrip("/").split("/")[-1]

        result = self.client.post(reverse("confirm_pota_history", args=[token]), {}, follow=True)

        self.assertRedirects(result, reverse("preview_pota_history", args=[token]))
        self.assertContains(result, "Select at least one eligible activation to import.")
        self.assertEqual(Adventure.objects.count(), 0)

    def test_selected_alternate_callsign_requires_attestation_then_imports(self):
        self.client.force_login(self.user)
        row = "2024-06-01 K0ALT US-9999 Long Park Name US-MN 0 0 10 10"
        start = self.client.post(reverse("import_pota_history"), {"pota_history": row})
        token = start.url.rstrip("/").split("/")[-1]
        preview = self.client.get(start.url)
        self.assertContains(preview, "data-requires-callsign-attestation")

        rejected = self.client.post(reverse("confirm_pota_history", args=[token]), {"selected": ["0"]}, follow=True)
        self.assertRedirects(rejected, reverse("preview_pota_history", args=[token]))
        self.assertContains(rejected, "Confirm authorization for the listed former or alternate callsigns before importing.")
        self.assertEqual(Adventure.objects.count(), 0)

        imported = self.client.post(reverse("confirm_pota_history", args=[token]), {
            "selected": ["0"], "callsign_attestation": "yes",
        })
        self.assertRedirects(imported, reverse("pota_history_result"))
        self.assertEqual(Adventure.objects.count(), 1)

    def test_confirmation_creates_review_queued_pinless_location(self):
        self.client.force_login(self.user)
        start = self.client.post(reverse("import_pota_history"), {"pota_history": "2024-06-01 W5TEST US-9999 Long Park Name US-MN 0 0 10 10"})
        token = start.url.rstrip("/").split("/")[-1]
        key = _park_key("US-9999")
        result = self.client.post(reverse("confirm_pota_history", args=[token]), {
            "selected": ["0"], f"park_resolution_{key}": "create",
            f"park_latitude_{key}": "", f"park_longitude_{key}": "",
        }, follow=True)
        self.assertContains(result, "1 needs Location review")
        location = Location.objects.get(reference_code="US-9999")
        self.assertTrue(location.needs_pin_review)
        self.assertIsNone(location.latitude)
        self.assertIsNone(location.longitude)
        self.assertEqual(Adventure.objects.count(), 1)

    @override_settings(GOOGLE_GEOCODING_API_KEY="test-key")
    @patch("adventures.pota_geocoding.urlopen")
    def test_geocodes_once_per_unique_park_without_rendering_preview_maps(self, mocked_open):
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
        request_url = mocked_open.call_args.args[0]
        self.assertIn("Caribou+Falls+Unique+Area%2C+Minnesota%2C+United+States", request_url)
        self.assertNotIn("US-12388", request_url)
        self.assertContains(preview, "Approximate pin found")
        self.assertNotContains(preview, "data-pota-park-map")
        self.assertNotContains(preview, "Delete Pin and Place Another")
        self.assertEqual(Location.objects.count(), 0)

    @override_settings(GOOGLE_GEOCODING_API_KEY="test-key")
    @patch("adventures.pota_geocoding.urlopen")
    def test_staged_search_accepts_caribou_falls_close_match(self, mocked_open):
        empty = MagicMock()
        empty.__enter__.return_value.read.return_value = json.dumps({"status": "ZERO_RESULTS", "results": []}).encode()
        close = MagicMock()
        close.__enter__.return_value.read.return_value = json.dumps({"status": "OK", "results": [{
            "formatted_address": "Caribou Falls State Wayside, Silver Creek Township, MN, USA",
            "types": ["park", "point_of_interest"],
            "geometry": {"location": {"lat": 47.463, "lng": -91.113}},
            "address_components": [
                {"short_name": "MN", "types": ["administrative_area_level_1"]},
                {"short_name": "US", "types": ["country"]},
            ],
        }]}).encode()
        mocked_open.side_effect = [empty, close]
        self.client.force_login(self.user)
        start = self.client.post(reverse("import_pota_history"), {"pota_history": "2025-06-04 W5TEST US-12388 Caribou Falls Unique Area US-MN 0 0 15 15"})
        preview = self.client.get(start.url)
        self.assertEqual(mocked_open.call_count, 2)
        self.assertContains(preview, "Approximate pin found")
        self.assertContains(preview, 'value="Caribou Falls State Wayside"')
        self.assertNotContains(preview, "Accept This General Location")
        self.assertContains(preview, 'value="47.463"')
        first_query = mocked_open.call_args_list[0].args[0]
        second_query = mocked_open.call_args_list[1].args[0]
        self.assertIn("Caribou+Falls+Unique+Area", first_query)
        self.assertIn("Caribou+Falls%2C+Minnesota", second_query)
        self.assertEqual(Location.objects.count(), 0)
        token = start.url.rstrip("/").split("/")[-1]
        key = _park_key("US-12388")
        self.client.post(reverse("confirm_pota_history", args=[token]), {
            "selected": ["0"], "publish_pota_batch": "yes", "row_visibility_0": "batch",
            f"park_resolution_{key}": "create", f"park_latitude_{key}": "47.463",
            f"park_longitude_{key}": "-91.113", f"park_provider_name_{key}": "Caribou Falls State Wayside",
        })
        location = Location.objects.get(reference_code="US-12388")
        self.assertEqual(location.name, "Caribou Falls Unique Area — US-12388")
        self.assertIn("Provider suggestion: Caribou Falls State Wayside.", location.description)
        self.assertIn("Coordinate source: geocoded park name.", location.description)
        self.assertTrue(Adventure.objects.get().is_public)

    @override_settings(GOOGLE_GEOCODING_API_KEY="test-key")
    @patch("adventures.pota_geocoding.urlopen")
    def test_provider_ranked_nearby_park_is_approximate_fallback(self, mocked_open):
        response = mocked_open.return_value.__enter__.return_value
        response.read.return_value = json.dumps({"status": "OK", "results": [{
            "formatted_address": "Garfield Public Use Area, Garfield, AR, USA",
            "types": ["park", "point_of_interest"],
            "geometry": {"location": {"lat": 36.454, "lng": -94.034}},
            "address_components": [
                {"short_name": "AR", "types": ["administrative_area_level_1"]},
                {"short_name": "US", "types": ["country"]},
            ],
        }]}).encode()
        result = geocode_pota_park(
            "US-0721", "Pea Ridge National Military Park", "US-AR", force_refresh=True,
        )
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["candidates"][0]["match_kind"], "nearby")
        self.assertEqual(result["candidates"][0]["provider_name"], "Garfield Public Use Area")

    def test_new_imports_default_public_with_per_row_private_override(self):
        self.client.force_login(self.user)
        rows = "2024-06-01 W5TEST US-9999 Long Park Name US-MN 0 0 10 10\n2024-06-02 W5TEST US-9999 Long Park Name US-MN 0 0 11 11"
        start = self.client.post(reverse("import_pota_history"), {"pota_history": rows})
        token = start.url.rstrip("/").split("/")[-1]
        key = _park_key("US-9999")
        response = self.client.post(reverse("confirm_pota_history", args=[token]), {
            "selected": ["0", "1"], "publish_pota_batch": "yes",
            "row_visibility_0": "batch", "row_visibility_1": "private",
            f"park_resolution_{key}": "create", f"park_latitude_{key}": "46.1", f"park_longitude_{key}": "-92.6",
        })
        self.assertEqual(response.status_code, 302)
        visibilities = list(Adventure.objects.order_by("started_at").values_list("is_public", flat=True))
        self.assertEqual(visibilities, [True, False])

    def test_batch_private_allows_individual_public_override(self):
        self.client.force_login(self.user)
        rows = "2024-07-01 W5TEST US-8888 Other Park US-MN 0 0 10 10\n2024-07-02 W5TEST US-8888 Other Park US-MN 0 0 11 11"
        start = self.client.post(reverse("import_pota_history"), {"pota_history": rows})
        token = start.url.rstrip("/").split("/")[-1]
        key = _park_key("US-8888")
        self.client.post(reverse("confirm_pota_history", args=[token]), {
            "selected": ["0", "1"], "row_visibility_0": "batch", "row_visibility_1": "public",
            f"park_resolution_{key}": "create", f"park_latitude_{key}": "46.2", f"park_longitude_{key}": "-92.7",
        })
        self.assertEqual(list(Adventure.objects.order_by("started_at").values_list("is_public", flat=True)), [False, True])

    def test_public_import_with_private_location_masks_location_from_visitor(self):
        self.client.force_login(self.user)
        start = self.client.post(reverse("import_pota_history"), {"pota_history": "2024-08-01 W5TEST US-7777 Secret Park US-MN 0 0 10 10"})
        token = start.url.rstrip("/").split("/")[-1]
        key = _park_key("US-7777")
        self.client.post(reverse("confirm_pota_history", args=[token]), {
            "selected": ["0"], "publish_pota_batch": "yes", "row_visibility_0": "batch",
            f"park_resolution_{key}": "create", f"park_latitude_{key}": "47.123456",
            f"park_longitude_{key}": "-93.654321", f"park_private_{key}": "yes",
        })
        adventure = Adventure.objects.get()
        self.assertTrue(adventure.is_public)
        self.assertEqual(adventure.location.visibility, Location.Visibility.PRIVATE)
        self.client.logout()
        response = self.client.get(adventure.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Private Location")
        self.assertNotContains(response, "47.123456")
        self.assertNotContains(response, "-93.654321")

    @override_settings(GOOGLE_GEOCODING_API_KEY="test-key")
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
        self.assertContains(preview, "Pin pending")
        self.assertContains(preview, 'name="park_latitude_', count=1)
        self.assertContains(preview, 'name="park_longitude_', count=1)

    def _create_pin_review_location(self, *, owner=None, reference="US-9999"):
        owner = owner or self.user
        location = Location.objects.create(
            name=f"Long Park Name — {reference}",
            reference_code=reference,
            state="MN",
            country="USA",
            created_by=owner,
            needs_pin_review=True,
            description="Created from POTA historical import. Pin needed.",
        )
        batch = PotaImportBatch.objects.create(owner=owner)
        for day in ("2024-06-01", "2024-06-02"):
            adventure = Adventure.objects.create(
                owner=owner,
                title=f"POTA activation {day}",
                location=location,
                is_public=True,
            )
            PotaActivationImport.objects.create(
                adventure=adventure,
                batch=batch,
                activation_date=day,
                callsign="W5TEST",
                park_reference=reference,
                park_name="Long Park Name",
                entity="US-MN",
                total_contacts=10,
                fingerprint=hashlib.sha256(f"{owner.pk}-{reference}-{day}".encode()).hexdigest(),
                location_resolution="unresolved",
            )
        return location

    def test_pin_review_queue_groups_repeated_activations_and_map_excludes_pinless_location(self):
        location = self._create_pin_review_location()
        self.client.force_login(self.user)
        queue = self.client.get(reverse("pota_pin_queue"))
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, location.name, count=1)
        self.assertContains(queue, "<td>2</td>", html=True)
        public_map = self.client.get(reverse("map_explorer"))
        self.assertNotContains(public_map, f'"location_id": {location.pk}')

    def test_pin_review_page_has_exactly_one_map_and_saving_pin_clears_queue(self):
        location = self._create_pin_review_location()
        self.client.force_login(self.user)
        review_url = reverse("review_pota_pin", args=[location.pk])
        review = self.client.get(review_url)
        self.assertEqual(review.status_code, 200)
        self.assertContains(review, 'id="pota-single-park-map"', count=1)
        self.assertContains(review, "Place Pin")
        saved = self.client.post(review_url, {"latitude": "46.123456", "longitude": "-92.654321"})
        self.assertRedirects(saved, reverse("pota_pin_queue"))
        location.refresh_from_db()
        self.assertFalse(location.needs_pin_review)
        self.assertEqual(str(location.latitude), "46.123456")
        self.assertNotContains(self.client.get(reverse("pota_pin_queue")), location.name)
        self.assertContains(self.client.get(reverse("map_explorer")), f'"location_id": {location.pk}')

    def test_pin_review_queue_is_owner_scoped_and_staff_can_review(self):
        other = get_user_model().objects.create_user(username="K0OTHER", password="password")
        MemberProfile.objects.create(user=other, callsign="K0OTHER", callsign_verified=True)
        location = self._create_pin_review_location(owner=other, reference="US-8888")
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("pota_pin_queue")), location.name)
        self.assertEqual(self.client.get(reverse("review_pota_pin", args=[location.pk])).status_code, 404)
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("pota_pin_queue")), location.name)
        self.assertEqual(self.client.get(reverse("review_pota_pin", args=[location.pk])).status_code, 200)

    @patch("adventures.pota_views.geocode_pota_park")
    def test_retry_lookup_runs_once_and_opens_single_map_review(self, geocode):
        location = self._create_pin_review_location()
        geocode.return_value = {"status": "found", "candidates": [{
            "provider_name": "Mapped Long Park",
            "latitude": "46.2",
            "longitude": "-92.7",
        }]}
        self.client.force_login(self.user)
        response = self.client.post(reverse("retry_pota_pin_lookup", args=[location.pk]))
        self.assertRedirects(response, reverse("review_pota_pin", args=[location.pk]))
        self.assertEqual(geocode.call_count, 1)
        review = self.client.get(response.url)
        self.assertContains(review, "Mapped Long Park")
        self.assertContains(review, 'id="pota-single-park-map"', count=1)
