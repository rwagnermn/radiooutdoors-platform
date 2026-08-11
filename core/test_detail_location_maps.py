from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from unittest.mock import PropertyMock, patch

from core.models import Adventure, Location, MemberProfile


@override_settings(
    GOOGLE_MAPS_API_KEY="browser-map-key-sentinel",
    GOOGLE_GEOCODING_API_KEY="server-geocoding-secret-sentinel",
)
class DetailLocationMapTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("MAPOWNER", password="test-password")
        self.other = users.create_user("MAPOTHER", password="test-password")
        for user in (self.owner, self.other):
            MemberProfile.objects.create(
                user=user,
                callsign=user.username,
                callsign_verified=True,
                verification_method=MemberProfile.VerificationMethod.QRZ,
            )
        self.location = Location.objects.create(
            name="Caribou Falls Unique Area — US-12388",
            created_by=self.owner,
            latitude="47.468800",
            longitude="-91.032100",
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Caribou Falls Activation",
            location=self.location,
            is_public=True,
        )

    def test_public_location_detail_contains_one_safe_map_point(self):
        response = self.client.get(reverse("location_detail", args=[self.location.pk]))
        self.assertContains(response, "Location Map")
        self.assertContains(response, 'data-single-location-map', count=1)
        self.assertContains(response, "47.4688")
        self.assertContains(response, "-91.0321")
        self.assertNotContains(response, "server-geocoding-secret-sentinel")

    def test_adventure_detail_contains_only_associated_location_map(self):
        Location.objects.create(
            name="Unrelated Location", latitude="40.1", longitude="-90.1"
        )
        response = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(response, "Adventure Location")
        self.assertContains(response, 'data-single-location-map', count=1)
        self.assertContains(response, self.location.name)
        self.assertNotContains(response, "Unrelated Location")

    def test_coordinate_free_location_omits_map_for_ordinary_viewer(self):
        location = Location.objects.create(name="No Pin", created_by=self.owner)
        response = self.client.get(reverse("location_detail", args=[location.pk]))
        self.assertNotContains(response, 'data-single-location-map')
        self.assertNotContains(response, "Location pin not yet set.")

    def test_owner_sees_missing_pin_and_edit_action(self):
        location = Location.objects.create(name="Owner No Pin", created_by=self.owner)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("location_detail", args=[location.pk]))
        self.assertContains(response, "Location pin not yet set.")
        self.assertContains(response, "Edit Pin Position")

    def test_unauthorized_viewer_has_no_edit_pin_action(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("location_detail", args=[self.location.pk]))
        edit_url = reverse("edit_owned_pin_position", args=["location", self.location.pk])
        self.assertNotContains(response, edit_url)

    def test_private_coordinates_absent_for_unauthorized_adventure_viewer(self):
        self.location.visibility = Location.Visibility.PRIVATE
        self.location.save(update_fields=["visibility"])
        response = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(response, "Private Location")
        self.assertNotContains(response, "47.4688")
        self.assertNotContains(response, "-91.0321")
        self.assertNotContains(response, 'id="adventure-location-map"')

    def test_private_location_map_visible_to_owner(self):
        self.location.visibility = Location.Visibility.PRIVATE
        self.location.save(update_fields=["visibility"])
        self.client.force_login(self.owner)
        response = self.client.get(reverse("location_detail", args=[self.location.pk]))
        self.assertContains(response, 'id="location-view-map"')
        self.assertContains(response, "47.4688")
        self.assertContains(response, "Edit Pin Position")

    def test_adventure_owner_receives_location_and_pin_edit_links(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(response, reverse("location_detail", args=[self.location.pk]))
        self.assertContains(
            response,
            reverse("edit_owned_pin_position", args=["location", self.location.pk]),
        )

    def test_view_only_map_script_has_no_coordinate_edit_handlers(self):
        from django.conf import settings

        source = (
            settings.BASE_DIR / "static" / "js" / "single-location-map.js"
        ).read_text(encoding="utf-8")
        self.assertNotIn("gmpDraggable", source)
        self.assertNotIn('map.addListener("click"', source)
        self.assertNotIn("GOOGLE_GEOCODING_API_KEY", source)
        self.assertIn('addListenerOnce(map, "idle"', source)
        self.assertIn('removeAttribute("aria-busy")', source)

    def test_assigned_location_photo_uses_adventure_cover_layout(self):
        with patch.object(
            Location,
            "display_photo_url",
            new_callable=PropertyMock,
            return_value="/media/location_photos/assigned.jpg",
        ):
            response = self.client.get(
                reverse("location_detail", args=[self.location.pk])
            )
        self.assertContains(response, "/media/location_photos/assigned.jpg")
        self.assertContains(response, "adventure-cover-frame location-cover-frame")
        self.assertContains(
            response,
            "adventure-cover-image location-primary-photo",
        )
        self.assertLess(
            response.content.index(self.location.name.encode()),
            response.content.index(b"/media/location_photos/assigned.jpg"),
        )

    def test_generic_location_photo_placeholder_remains_available(self):
        with patch.object(
            Location,
            "display_photo_url",
            new_callable=PropertyMock,
            return_value="",
        ):
            response = self.client.get(
                reverse("location_detail", args=[self.location.pk])
            )
        self.assertContains(response, "Radio Outdoors Location photo placeholder")
        self.assertContains(response, "location-primary-photo-placeholder")
