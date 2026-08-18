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

    def test_public_contact_payload_contains_destination_and_journal_origin(self):
        contact = self.add_contact()
        response = self.client.get(reverse("map_explorer"))
        points = response.context["contact_points"]
        self.assertEqual(len(points), 1)
        point = points[0]
        self.assertEqual(point["contact_id"], contact.pk)
        self.assertEqual(point["marker_type"], "contact")
        self.assertEqual(point["latitude"], 45.520833)
        self.assertEqual(point["longitude"], -93.291667)
        self.assertEqual(point["origin_latitude"], 45.1)
        self.assertEqual(point["origin_longitude"], -93.1)
        self.assertEqual(point["journal_id"], self.journal.pk)

    def test_contacts_without_coordinates_or_valid_grid_are_omitted(self):
        self.add_contact(grid_square="", latitude=None, longitude=None)
        response = self.client.get(reverse("map_explorer"))
        self.assertEqual(response.context["contact_points"], [])

    def test_private_journal_geography_is_owner_only(self):
        contact = self.add_contact(callsign="K1PRIVATE")
        self.journal.is_public = False
        self.journal.save(update_fields=["is_public"])
        visitor = self.client.get(reverse("map_explorer"))
        self.assertEqual(visitor.context["contact_points"], [])
        self.assertNotContains(visitor, str(contact.latitude))
        self.client.force_login(self.owner)
        owner = self.client.get(reverse("map_explorer"))
        self.assertEqual(owner.context["contact_points"][0]["contact_id"], contact.pk)

    def test_private_origin_suppresses_contact_geography_for_visitor(self):
        contact = self.add_contact(callsign="K1SECRET")
        self.origin.visibility = Location.Visibility.PRIVATE
        self.origin.save(update_fields=["visibility"])
        visitor = self.client.get(reverse("map_explorer"))
        self.assertEqual(visitor.context["contact_points"], [])
        self.assertNotContains(visitor, str(contact.longitude))
        self.client.force_login(self.owner)
        owner = self.client.get(reverse("map_explorer"))
        self.assertEqual(owner.context["contact_points"][0]["contact_id"], contact.pk)

    def test_private_resolved_destination_is_not_exposed_to_visitor(self):
        destination = Location.objects.create(
            name="Private Contact Destination",
            created_by=self.owner,
            visibility=Location.Visibility.PRIVATE,
            latitude="40.123456",
            longitude="-75.654321",
        )
        contact = self.add_contact(
            callsign="K1RESOLVED",
            grid_square="",
            latitude=None,
            longitude=None,
            resolved_location=destination,
        )
        visitor = self.client.get(reverse("map_explorer"))
        self.assertEqual(visitor.context["contact_points"], [])
        self.assertNotContains(visitor, "40.123456")
        self.client.force_login(self.owner)
        owner = self.client.get(reverse("map_explorer"))
        self.assertEqual(owner.context["contact_points"][0]["contact_id"], contact.pk)

    def test_main_map_renders_contact_filter_markers_paths_and_map_type_restore(self):
        self.add_contact()
        response = self.client.get(reverse("map_explorer"))
        self.assertContains(response, 'id="show-contact-pins" checked')
        self.assertContains(response, '"marker_type": "contact"')
        self.assertContains(response, "new google.maps.Polyline")
        self.assertContains(response, 'map.addListener("maptypeid_changed"')
        self.assertContains(response, "record.path.setMap")
