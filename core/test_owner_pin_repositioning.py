from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    Adventure, CoordinateChangeAudit, Location, MemberProfile, OperatingLocation,
)


class OwnerPinRepositioningTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("pinowner", password="secret")
        self.other = get_user_model().objects.create_user("pinother", password="secret")
        for user, callsign in ((self.owner, "W5PIN"), (self.other, "W5OTHER")):
            MemberProfile.objects.create(
                user=user, callsign=callsign, callsign_verified=True,
                verification_method=MemberProfile.VerificationMethod.QRZ,
            )
        self.location = Location.objects.create(
            name="Owner Pin Park", created_by=self.owner,
            street_address="1 Original Road", city="Oldtown", state="MN",
            description="Keep this description", latitude="44.100000",
            longitude="-93.100000",
        )
        self.position = OperatingLocation.objects.create(
            location=self.location, created_by=self.owner, name="North Setup",
            description="Keep the position notes", latitude="44.110000",
            longitude="-93.110000",
        )

    def edit_url(self, kind, pk):
        return reverse("edit_owned_pin_position", args=[kind, pk])

    def test_owner_moves_location_without_changing_address_position_or_content(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.edit_url("location", self.location.pk), {
            "latitude": "45.123456", "longitude": "-94.654321",
        }, follow=True)
        self.assertContains(response, "Pin position updated successfully.")
        self.location.refresh_from_db(); self.position.refresh_from_db()
        self.assertEqual(str(self.location.latitude), "45.123456")
        self.assertEqual(self.location.street_address, "1 Original Road")
        self.assertEqual(self.location.description, "Keep this description")
        self.assertEqual(str(self.position.latitude), "44.110000")
        audit = CoordinateChangeAudit.objects.get()
        self.assertEqual((audit.record_type, audit.actor), ("location", self.owner))
        self.assertEqual(str(audit.previous_latitude), "44.100000")

    def test_owner_moves_position_without_moving_location(self):
        self.client.force_login(self.owner)
        self.client.post(self.edit_url("operating_position", self.position.pk), {
            "latitude": "46.000001", "longitude": "-95.000001",
        })
        self.position.refresh_from_db(); self.location.refresh_from_db()
        self.assertEqual(str(self.position.latitude), "46.000001")
        self.assertEqual(self.position.description, "Keep the position notes")
        self.assertEqual(str(self.location.latitude), "44.100000")

    def test_adventure_owner_can_move_legacy_position_but_not_location(self):
        legacy = OperatingLocation.objects.create(
            location=self.location, name="Legacy Setup",
            latitude="44.200000", longitude="-93.200000",
        )
        Adventure.objects.create(owner=self.other, location=self.location, operating_location=legacy)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.edit_url("location", self.location.pk)).status_code, 403)
        self.assertEqual(self.client.get(self.edit_url("operating_position", legacy.pk)).status_code, 200)

    def test_non_owner_and_visitor_are_denied_while_staff_is_allowed(self):
        self.assertEqual(self.client.get(self.edit_url("location", self.location.pk)).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.edit_url("location", self.location.pk)).status_code, 403)
        staff = get_user_model().objects.create_user("pinstaff", password="secret", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.edit_url("location", self.location.pk)).status_code, 200)

    def test_cancel_get_makes_no_change_and_page_is_explicit_editing_mode(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.edit_url("location", self.location.pk))
        self.assertContains(response, "Editing Location position: Owner Pin Park")
        self.assertContains(response, "Drag the pin or click the map")
        self.assertContains(response, "Save Position")
        self.assertContains(response, "Cancel")
        self.location.refresh_from_db()
        self.assertEqual(str(self.location.latitude), "44.100000")
        self.assertFalse(CoordinateChangeAudit.objects.exists())

    def test_shared_use_warning_only_for_other_members_records(self):
        Adventure.objects.create(owner=self.other, location=self.location)
        self.client.force_login(self.owner)
        response = self.client.get(self.edit_url("location", self.location.pk))
        self.assertContains(response, "This Location is used by other Adventures.")
        self.location.adventures.all().delete()
        Adventure.objects.create(owner=self.owner, location=self.location)
        response = self.client.get(self.edit_url("location", self.location.pk))
        self.assertNotContains(response, "This Location is used by other Adventures.")

    def test_location_removal_is_optional_but_position_requires_replacement(self):
        self.client.force_login(self.owner)
        self.client.post(self.edit_url("location", self.location.pk), {
            "latitude": "", "longitude": "",
        })
        self.location.refresh_from_db()
        self.assertIsNone(self.location.latitude)
        response = self.client.post(self.edit_url("operating_position", self.position.pk), {
            "latitude": "", "longitude": "",
        })
        self.assertContains(response, "Place a new pin before saving.")
        self.position.refresh_from_db()
        self.assertIsNotNone(self.position.latitude)

    def test_pin_repositioning_never_overwrites_entered_address(self):
        self.client.force_login(self.owner)
        self.client.post(self.edit_url("location", self.location.pk), {
            "latitude": "45", "longitude": "-94", "update_address": "1",
            "street_address": "2 New Road", "city": "Newtown", "state": "WI",
            "postal_code": "54000", "country": "USA",
        })
        self.location.refresh_from_db()
        self.assertEqual(self.location.street_address, "1 Original Road")
        self.assertFalse(CoordinateChangeAudit.objects.get().address_updated)

    def test_map_and_location_detail_show_controls_only_to_authorized_user(self):
        self.client.force_login(self.owner)
        main_map = self.client.get(reverse("map_explorer"))
        self.assertContains(main_map, "Edit Pin Position")
        detail = self.client.get(reverse("location_detail", args=[self.location.pk]))
        self.assertContains(detail, "Edit Pin Position")
        self.client.force_login(self.other)
        main_map = self.client.get(reverse("map_explorer"))
        self.assertNotContains(main_map, self.edit_url("location", self.location.pk))
        detail = self.client.get(reverse("location_detail", args=[self.location.pk]))
        self.assertNotContains(detail, self.edit_url("location", self.location.pk))

    def test_editable_map_script_keeps_one_marker_and_suppresses_drag_click(self):
        from django.conf import settings
        source = (settings.BASE_DIR / "static" / "js" / "editable-map-pin.js").read_text(encoding="utf-8")
        self.assertIn("let marker = null", source)
        self.assertIn("suppressMapClickUntil", source)
        self.assertIn('map.addListener("dragstart"', source)
        self.assertIn("marker.position = clean", source)
