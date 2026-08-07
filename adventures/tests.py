from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Adventure, JournalEntry, Location, OperatingLocation, Photo


class AddAdventureWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="workflow-test",
            password="test-password",
        )
        self.client.force_login(self.user)
        self.location = Location.objects.create(name="Workflow Park")
        self.mapped_position = OperatingLocation.objects.create(
            location=self.location,
            name="Mapped Position",
            latitude="44.100000",
            longitude="-93.100000",
        )
        self.unmapped_position = OperatingLocation.objects.create(
            location=self.location,
            name="Unmapped Position",
        )

    def test_add_page_supplies_all_positions_and_only_maps_coordinates(self):
        response = self.client.get(reverse("add_adventure"))

        self.assertEqual(response.status_code, 200)
        positions = response.context["operating_positions"]
        self.assertEqual(
            {position["id"] for position in positions},
            {self.mapped_position.pk, self.unmapped_position.pk},
        )
        mapped = [
            position for position in positions
            if position["latitude"] is not None
            and position["longitude"] is not None
        ]
        self.assertEqual(
            [position["id"] for position in mapped],
            [self.mapped_position.pk],
        )
        self.assertContains(response, "+ Add New Location")
        self.assertContains(response, "📍 Drop a New Pin...")
        self.assertContains(response, "Required Field", count=3)

    def test_dropdown_selection_creates_adventure_with_matching_position(self):
        response = self.client.post(
            reverse("add_adventure"),
            {
                "title": "Dropdown Adventure",
                "location": self.location.pk,
                "operating_location": self.unmapped_position.pk,
                "is_public": "on",
            },
        )

        adventure = Adventure.objects.get(title="Dropdown Adventure")
        self.assertRedirects(
            response,
            reverse("edit_adventure", kwargs={"slug": adventure.slug}),
        )
        self.assertEqual(adventure.location_id, self.location.pk)
        self.assertEqual(
            adventure.operating_location_id,
            self.unmapped_position.pk,
        )
        self.assertTrue(
            Adventure.objects.filter(
                owner=self.user,
                pk=adventure.pk,
            ).exists()
        )

    def test_add_location_returns_with_new_location_and_position_selected(self):
        response = self.client.post(
            reverse("create_location"),
            {
                "return_to": "adventure",
                "draft_title": "Preserved Draft",
                "draft_public": "1",
                "location-name": "New Workflow Location",
                "location-location_type": Location.LocationType.PARK,
                "location-country": "USA",
                "operating-name": "First Position",
            },
        )

        location = Location.objects.get(name="New Workflow Location")
        position = location.operating_locations.get(name="First Position")
        expected = (
            f"{reverse('add_adventure')}?location={location.pk}"
            f"&operating={position.pk}&title=Preserved+Draft&public=1"
        )
        self.assertRedirects(response, expected, fetch_redirect_response=False)

        returned = self.client.get(expected)
        self.assertEqual(
            returned.context["form"].initial["location"],
            str(location.pk),
        )
        self.assertEqual(
            returned.context["form"].initial["operating_location"],
            str(position.pk),
        )

    def test_inline_position_creation_saves_under_selected_location(self):
        empty_location = Location.objects.create(name="Empty Workflow Park")

        response = self.client.post(
            reverse(
                "create_operating_position_inline",
                kwargs={"location_id": empty_location.pk},
            ),
            {
                "name": "Map Click Position",
                "description": "Quiet spot near the trail.",
                "latitude": "45.123456",
                "longitude": "-93.654321",
            },
        )

        self.assertEqual(response.status_code, 201)
        position = empty_location.operating_locations.get(
            name="Map Click Position"
        )
        self.assertEqual(response.json()["id"], position.pk)
        self.assertEqual(position.location_id, empty_location.pk)
        self.assertEqual(position.description, "Quiet spot near the trail.")
        self.assertEqual(str(position.latitude), "45.123456")
        self.assertEqual(str(position.longitude), "-93.654321")

    def test_new_adventure_defaults_public_when_visibility_is_omitted(self):
        response = self.client.post(
            reverse("add_adventure"),
            {
                "title": "Default Public Adventure",
                "location": self.location.pk,
                "operating_location": self.mapped_position.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Adventure.objects.get(title="Default Public Adventure").is_public
        )

    def test_new_adventure_can_be_intentionally_private(self):
        self.client.post(
            reverse("add_adventure"),
            {
                "title": "Private Adventure",
                "location": self.location.pk,
                "operating_location": self.mapped_position.pk,
                "adventure_visibility_present": "1",
            },
        )

        self.assertFalse(
            Adventure.objects.get(title="Private Adventure").is_public
        )

    def test_new_journal_defaults_public_when_visibility_is_omitted(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Journal Parent",
            location=self.location,
            operating_location=self.mapped_position,
        )

        response = self.client.post(
            reverse("add_journal_entry", kwargs={"slug": adventure.slug}),
            {
                "entry_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "body": "Default public journal.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(adventure.journal_entries.get().is_public)

    def test_new_journal_can_be_intentionally_private(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Private Journal Parent",
            location=self.location,
            operating_location=self.mapped_position,
        )

        self.client.post(
            reverse("add_journal_entry", kwargs={"slug": adventure.slug}),
            {
                "entry_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "body": "Private journal.",
                "journal_visibility_present": "1",
            },
        )

        self.assertFalse(adventure.journal_entries.get().is_public)

    def test_status_endpoints_toggle_and_edit_save_preserves_status(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Status Workflow",
            location=self.location,
            operating_location=self.mapped_position,
        )

        response = self.client.post(
            reverse("mark_adventure_done", kwargs={"slug": adventure.slug}),
            {"next": reverse("my_adventures")},
        )
        self.assertRedirects(response, reverse("my_adventures"))
        adventure.refresh_from_db()
        self.assertEqual(adventure.status, Adventure.Status.COMPLETED)

        self.client.post(
            reverse("edit_adventure", kwargs={"slug": adventure.slug}),
            {
                "title": "Status Workflow Edited",
                "location": self.location.pk,
                "operating_location": self.mapped_position.pk,
                "is_public": "on",
            },
        )
        adventure.refresh_from_db()
        self.assertEqual(adventure.status, Adventure.Status.COMPLETED)

        response = self.client.post(
            reverse(
                "mark_adventure_in_progress",
                kwargs={"slug": adventure.slug},
            ),
            {"next": reverse("edit_adventure", kwargs={"slug": adventure.slug})},
        )
        self.assertRedirects(
            response,
            reverse("edit_adventure", kwargs={"slug": adventure.slug}),
        )
        adventure.refresh_from_db()
        self.assertEqual(adventure.status, Adventure.Status.ACTIVE)

    def test_status_controls_render_for_my_adventures_and_edit(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Status Control",
            location=self.location,
            operating_location=self.mapped_position,
        )

        response = self.client.get(reverse("my_adventures"))
        self.assertContains(
            response,
            reverse("mark_adventure_done", kwargs={"slug": adventure.slug}),
        )
        self.assertContains(response, '<span class="adventure-status')
        self.assertNotContains(response, '<button type="submit" class="adventure-status')
        self.assertContains(response, 'class="journal-menu-button"')
        self.assertContains(response, 'name="next" value="/adventures/"')
        self.assertContains(response, "Currently Operating")
        self.assertContains(response, "Mark Completed")

        edit_response = self.client.get(
            reverse("edit_adventure", kwargs={"slug": adventure.slug})
        )
        self.assertContains(edit_response, "Currently Operating")
        self.assertContains(edit_response, "Mark Completed")

        adventure.status = Adventure.Status.COMPLETED
        adventure.save()
        response = self.client.get(reverse("my_adventures"))
        self.assertContains(
            response,
            reverse(
                "mark_adventure_in_progress",
                kwargs={"slug": adventure.slug},
            ),
        )
        self.assertContains(response, "Adventure Complete")
        self.assertContains(response, "Mark In Progress")

        edit_response = self.client.get(
            reverse("edit_adventure", kwargs={"slug": adventure.slug})
        )
        self.assertContains(edit_response, "Adventure Complete")
        self.assertContains(edit_response, "Mark In Progress")

        self.assertEqual(
            self.client.get(
                reverse("mark_adventure_done", kwargs={"slug": adventure.slug})
            ).status_code,
            405,
        )

    def test_journal_photos_render_original_size_viewer_controls(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Photo Viewer Adventure",
            location=self.location,
            operating_location=self.mapped_position,
        )
        entry = JournalEntry.objects.create(
            adventure=adventure,
            body="Photo viewer journal.",
        )
        Photo.objects.create(
            journal_entry=entry,
            image="adventure_photos/test-original.jpg",
            caption="Summit station",
        )

        response = self.client.get(
            reverse("journal_entry_detail", kwargs={"entry_id": entry.pk})
        )

        self.assertContains(response, 'class="journal-photo-viewer-trigger"')
        self.assertContains(
            response,
            'data-full-src="/media/adventure_photos/test-original.jpg',
        )
        self.assertContains(response, "View Summit station at original size")
        self.assertContains(response, "journal-photo-viewer.js")
