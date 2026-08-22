from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, JournalContact, JournalEntry, Location, MemberProfile


class ContactMapSimplificationTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("simple-map-owner", password="test")
        MemberProfile.objects.create(
            user=self.owner, callsign="W0MAP", callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.location = Location.objects.create(
            name="Simple Map Park", created_by=self.owner,
            latitude="44.100000", longitude="-93.200000",
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner, title="Minnesota North Shore Weekend",
            operating_callsign="W0MAP", is_public=True,
        )
        self.journal = JournalEntry.objects.create(
            adventure=self.adventure, location=self.location, title="First Journal",
            latitude=self.location.latitude, longitude=self.location.longitude, is_public=True,
        )
        JournalContact.objects.create(
            journal_entry=self.journal, qso_date="2026-08-21", callsign="K0TEST",
            latitude=40, longitude=-75, fingerprint="simple-map-contact",
        )
        self.url = reverse("adventure_contact_geography", args=[self.adventure.slug])

    def test_page_uses_one_simple_map_and_named_adventure_heading(self):
        response = self.client.get(self.url)
        self.assertContains(response, "<h1>Contacts from Adventure - Minnesota North Shore Weekend</h1>", html=True)
        self.assertContains(response, "Show Contact Lines")
        self.assertContains(response, "Contact path")
        for removed in (
            "data-contact-path-animation", "data-contact-basemap", "data-journal-projection",
            "data-journal-display", "data-journal-gray-line", "journal-contact-globe.js",
            "maplibre-gl.js", "maplibre-gl.css",
        ):
            self.assertNotContains(response, removed)

    def test_static_paths_are_orange_four_pixels_and_animation_is_absent(self):
        source = (Path(settings.BASE_DIR) / "static/js/contact-map.js").read_text(encoding="utf-8")
        css = (Path(settings.BASE_DIR) / "static/css/style.css").read_text(encoding="utf-8")
        self.assertIn('const CONTACT_PATH_COLOR = "#e47b08"', source)
        self.assertIn("const CONTACT_PATH_STROKE_WIDTH = 4", source)
        self.assertIn("strokeColor: CONTACT_PATH_COLOR", source)
        self.assertIn("strokeWeight: CONTACT_PATH_STROKE_WIDTH", source)
        self.assertIn("strokeOpacity: 1", source)
        self.assertIn("geodesic: true", source)
        self.assertIn("border-top:4px solid #e47b08", css)
        for removed in (
            "requestAnimationFrame", "cancelAnimationFrame", "CONTACT_PATH_LEG_MS",
            "contactAnimation", "journal-contact-path-ball", "visibilitychange",
            "grayLine", "contact-geography-display", "contact-geography-projection",
        ):
            self.assertNotIn(removed, source)
        self.assertNotIn("journal-contact-path-ball", css)

    def test_native_navigation_fullscreen_markers_and_path_endpoints_remain(self):
        source = (Path(settings.BASE_DIR) / "static/js/contact-map.js").read_text(encoding="utf-8")
        self.assertIn("fullscreenControl: true", source)
        self.assertIn("mapTypeControl: false", source)
        self.assertIn("new google.maps.marker.AdvancedMarkerElement", source)
        self.assertIn("{ lat: contact.origin.latitude, lng: contact.origin.longitude }", source)
        self.assertIn("{ lat: contact.latitude, lng: contact.longitude }", source)
        self.assertIn('if (currentOrigins.length && filter("lines").checked)', source)
        self.assertIn('String(item.journal_id) === journal', source)

    def test_private_journal_remains_server_side_excluded(self):
        self.journal.is_public = False
        self.journal.save(update_fields=["is_public"])
        public = self.client.get(self.url)
        self.assertNotContains(public, "First Journal")
        self.assertNotContains(public, "K0TEST")
        self.assertNotContains(public, '"latitude": 40.0')
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(self.url), "K0TEST")
