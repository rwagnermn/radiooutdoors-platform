from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from adventures.forms import JournalEntryForm, LocationForm
from core.location_privacy import can_view_location, visible_locations
from core.models import Adventure, Location, LocationType, MemberProfile
from core.pin_permissions import can_edit_location_pin


class PrivateLocationTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user("OWNER1", password="test-password")
        self.other = users.create_user("OTHER1", password="test-password")
        self.staff = users.create_user(
            "STAFF1", password="test-password", is_staff=True
        )
        for user in (self.owner, self.other):
            MemberProfile.objects.create(
                user=user,
                callsign=user.username,
                callsign_verified=True,
                verification_method=MemberProfile.VerificationMethod.QRZ,
            )
        self.location_type = LocationType.objects.get(key="cabin")
        self.public = Location.objects.create(
            name="Public Ridge",
            created_by=self.owner,
            visibility=Location.Visibility.PUBLIC,
            location_type=self.location_type.key,
            location_type_record=self.location_type,
            latitude="47.100001",
            longitude="-93.100001",
        )
        self.private = Location.objects.create(
            name="Secret Pike Cabin",
            created_by=self.owner,
            visibility=Location.Visibility.PRIVATE,
            location_type=self.location_type.key,
            location_type_record=self.location_type,
            street_address="123 Hidden Road",
            city="Hidden Town",
            latitude="47.654321",
            longitude="-93.123456",
        )

    def location_form_data(self, location, visibility):
        return {
            "name": location.name,
            "visibility": visibility,
            "location_type": self.location_type.key,
            "street_address": location.street_address,
            "address_line_2": location.address_line_2,
            "city": location.city,
            "state": location.state,
            "postal_code": location.postal_code,
            "country": location.country,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "official_website": location.official_website,
            "reference_code": location.reference_code,
            "description": location.description,
            "parking": location.parking,
            "restrooms": location.restrooms,
            "picnic_tables": location.picnic_tables,
            "shelter": location.shelter,
            "shade": location.shade,
            "power": location.power,
            "drinking_water": location.drinking_water,
            "cell_coverage_bars": location.cell_coverage_bars,
            "ambient_noise_level": location.ambient_noise_level,
            "has_operating_advisory": location.has_operating_advisory,
            "operating_advisory": location.operating_advisory,
        }

    def test_default_is_public_and_visibility_is_required(self):
        self.assertEqual(Location().visibility, Location.Visibility.PUBLIC)
        form = LocationForm(
            data={
                "name": "No Choice",
                "location_type": self.location_type.key,
                "country": "USA",
            },
            user=self.owner,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("visibility", form.errors)

    def test_server_side_visibility_queryset(self):
        self.assertSetEqual(
            set(visible_locations(self.owner)), {self.public, self.private}
        )
        self.assertSetEqual(set(visible_locations(self.other)), {self.public})
        self.assertSetEqual(
            set(visible_locations(self.staff)), {self.public, self.private}
        )
        self.assertTrue(can_view_location(self.owner, self.private))
        self.assertFalse(can_view_location(self.other, self.private))

    def test_private_location_absent_from_public_list_map_and_direct_url(self):
        for url in (reverse("locations"), reverse("map_explorer")):
            response = self.client.get(url)
            self.assertContains(response, self.public.name)
            self.assertNotContains(response, self.private.name)
            self.assertNotContains(response, self.private.street_address)
            self.assertNotContains(response, "47.654321")
            self.assertNotContains(response, "-93.123456")
        response = self.client.get(
            reverse("location_detail", args=[self.private.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_owner_and_staff_can_view_private_location(self):
        for user in (self.owner, self.staff):
            self.client.force_login(user)
            response = self.client.get(
                reverse("location_detail", args=[self.private.pk])
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.private.name)
            self.assertContains(response, "Private")
        self.assertTrue(can_edit_location_pin(self.owner, self.private))
        self.assertTrue(can_edit_location_pin(self.staff, self.private))
        self.assertFalse(can_edit_location_pin(self.other, self.private))

    def test_private_location_selector_is_owner_only_and_labeled(self):
        owner_form = JournalEntryForm(user=self.owner)
        owner_choices = dict(owner_form.fields["location"].choices)
        self.assertEqual(
            owner_choices[self.private.pk], f"Private — {self.private.name}"
        )
        other_ids = set(
            JournalEntryForm(user=self.other)
            .fields["location"]
            .queryset.values_list("pk", flat=True)
        )
        self.assertNotIn(self.private.pk, other_ids)

    def test_public_adventure_masks_private_location_for_unauthorized_viewer(self):
        adventure = Adventure.objects.create(
            owner=self.owner,
            title="Public Cabin Adventure",
            location=self.private,
            is_public=True,
        )
        response = self.client.get(adventure.get_absolute_url())
        self.assertContains(response, '<p class="private-location-badge">Private Location</p>')
        self.assertContains(
            response,
            "Contact paths are hidden because this Adventure uses a Private Location.",
        )
        self.assertNotContains(response, self.private.name)
        self.assertNotContains(response, self.private.street_address)
        self.assertNotContains(response, "47.654321")

    def test_non_owner_cannot_edit_private_location(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("edit_location", args=[self.private.pk]))
        self.assertIn(response.status_code, (403, 404))

    def test_owner_can_change_unshared_location_visibility(self):
        form = LocationForm(
            data=self.location_form_data(self.public, Location.Visibility.PRIVATE),
            instance=self.public,
            user=self.owner,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.public.refresh_from_db()
        self.assertEqual(self.public.visibility, Location.Visibility.PRIVATE)

    def test_shared_location_cannot_be_made_private_by_owner(self):
        Adventure.objects.create(
            owner=self.other,
            title="Other Member Adventure",
            location=self.public,
        )
        form = LocationForm(
            data=self.location_form_data(self.public, Location.Visibility.PRIVATE),
            instance=self.public,
            user=self.owner,
        )
        self.assertFalse(form.is_valid())
        self.assertIn(
            "This Location is used by Adventures belonging to other members.",
            form.errors["visibility"][0],
        )
        self.public.refresh_from_db()
        self.assertEqual(self.public.visibility, Location.Visibility.PUBLIC)

        staff_form = LocationForm(
            data=self.location_form_data(self.public, Location.Visibility.PRIVATE),
            instance=self.public,
            user=self.staff,
        )
        self.assertTrue(staff_form.is_valid(), staff_form.errors)
