from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, JournalContact, JournalEntry, Location


class GlobalContactMapTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="W0MAP", password="test-password"
        )
        self.origin = Location.objects.create(
            name="Public Contact Origin",
            created_by=self.owner,
            latitude="45.100000",
            longitude="-93.100000",
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Mapped Contact Adventure",
            location=self.origin,
            is_public=True,
        )
        self.journal = JournalEntry.objects.create(
            adventure=self.adventure,
            location=self.origin,
            latitude=self.origin.latitude,
            longitude=self.origin.longitude,
            title="Mapped Contact Journal",
            body="Map tests",
            is_public=True,
        )

    def add_contact(self, callsign="K1MAP", **overrides):
        defaults = {
            "owner": self.owner,
            "adventure": self.adventure,
            "journal_entry": self.journal,
            "qso_date": "2026-08-18",
            "time_on": "01:45",
            "callsign": callsign,
            "grid_square": "EN35IM",
            "latitude": "45.520833",
            "longitude": "-93.291667",
            "fingerprint": f"global-map-{callsign}",
        }
        defaults.update(overrides)
        return JournalContact.objects.create(**defaults)

    def test_main_map_never_serializes_contact_markers_or_coordinates(self):
        self.add_contact(callsign="K1PRIVATE")
        self.journal.is_public = False
        self.journal.save(update_fields=["is_public"])

        for user in (None, self.owner):
            if user is None:
                self.client.logout()
            else:
                self.client.force_login(user)
            response = self.client.get(reverse("map_explorer"))
            self.assertNotIn("contact_points", response.context)
            self.assertNotContains(response, "K1PRIVATE")
            self.assertNotContains(response, "45.520833")
            self.assertNotContains(response, "-93.291667")
            self.assertNotContains(response, '"marker_type": "contact"')
            self.assertNotContains(response, "radio-outdoors-contact-map-data")

    def test_main_map_contact_filter_legend_marker_and_path_code_are_absent(self):
        self.add_contact()
        response = self.client.get(reverse("map_explorer"))
        html = response.content.decode()

        self.assertNotIn('id="show-contact-pins"', html)
        self.assertNotIn("map-legend-pin-blue", html)
        self.assertNotIn(">Contact</span>", html)
        self.assertNotIn("contactPoints", html)
        self.assertNotIn('marker_type === "contact"', html)
        self.assertNotIn("new google.maps.Polyline", html)
        self.assertNotIn("pathRecords", html)

    def test_location_advisory_and_active_adventure_markers_remain(self):
        self.origin.has_operating_advisory = True
        self.origin.operating_advisory = "Use the east entrance."
        self.origin.save(
            update_fields=["has_operating_advisory", "operating_advisory"]
        )
        plain = Location.objects.create(
            name="Plain Location",
            created_by=self.owner,
            latitude="46.200000",
            longitude="-94.200000",
        )
        self.add_contact()

        response = self.client.get(reverse("map_explorer"))
        points = response.context["map_points"]
        by_name = {point["location_name"]: point for point in points}

        self.assertEqual(response.context["point_count"], 2)
        self.assertIn(plain.name, by_name)
        self.assertTrue(by_name[self.origin.name]["has_operating_advisory"])
        self.assertTrue(by_name[self.origin.name]["has_open_adventure"])
        self.assertContains(response, 'id="show-location-pins" checked')
        self.assertContains(response, 'id="show-open-pins" checked')
        self.assertContains(response, "Operating Advisories — Always shown")
        self.assertContains(response, "points.forEach")

    def test_authorized_journal_contacts_map_keeps_markers_and_paths(self):
        contact = self.add_contact()
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("adventure_contact_geography", args=[self.adventure.slug]) + f"?journal={self.journal.pk}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Contacts From Adventure ({self.adventure.title})")
        self.assertContains(response, contact.callsign)
        self.assertContains(response, '"latitude": 45.520833')
        self.assertContains(response, '"longitude": -93.291667')
        self.assertContains(response, "Contact path")
        self.assertContains(response, "journal-contact-globe.js")
        self.assertEqual(response.context["contact_map"]["path_count"], 1)
