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
        self.map_url = reverse("journal_contact_map", args=[self.entry.pk])
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
            self.assertEqual(self.client.get(self.map_url).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.map_url).status_code, 200)

    def test_map_uses_journal_origin_and_only_current_journal_contacts(self):
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
        self.assertContains(response, "Back to Journal")
        self.assertContains(response, "Journal Location")
        self.assertContains(response, "Contact path")
        self.assertContains(response, '"mapped": 2')
        self.assertContains(response, '"unmapped": 1')
        self.assertContains(response, '"latitude": 44.1')
        self.assertContains(response, '"longitude": -93.2')
        self.assertContains(response, mapped.callsign)
        self.assertContains(response, "K1GRID")
        self.assertContains(response, "K1NONE")
        self.assertNotContains(response, "K1WRONG")
        self.assertEqual(response.context["contact_map"]["mapped"], 2)
        self.assertEqual(len(response.context["contact_map"]["contacts"]), 2)

    def test_missing_journal_origin_still_maps_contacts_without_paths(self):
        Location.objects.filter(pk=self.origin.pk).update(latitude=None, longitude=None)
        JournalEntry.objects.filter(pk=self.entry.pk).update(latitude=None, longitude=None)
        self.add_contact(self.entry, "K1GRID", "missing-origin", grid_square="EN34")
        response = self.client.get(self.map_url)
        self.assertContains(response, "Contact markers are shown, but contact paths cannot be drawn")
        self.assertContains(response, 'id="journal-{}-contact-map-data"'.format(self.entry.pk))
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
            "None of this Journal&#x27;s contacts contain coordinates or grid squares that can be placed on the map.",
        )
        self.assertContains(response, "1 contact could not be mapped")
        self.assertEqual(response.context["contact_map"]["mapped"], 0)
        self.assertEqual(response.context["contact_map"]["unmapped"], 1)
        self.assertFalse(response.context["contact_map"]["has_map_points"])
        self.assertContains(response, 'id="journal-{}-contact-map-data"'.format(self.entry.pk))

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
        self.assertContains(response, "Journal uses a Private Location")
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
        self.assertContains(response, "This Journal has no contacts to map")
        self.assertContains(response, "0 of 0 contacts can be mapped")
        from django.conf import settings

        source = (settings.BASE_DIR / "static" / "js" / "contact-map.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("fullscreenControl: true", source)
        self.assertIn("path: [origin", source)
        self.assertIn("radioOutdoorsFitMap", source)
        self.assertIn("const origin = data.origin ?", source)
        self.assertIn("if (origin && filter(\"lines\").checked)", source)

    def test_globe_controls_assets_fallback_and_attribution_are_scoped_to_map_page(self):
        self.add_contact(
            self.entry,
            "K1GLOBE",
            "globe",
            latitude="40.100000",
            longitude="-75.200000",
        )
        response = self.client.get(self.map_url)
        self.assertContains(response, 'data-journal-projection="globe"')
        self.assertContains(response, 'data-journal-projection="flat"')
        self.assertContains(response, 'data-journal-display="day"')
        self.assertContains(response, 'data-journal-display="night"')
        self.assertContains(response, 'data-journal-display="gray-line"')
        self.assertContains(response, 'data-journal-globe-reset')
        self.assertContains(response, 'aria-pressed="true">Globe</button>')
        self.assertContains(response, 'aria-pressed="true">Day</button>')
        self.assertContains(response, "vendor/maplibre-gl/5.24.0/maplibre-gl.js")
        self.assertContains(response, "vendor/maplibre-gl/5.24.0/maplibre-gl.css")
        self.assertNotContains(self.client.get(self.detail_url), "journal-contact-globe.js")

        from django.conf import settings

        source = (
            settings.BASE_DIR / "static" / "js" / "journal-contact-globe.js"
        ).read_text(encoding="utf-8")
        self.assertIn('projection: { type: "globe" }', source)
        self.assertIn("greatCircleCoordinates(origin", source)
        self.assertIn("maplibregl.FullscreenControl", source)
        self.assertIn("supportsWebGL()", source)
        self.assertIn('canvas.getContext("webgl2"', source)
        self.assertIn("Flat Map shown because interactive globe rendering is unavailable", source)
        self.assertIn("OpenFreeMap © OpenMapTiles · Data © OpenStreetMap contributors", source)
        self.assertIn("localStorage.getItem(PREFERENCE_KEY)", source)
        self.assertIn("localStorage.setItem(PREFERENCE_KEY", source)
        self.assertNotIn("demotiles.maplibre.org", source)
        self.assertNotIn("mapbox.com", source)
        self.assertNotIn("maptiler.com", source)

    def test_gray_line_uses_current_utc_and_updates_one_existing_source(self):
        from django.conf import settings

        source = (
            settings.BASE_DIR / "static" / "js" / "journal-contact-globe.js"
        ).read_text(encoding="utf-8")
        self.assertIn("grayLineGeoJSON(now)", source)
        self.assertIn("updateGrayLine(new Date())", source)
        self.assertIn("source.setData(geojson)", source)
        self.assertIn("5 * 60 * 1000", source)
        self.assertIn("now.toISOString()", source)
        self.assertIn("pointer-events:none", (settings.BASE_DIR / "static" / "css" / "style.css").read_text(encoding="utf-8"))

    def test_globe_style_changes_restore_one_authorized_overlay_set(self):
        from django.conf import settings

        source = (
            settings.BASE_DIR / "static" / "js" / "journal-contact-globe.js"
        ).read_text(encoding="utf-8")
        self.assertIn("const authorizedPathData =", source)
        self.assertIn("function restoreJournalOverlays(generation)", source)
        self.assertIn("generation !== styleGeneration", source)
        self.assertIn('map.on("style.load", restoreCurrentStyle)', source)
        self.assertIn('map.on("styledata", restoreCurrentStyle)', source)
        self.assertIn("map.setStyle(", source)
        self.assertIn("restoreJournalOverlays(styleGeneration)", source)
        self.assertIn("if (!map.getSource(PATH_SOURCE))", source)
        self.assertIn("if (!map.getLayer(PATH_LAYER))", source)
        self.assertIn("if (!map.getLayer(layer.id))", source)
        self.assertIn("map.moveLayer(PATH_LAYER, beforeId)", source)
        self.assertIn("if (!map || markersInitialized) return", source)
        self.assertIn("authorizedPathData.features.length", source)
        self.assertIn("if (data.origin)", source)
        self.assertIn("center: initialCenter()", source)
        self.assertIn("contactPathSourceCount", source)
        self.assertIn("contactPathLayerCount", source)
        self.assertIn("mapMarkerCount", source)
        self.assertIn("generation === restoredGeneration", source)
        self.assertIn("overlaysRestoring", source)
        self.assertIn('overlayPending = "true"', source)
        self.assertIn("requestedStyleGeneration", source)
        self.assertNotIn("setTimeout(", source)

    def test_contact_marker_head_is_half_size_centered_and_origin_is_unchanged(self):
        from django.conf import settings

        javascript = (
            settings.BASE_DIR / "static" / "js" / "journal-contact-globe.js"
        ).read_text(encoding="utf-8")
        stylesheet = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn('markerElement("contact", `Contact ${contact.callsign}`, "C")', javascript)
        self.assertIn('head.className = "journal-globe-marker-head"', javascript)
        self.assertIn('head.setAttribute("aria-hidden", "true")', javascript)
        self.assertIn(".journal-globe-marker { display:inline-flex; width:34px; height:34px;", stylesheet)
        self.assertIn(".journal-globe-marker-head { display:inline-flex; width:17px; height:17px;", stylesheet)
        self.assertIn("align-items:center; justify-content:center; padding:0;", stylesheet)
        self.assertIn("font-size:.42rem;", stylesheet)
        self.assertIn("line-height:1;", stylesheet)
        self.assertIn(".journal-globe-marker-origin { width:40px; height:40px; }", stylesheet)
        self.assertIn(".journal-globe-marker-origin .journal-globe-marker-head { width:40px; height:40px;", stylesheet)
