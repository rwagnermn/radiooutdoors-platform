from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, JournalContact, JournalEntry, Location, MemberProfile


class AdventureContactGeographyTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("geo-owner", password="test")
        MemberProfile.objects.create(user=self.owner, callsign="W0GEO", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)
        self.other = users.objects.create_user("geo-other", password="test")
        self.location_a = Location.objects.create(name="First Site", created_by=self.owner, latitude=45, longitude=-93)
        self.location_b = Location.objects.create(name="Second Site", created_by=self.owner, latitude=46, longitude=-94)
        self.adventure = Adventure.objects.create(owner=self.owner, title='North <Shore> & "Weekend"', operating_callsign="W0GEO", is_public=True)
        self.first = JournalEntry.objects.create(adventure=self.adventure, location=self.location_a, latitude=45, longitude=-93, title="First Journal", is_public=True)
        self.second = JournalEntry.objects.create(adventure=self.adventure, location=self.location_b, latitude=46, longitude=-94, title="Second Journal", is_public=True)
        self.private = JournalEntry.objects.create(adventure=self.adventure, location=self.location_b, latitude=46, longitude=-94, title="Private Journal", is_public=False)
        self.contacts = [
            self.contact(self.first, "K1FIRST", "20m", "SSB", "2026-01-01", 40, -75),
            self.contact(self.second, "K1SECOND", "40m", "CW", "2026-06-01", 41, -76),
            self.contact(self.private, "K1PRIVATE", "10m", "FM", "2026-07-01", 42, -77),
        ]
        other_adventure = Adventure.objects.create(owner=self.other, title="Other Adventure", is_public=True)
        other_journal = JournalEntry.objects.create(adventure=other_adventure, title="Foreign Journal", is_public=True)
        self.contact(other_journal, "K1FOREIGN", "80m", "AM", "2026-08-01", 43, -78)
        self.url = reverse("adventure_contact_geography", args=[self.adventure.slug])

    @staticmethod
    def contact(journal, callsign, band, mode, date, latitude, longitude):
        return JournalContact.objects.create(
            journal_entry=journal, qso_date=date, callsign=callsign, band=band, mode=mode,
            latitude=latitude, longitude=longitude, fingerprint=f"geo-{callsign}",
        )

    def test_public_payload_combines_only_authorized_journals_and_escapes_title(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Contacts From Adventure (North &lt;Shore&gt; &amp; &quot;Weekend&quot;)")
        self.assertContains(response, "All Journals")
        self.assertContains(response, "First Journal")
        self.assertContains(response, "Second Journal")
        self.assertContains(response, "K1FIRST")
        self.assertContains(response, "K1SECOND")
        self.assertNotContains(response, "Private Journal")
        self.assertNotContains(response, "K1PRIVATE")
        self.assertNotContains(response, "Foreign Journal")
        self.assertNotContains(response, "K1FOREIGN")
        self.assertEqual(response.context["contact_map"]["mapped"], 2)
        self.assertEqual(response.context["contact_map"]["path_count"], 2)

    def test_owner_receives_private_journal_and_each_contact_has_its_journal_origin(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        payload = response.context["contact_map"]
        self.assertEqual(payload["mapped"], 3)
        self.assertContains(response, "Private Journal")
        origins = {point["callsign"]: point["origin"] for point in payload["contacts"]}
        self.assertEqual(origins["K1FIRST"]["latitude"], 45.0)
        self.assertEqual(origins["K1SECOND"]["latitude"], 46.0)

    def test_journal_entry_redirects_to_adventure_url_with_preselection(self):
        legacy = self.client.get(reverse("journal_contact_map", args=[self.first.pk]))
        self.assertRedirects(legacy, f"{self.url}?journal={self.first.pk}", fetch_redirect_response=False)
        selected = self.client.get(f"{self.url}?journal={self.first.pk}")
        self.assertContains(selected, f'<option value="{self.first.pk}" selected>First Journal</option>', html=True)
        self.assertContains(selected, "Second Journal")

    def test_controls_filters_curves_animation_and_failure_isolation_are_wired(self):
        response = self.client.get(self.url)
        for value in ('data-contact-basemap="roadmap"', 'data-contact-basemap="satellite"', 'data-journal-projection="globe"', 'data-journal-projection="flat"', 'data-journal-display="day"', 'data-journal-display="night"', "data-journal-gray-line"):
            self.assertContains(response, value)
        flat = (Path(settings.BASE_DIR) / "static/js/contact-map.js").read_text(encoding="utf-8")
        globe = (Path(settings.BASE_DIR) / "static/js/journal-contact-globe.js").read_text(encoding="utf-8")
        self.assertIn("greatCircleCoordinates", globe)
        self.assertIn("geodesic: true", flat)
        self.assertIn("const PATH_LEG_MS = 500", globe)
        self.assertIn("const CONTACT_PATH_LEG_MS = 500", flat)
        self.assertIn('"circle-radius": PATH_WIDTH / 2', globe)
        self.assertIn("CONTACT_PATH_STROKE_WIDTH", flat)
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)")', flat)
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)")', globe)
        self.assertIn("try {", globe)
        self.assertIn("contact-geography-filter-change", globe)
        self.assertIn("map.setMapTypeId", flat)
        self.assertIn("toggleGrayLine", globe)
