from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from adventures.forms import LocationForm
from core.models import Location, LocationType, MemberProfile


class LocationTypeManagementTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="type-admin",
            password="test-password",
            is_staff=True,
        )
        self.member = get_user_model().objects.create_user(
            username="type-member",
            password="test-password",
        )
        MemberProfile.objects.create(
            user=self.member,
            callsign="W5TYPE",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )

    def test_staff_only_routes_and_menu(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("location_type_list")).status_code, 302)
        self.assertNotContains(self.client.get(reverse("home")), "Location Types")

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("location_type_list")).status_code, 200)
        self.assertContains(self.client.get(reverse("home")), "Location Types")

    def test_add_trim_duplicate_and_active_choices(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("location_type_add"),
            {"name": "  River   Access  ", "is_active": "on"},
        )
        self.assertRedirects(response, reverse("location_type_list"))
        added = LocationType.objects.get(name="River Access")
        self.assertEqual(added.key, "river-access")
        self.assertIn((added.key, added.name), list(LocationForm().fields["location_type"].choices))

        duplicate = self.client.post(
            reverse("location_type_add"),
            {"name": "river access", "is_active": "on"},
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertContains(duplicate, "already exists")
        self.assertEqual(LocationType.objects.filter(name__iexact="river access").count(), 1)

    def test_rename_preserves_association_and_inactive_edit_selection(self):
        location_type = LocationType.objects.create(name="Field Site", is_active=True)
        location = Location.objects.create(
            name="Associated Site",
            location_type=location_type.key,
            location_type_record=location_type,
        )
        stable_key = location_type.key
        self.client.force_login(self.staff)
        self.client.post(
            reverse("location_type_edit", args=[location_type.pk]),
            {"name": "Portable Field Site", "is_active": "on"},
        )
        location_type.refresh_from_db()
        location.refresh_from_db()
        self.assertEqual(location_type.key, stable_key)
        self.assertEqual(location.location_type_record_id, location_type.pk)
        self.assertEqual(location.get_location_type_display(), "Portable Field Site")

        self.client.post(reverse("location_type_toggle", args=[location_type.pk]))
        location_type.refresh_from_db()
        self.assertFalse(location_type.is_active)
        new_form = LocationForm()
        self.assertNotIn(stable_key, dict(new_form.fields["location_type"].choices))
        edit_form = LocationForm(instance=location)
        self.assertIn(stable_key, dict(edit_form.fields["location_type"].choices))

    def test_in_use_delete_blocked_and_unused_delete_allowed(self):
        used = LocationType.objects.create(name="Used Type")
        Location.objects.create(
            name="Uses Managed Type",
            location_type=used.key,
            location_type_record=used,
        )
        unused = LocationType.objects.create(name="Unused Type")
        self.client.force_login(self.staff)

        blocked = self.client.post(reverse("location_type_delete", args=[used.pk]), follow=True)
        self.assertContains(blocked, "cannot be deleted")
        self.assertTrue(LocationType.objects.filter(pk=used.pk).exists())
        self.assertTrue(Location.objects.filter(location_type_record=used).exists())

        allowed = self.client.post(reverse("location_type_delete", args=[unused.pk]))
        self.assertRedirects(allowed, reverse("location_type_list"))
        self.assertFalse(LocationType.objects.filter(pk=unused.pk).exists())

    def test_inactive_used_type_remains_in_public_filter(self):
        item = LocationType.objects.create(name="Legacy Site", is_active=False)
        Location.objects.create(
            name="Legacy Location",
            location_type=item.key,
            location_type_record=item,
        )
        response = self.client.get(reverse("locations"))
        self.assertContains(response, "Legacy Site (Inactive)")
        filtered = self.client.get(reverse("locations"), {"type": item.key})
        self.assertContains(filtered, "Legacy Location")

    def test_types_are_alphabetical_ignoring_capitalization_everywhere(self):
        LocationType.objects.create(name="zebra Site")
        LocationType.objects.create(name="Alpha Site")
        LocationType.objects.create(name="beta Site")

        names = list(LocationType.objects.values_list("name", flat=True))
        self.assertEqual(names, sorted(names, key=str.casefold))

        form_names = [label for _, label in LocationForm().fields["location_type"].choices]
        self.assertEqual(form_names, sorted(form_names, key=str.casefold))

        self.client.force_login(self.staff)
        response = self.client.get(reverse("location_type_list"))
        rendered_names = [item.name for item in response.context["location_types"]]
        self.assertEqual(rendered_names, sorted(rendered_names, key=str.casefold))

        public_response = self.client.get(reverse("locations"))
        public_names = [label for _, label in public_response.context["location_types"]]
        self.assertEqual(public_names, sorted(public_names, key=str.casefold))
