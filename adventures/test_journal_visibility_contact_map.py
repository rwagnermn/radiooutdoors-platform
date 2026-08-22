from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Adventure, JournalContact, JournalEntry, Location, MemberProfile


class JournalVisibilityAndContactMapTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("map-owner", password="test")
        MemberProfile.objects.create(
            user=self.owner,
            callsign="W0MAP",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = users.objects.create_user("map-other", password="test")
        MemberProfile.objects.create(
            user=self.other,
            callsign="W1OTHER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.staff = users.objects.create_user(
            "map-staff", password="test", is_staff=True
        )
        self.origin = Location.objects.create(
            name="Journal Origin",
            created_by=self.owner,
            latitude="44.100000",
            longitude="-93.200000",
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Map Adventure",
            is_public=True,
        )
        self.entry = JournalEntry.objects.create(
            adventure=self.adventure,
            location=self.origin,
            latitude=self.origin.latitude,
            longitude=self.origin.longitude,
            title="Mapped Journal",
            body="Fields remain unchanged.",
            operating_callsign="W0MAP",
            is_public=True,
        )
        self.detail_url = reverse("journal_entry_detail", args=[self.entry.pk])
        self.map_url = reverse("adventure_contact_geography", args=[self.adventure.slug]) + f"?journal={self.entry.pk}"
        self.toggle_url = reverse("toggle_journal_visibility", args=[self.entry.pk])

    def add_contact(self, entry, callsign, fingerprint, **values):
        defaults = {
            "qso_date": entry.entry_at.date(),
            "callsign": callsign,
            "fingerprint": fingerprint,
            "mode": "SSB",
        }
        defaults.update(values)
        return JournalContact.objects.create(journal_entry=entry, **defaults)

    def test_owner_flip_flop_is_post_only_and_preserves_fields(self):
        self.client.force_login(self.owner)
        detail = self.client.get(self.detail_url)
        self.assertContains(detail, ">Public</button>")
        self.assertContains(detail, 'aria-label="Change Journal visibility to Private"')
        self.assertEqual(self.client.get(self.toggle_url).status_code, 405)

        response = self.client.post(self.toggle_url, follow=True)
        self.assertRedirects(response, self.detail_url)
        self.assertContains(response, "Journal visibility changed to Private.")
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_public)
        self.assertEqual(self.entry.body, "Fields remain unchanged.")
        self.assertEqual(self.entry.operating_callsign, "W0MAP")

        response = self.client.post(self.toggle_url, follow=True)
        self.assertContains(response, "Journal visibility changed to Public.")
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_public)

    def test_toggle_rejects_visitor_other_member_forgery_and_missing_csrf(self):
        self.assertEqual(self.client.post(self.toggle_url).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.toggle_url).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("toggle_journal_visibility", args=[999999])).status_code,
            404,
        )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(self.toggle_url).status_code, 403)
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_public)

    def test_staff_can_toggle_and_public_viewer_gets_noninteractive_badge(self):
        public = self.client.get(self.detail_url)
        self.assertContains(public, 'class="journal-visibility-badge journal-visibility-public"')
        self.assertNotContains(public, "Change Journal visibility")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(self.toggle_url).status_code, 302)
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_public)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        self.assertEqual(self.client.get(self.map_url).status_code, 200)

    def test_private_journal_detail_and_map_are_hidden_from_unauthorized_users(self):
        self.entry.is_public = False
        self.entry.save(update_fields=["is_public"])
        for user in (None, self.other):
            if user is None:
                self.client.logout()
            else:
                self.client.force_login(user)
            self.assertEqual(self.client.get(self.detail_url).status_code, 404)
            geography = self.client.get(self.map_url)
            self.assertEqual(geography.status_code, 200)
            self.assertNotContains(geography, "Mapped Journal")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.map_url).status_code, 200)

    def test_map_combines_adventure_journals_and_preselects_current_journal(self):
        mapped = self.add_contact(
            self.entry,
            "K1MAPPED",
            "mapped",
            latitude="40.100000",
            longitude="-75.200000",
            band="20m",
            source=JournalContact.Source.ADIF,
        )
        self.add_contact(self.entry, "K1GRID", "grid", grid_square="EN34")
        self.add_contact(self.entry, "K1NONE", "none")
        other_entry = JournalEntry.objects.create(
            adventure=self.adventure, title="Other Journal", body="Other"
        )
        self.add_contact(
            other_entry,
            "K1WRONG",
            "wrong-journal",
            latitude="35.000000",
            longitude="-80.000000",
        )

        response = self.client.get(self.map_url)
        self.assertContains(response, "Mapped Journal")
        self.assertContains(response, "Map Adventure")
        self.assertContains(response, "Back to Adventure")
        self.assertContains(response, "Journal Location")
        self.assertContains(response, "Contact path")
        self.assertContains(response, '"mapped": 3')
        self.assertContains(response, '"unmapped": 1')
        self.assertContains(response, '"latitude": 44.1')
        self.assertContains(response, '"longitude": -93.2')
        self.assertContains(response, mapped.callsign)
        self.assertContains(response, "K1GRID")
        self.assertContains(response, "K1NONE")
        self.assertContains(response, "K1WRONG")
        self.assertContains(response, f'<option value="{self.entry.pk}" selected>Mapped Journal</option>', html=True)
        self.assertEqual(response.context["contact_map"]["mapped"], 3)
        self.assertEqual(len(response.context["contact_map"]["contacts"]), 3)

    def test_missing_journal_origin_still_maps_contacts_without_paths(self):
        Location.objects.filter(pk=self.origin.pk).update(latitude=None, longitude=None)
        JournalEntry.objects.filter(pk=self.entry.pk).update(latitude=None, longitude=None)
        self.add_contact(self.entry, "K1GRID", "missing-origin", grid_square="EN34")
        response = self.client.get(self.map_url)
        self.assertContains(response, "Contact markers are shown, but authorized Journal Locations do not have coordinates")
        self.assertContains(response, 'id="adventure-{}-contact-map-data"'.format(self.adventure.pk))
        self.assertContains(response, '"mapped": 1')
        self.assertContains(response, '"path_count": 0')
        self.assertContains(response, '"origin": null')
        self.assertContains(response, "K1GRID")
        self.assertTrue(response.context["contact_map"]["has_map_points"])
        self.assertEqual(response.context["contact_map"]["path_count"], 0)
        self.assertNotContains(response, '"latitude": 0')
        self.assertNotContains(response, '"longitude": 0')

        JournalEntry.objects.filter(pk=self.entry.pk).update(
            latitude="0.000000", longitude="0.000000"
        )
        response = self.client.get(self.map_url)
        self.assertContains(response, "Contact markers are shown")
        self.assertNotContains(response, '"origin": {')

    def test_unmappable_contacts_are_counted_and_explained_without_blank_map(self):
        Location.objects.filter(pk=self.origin.pk).update(latitude=None, longitude=None)
        JournalEntry.objects.filter(pk=self.entry.pk).update(latitude=None, longitude=None)
        self.add_contact(
            self.entry,
            "K1NONE",
            "unmappable",
            state="MN",
            country="United States",
        )

        response = self.client.get(self.map_url)

        self.assertContains(
            response,
            "None of this Adventure&#x27;s authorized contacts contain coordinates or grid squares that can be placed on the map.",
        )
        self.assertContains(response, "1 contact could not be mapped")
        self.assertEqual(response.context["contact_map"]["mapped"], 0)
        self.assertEqual(response.context["contact_map"]["unmapped"], 1)
        self.assertFalse(response.context["contact_map"]["has_map_points"])
        self.assertContains(response, 'id="adventure-{}-contact-map-data"'.format(self.adventure.pk))

    def test_private_location_coordinates_are_not_serialized_to_visitor(self):
        self.origin.visibility = Location.Visibility.PRIVATE
        self.origin.save(update_fields=["visibility"])
        self.add_contact(
            self.entry,
            "K1PRIVATE",
            "private-origin",
            latitude="41.123456",
            longitude="-71.654321",
        )
        response = self.client.get(self.map_url)
        self.assertContains(response, "None of this Adventure&#x27;s authorized contacts")
        for value in ("44.1", "-93.2", "41.123456", "-71.654321"):
            self.assertNotContains(response, value)

    def test_actions_order_compact_headers_and_full_page_headers(self):
        self.add_contact(self.entry, "K1ROW", "row")
        self.client.force_login(self.owner)
        detail = self.client.get(self.detail_url)
        html = detail.content.decode()
        add_at = html.index("Add Contact")
        import_at = html.index("Import Contacts", add_at)
        map_at = html.index("View Map", import_at)
        row_at = html.index("K1ROW", map_at)
        self.assertLess(add_at, import_at)
        self.assertLess(import_at, map_at)
        self.assertLess(map_at, row_at)
        self.assertContains(detail, '<thead class="visually-hidden">')
        self.assertNotContains(detail, "<thead><tr><th>Date</th>")

        full = self.client.get(reverse("adventure_contacts", args=[self.adventure.slug]))
        self.assertContains(full, "<thead>")
        self.assertContains(full, "<th>Callsign</th>", html=True)

    def test_empty_map_has_useful_state_and_map_javascript_keeps_fullscreen_paths(self):
        response = self.client.get(self.map_url)
        self.assertContains(response, "This Adventure has no contacts to map")
        self.assertContains(response, "0 of 0 Adventure contacts have map coordinates")
        from django.conf import settings

        source = (settings.BASE_DIR / "static" / "js" / "contact-map.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("fullscreenControl: true", source)
        self.assertIn("contact.origin.latitude", source)
        self.assertIn("radioOutdoorsFitMap", source)
        self.assertIn("const origins =", source)
        self.assertIn("if (currentOrigins.length && filter(\"lines\").checked)", source)

    def test_advanced_controls_and_maplibre_assets_are_removed_from_map_page(self):
        self.add_contact(
            self.entry,
            "K1GLOBE",
            "globe",
            latitude="40.100000",
            longitude="-75.200000",
        )
        response = self.client.get(self.map_url)
        for removed in (
            'data-journal-projection="globe"', 'data-journal-projection="flat"',
            'data-journal-display="day"', 'data-journal-display="night"',
            "data-journal-gray-line", "data-journal-globe-reset",
            "vendor/maplibre-gl/5.24.0/maplibre-gl.js",
            "vendor/maplibre-gl/5.24.0/maplibre-gl.css",
        ):
            self.assertNotContains(response, removed)
        self.assertContains(response, "contact-map.js")
        self.assertNotContains(self.client.get(self.detail_url), "journal-contact-globe.js")

    def test_overlay_and_animation_code_is_absent(self):
        from django.conf import settings

        source = (settings.BASE_DIR / "static" / "js" / "contact-map.js").read_text(encoding="utf-8")
        for removed in ("grayLine", "requestAnimationFrame", "contactAnimation", "contact-geography-display"):
            self.assertNotIn(removed, source)
        self.assertFalse((settings.BASE_DIR / "static" / "js" / "journal-contact-globe.js").exists())

    def test_static_map_uses_one_path_renderer(self):
        from django.conf import settings

        source = (settings.BASE_DIR / "static" / "js" / "contact-map.js").read_text(encoding="utf-8")
        self.assertEqual(source.count("new google.maps.Polyline"), 1)
        self.assertIn('const CONTACT_PATH_COLOR = "#e47b08"', source)
        self.assertIn("const CONTACT_PATH_STROKE_WIDTH = 4", source)
        self.assertIn("geodesic: true", source)

    def test_google_contact_markers_keep_grouping_and_origin_distinction(self):
        from django.conf import settings

        javascript = (settings.BASE_DIR / "static" / "js" / "contact-map.js").read_text(encoding="utf-8")
        self.assertIn("const groups = new Map()", javascript)
        self.assertIn('glyph: grouped ? String(Math.min(group.length, 99)) : "C"', javascript)
        self.assertIn('glyph: "J"', javascript)
