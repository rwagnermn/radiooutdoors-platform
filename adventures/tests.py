from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.models import (
    Adventure, JournalEntry, Location, LocationType, MemberProfile,
    OperatingLocation, Photo,
)


@override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.SafeProvider")
class AddAdventureWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="workflow-test",
            password="test-password",
        )
        MemberProfile.objects.create(
            user=self.user,
            callsign="W5FLOW",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.client.force_login(self.user)
        LocationType.objects.get_or_create(
            key=Location.LocationType.PARK,
            defaults={"name": "Park", "is_active": True},
        )
        self.location = Location.objects.create(name="Workflow Park", created_by=self.user)
        self.mapped_position = OperatingLocation.objects.create(
            location=self.location,
            created_by=self.user,
            name="Mapped Position",
            latitude="44.100000",
            longitude="-93.100000",
        )
        self.unmapped_position = OperatingLocation.objects.create(
            location=self.location,
            created_by=self.user,
            name="Unmapped Position",
        )

    def test_add_page_uses_location_only_workflow(self):
        response = self.client.get(reverse("add_adventure"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("operating_location", response.context["form"].fields)
        self.assertContains(response, "Create a New Location")
        self.assertContains(response, "Choosing or creating a Location")

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
            reverse("my_adventures"),
        )
        self.assertIsNone(adventure.location_id)
        self.assertIsNone(adventure.operating_location_id)
        self.assertTrue(
            Adventure.objects.filter(
                owner=self.user,
                pk=adventure.pk,
            ).exists()
        )

    def test_new_adventure_photos_use_existing_journal_photo_storage(self):
        output = BytesIO()
        Image.new("RGB", (32, 24), "orange").save(output, "PNG")
        response = self.client.post(
            reverse("add_adventure"),
            {
                "title": "Photo Adventure",
                "location": self.location.pk,
                "operating_location": self.mapped_position.pk,
                "photos": SimpleUploadedFile("pasted.png", output.getvalue(), "image/png"),
            },
        )
        adventure = Adventure.objects.get(title="Photo Adventure")
        self.assertRedirects(response, reverse("my_adventures"))
        self.assertEqual(Photo.objects.filter(journal_entry__adventure=adventure).count(), 1)

    def test_create_redirects_to_my_adventures_with_success_message_and_saved_row(self):
        response = self.client.post(
            reverse("add_adventure"),
            {
                "title": "Visible After Save",
                "location": self.location.pk,
                "operating_location": self.mapped_position.pk,
            },
            follow=True,
        )

        self.assertEqual(response.resolver_match.url_name, "my_adventures")
        self.assertContains(response, "Adventure saved successfully.")
        self.assertContains(response, "Visible After Save")
        self.assertContains(response, "My Adventures")

    def test_edit_redirects_to_my_adventures_and_updates_saved_row(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Before Edit Redirect",
            location=self.location,
            operating_location=self.mapped_position,
        )

        response = self.client.post(
            reverse("edit_adventure", kwargs={"slug": adventure.slug}),
            {
                "title": "After Edit Redirect",
                "location": self.location.pk,
                "operating_location": self.mapped_position.pk,
            },
            follow=True,
        )

        self.assertEqual(response.resolver_match.url_name, "my_adventures")
        self.assertContains(response, "Adventure saved successfully.")
        self.assertContains(response, "After Edit Redirect")
        adventure.refresh_from_db()
        self.assertEqual(adventure.title, "After Edit Redirect")

    def test_validation_failure_stays_on_form_and_creates_nothing(self):
        response = self.client.post(
            reverse("add_adventure"),
            {
                "title": "Preserve This Title",
                "operating_start_date": "2026-08-15",
                "operating_end_date": "2026-08-14",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.resolver_match.url_name, "add_adventure")
        self.assertContains(response, "Preserve This Title")
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(
            Adventure.objects.filter(title="Preserve This Title").exists()
        )

    def test_related_photo_failure_rolls_back_adventure_and_stays_on_form(self):
        output = BytesIO()
        Image.new("RGB", (20, 20), "orange").save(output, "PNG")
        with patch(
            "adventures.views._save_entry_photos",
            side_effect=OSError("simulated storage failure"),
        ):
            response = self.client.post(
                reverse("add_adventure"),
                {
                    "title": "Rolled Back Adventure",
                    "location": self.location.pk,
                    "operating_location": self.mapped_position.pk,
                    "photos": SimpleUploadedFile(
                        "rollback.png", output.getvalue(), "image/png"
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Adventure could not be saved")
        self.assertFalse(
            Adventure.objects.filter(title="Rolled Back Adventure").exists()
        )

    def test_form_prevents_duplicate_browser_submission(self):
        response = self.client.get(reverse("add_adventure"))
        self.assertContains(response, "data-prevent-double-submit")
        self.assertContains(response, "if (submitting)")
        self.assertContains(response, "event.preventDefault()")

    def test_map_coordinates_prepopulate_location_form(self):
        response = self.client.get(
            reverse("create_location"),
            {"latitude": "44.123456", "longitude": "-93.654321"},
        )
        form = response.context["location_form"]
        self.assertEqual(form.initial["latitude"], "44.123456")
        self.assertEqual(form.initial["longitude"], "-93.654321")

        self.assertIsNone(response.context["operating_form"])

    def test_first_operating_position_inherits_parent_location_coordinates(self):
        self.location.latitude = "44.234567"
        self.location.longitude = "-93.765432"
        self.location.save(update_fields=["latitude", "longitude"])

        response = self.client.get(
            reverse("add_operating_position", args=[self.location.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(response.context["form"].initial["latitude"]), "44.234567")
        self.assertEqual(str(response.context["form"].initial["longitude"]), "-93.765432")
        self.assertContains(response, "Reset to Location")
        self.assertContains(response, "Remove Pin")

    def test_location_without_coordinates_does_not_invent_position_coordinates(self):
        response = self.client.get(
            reverse("add_operating_position", args=[self.location.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("latitude", response.context["form"].initial)
        self.assertNotIn("longitude", response.context["form"].initial)

    def test_operating_position_requires_a_pin(self):
        response = self.client.post(
            reverse("add_operating_position", args=[self.location.pk]),
            {"name": "Missing Pin"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Place the Operating Position pin before continuing.",
        )
        self.assertFalse(
            OperatingLocation.objects.filter(
                location=self.location,
                name="Missing Pin",
            ).exists()
        )

    def test_editing_position_coordinates_does_not_change_parent_location(self):
        self.location.latitude = "44.300000"
        self.location.longitude = "-93.300000"
        self.location.save(update_fields=["latitude", "longitude"])

        response = self.client.post(
            reverse("edit_operating_position", args=[self.mapped_position.pk]),
            {
                "name": self.mapped_position.name,
                "latitude": "44.399999",
                "longitude": "-93.399999",
            },
        )

        self.assertRedirects(
            response,
            reverse("location_detail", args=[self.location.pk]),
        )
        self.mapped_position.refresh_from_db()
        self.location.refresh_from_db()
        self.assertEqual(str(self.mapped_position.latitude), "44.399999")
        self.assertEqual(str(self.mapped_position.longitude), "-93.399999")
        self.assertEqual(str(self.location.latitude), "44.300000")
        self.assertEqual(str(self.location.longitude), "-93.300000")

    def test_edit_location_renders_shared_editable_pin_controls(self):
        response = self.client.get(
            reverse("edit_location", args=[self.location.pk])
        )

        self.assertContains(response, "Remove Pin")
        self.assertContains(response, "editable-map-pin.js")
        self.assertNotContains(response, "Reset to Location")

    def test_airport_location_type_persists(self):
        airport = Location.objects.create(
            name="Workflow Airport",
            location_type=Location.LocationType.AIRPORT,
        )
        airport.refresh_from_db()
        self.assertEqual(airport.location_type, "airport")
        self.assertEqual(airport.get_location_type_display(), "Airport")

    def test_add_location_returns_with_new_location_selected(self):
        response = self.client.post(
            reverse("create_location"),
            {
                "return_to": "adventure",
                "draft_title": "Preserved Draft",
                "draft_public": "1",
                "location-name": "New Workflow Location",
                "location-visibility": Location.Visibility.PUBLIC,
                "location-location_type": Location.LocationType.PARK,
                "location-country": "USA",
                "location-latitude": "44.123456",
                "location-longitude": "-93.654321",
                "location-parking": "unknown",
                "location-restrooms": "unknown",
                "location-picnic_tables": "unknown",
                "location-shelter": "unknown",
                "location-shade": "unknown",
                "location-power": "unknown",
                "location-drinking_water": "unknown",
                "location-cell_coverage_bars": "0",
                "location-ambient_noise_level": "unknown",
                "operating-name": "First Position",
                "operating-latitude": "44.123456",
                "operating-longitude": "-93.654321",
            },
        )

        self.assertEqual(response.status_code, 302)
        location = Location.objects.get(name="New Workflow Location")
        expected = (
            f"{reverse('add_adventure')}?location={location.pk}"
            f"&title=Preserved+Draft&public=1"
        )
        self.assertRedirects(response, expected, fetch_redirect_response=False)

        returned = self.client.get(expected)
        self.assertEqual(
            returned.context["form"].initial["location"],
            str(location.pk),
        )

        saved = self.client.post(
            reverse("add_adventure"),
            {
                "title": "Adventure With Newly Created Place",
                "location": location.pk,
            },
            follow=True,
        )
        self.assertEqual(saved.resolver_match.url_name, "my_adventures")
        self.assertContains(saved, "Adventure With Newly Created Place")
        created = Adventure.objects.get(title="Adventure With Newly Created Place")
        self.assertIsNone(created.location_id)
        self.assertIsNone(created.operating_location_id)

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

    def test_journal_photo_preview_controls_do_not_create_records(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Preview Controls",
            location=self.location,
            operating_location=self.mapped_position,
        )
        response = self.client.get(
            reverse("add_journal_entry", kwargs={"slug": adventure.slug})
        )
        self.assertContains(response, "data-photo-preview")
        self.assertContains(response, "Load Photos")
        self.assertContains(response, "Change Photos")
        self.assertContains(response, "Clear Selection")
        self.assertContains(response, "photo-preview.js")
        self.assertContains(response, "multiple")
        self.assertEqual(Photo.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_duplicate_journal_photo_selection_saves_only_once(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Duplicate Photo Preview",
            location=self.location,
            operating_location=self.mapped_position,
        )
        image = Image.new("RGB", (80, 60), "orange")
        output = BytesIO()
        image.save(output, format="JPEG")
        image_bytes = output.getvalue()

        response = self.client.post(
            reverse("add_journal_entry", kwargs={"slug": adventure.slug}),
            {
                "entry_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "body": "Duplicate photo protection.",
                "photos": [
                    SimpleUploadedFile("same-one.jpg", image_bytes, "image/jpeg"),
                    SimpleUploadedFile("same-two.jpg", image_bytes, "image/jpeg"),
                ],
            },
        )
        self.assertEqual(response.status_code, 302)
        entry = adventure.journal_entries.get()
        self.assertEqual(entry.photos.count(), 1)

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
        self.assertNotContains(
            response,
            reverse("mark_adventure_done", kwargs={"slug": adventure.slug}),
        )
        self.assertNotContains(response, 'data-adventure-status-control')
        self.assertContains(response, 'class="ro-action-menu adventure-row-menu"')
        self.assertNotContains(response, ">Open</button>")
        self.assertContains(response, ">View</a>")
        self.assertContains(response, ">Edit</a>")
        self.assertContains(response, ">Delete</button>")
        self.assertNotContains(response, "Currently Operating")
        self.assertNotContains(response, "Mark Completed")

        edit_response = self.client.get(
            reverse("edit_adventure", kwargs={"slug": adventure.slug})
        )
        self.assertNotContains(edit_response, ">Open</button>")

        adventure.status = Adventure.Status.COMPLETED
        adventure.save()
        response = self.client.get(reverse("my_adventures"))
        self.assertNotContains(
            response,
            reverse(
                "mark_adventure_in_progress",
                kwargs={"slug": adventure.slug},
            ),
        )
        self.assertNotContains(response, ">Complete</button>")

        edit_response = self.client.get(
            reverse("edit_adventure", kwargs={"slug": adventure.slug})
        )
        self.assertNotContains(edit_response, ">Complete</button>")

        self.assertEqual(
            self.client.get(
                reverse("mark_adventure_done", kwargs={"slug": adventure.slug})
            ).status_code,
            405,
        )

    def test_ajax_status_toggle_persists_and_returns_next_toggle(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Ajax Status",
            location=self.location,
            operating_location=self.mapped_position,
        )
        response = self.client.post(
            reverse("mark_adventure_done", kwargs={"slug": adventure.slug}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["label"], "Complete")
        adventure.refresh_from_db()
        self.assertEqual(adventure.status, Adventure.Status.COMPLETED)

        response = self.client.post(
            response.json()["toggle_url"],
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.json()["label"], "Open")
        adventure.refresh_from_db()
        self.assertEqual(adventure.status, Adventure.Status.ACTIVE)

    def test_public_action_menu_permissions_and_status_filters(self):
        open_adventure = Adventure.objects.create(
            owner=self.user,
            title="Owned Open",
            location=self.location,
            operating_location=self.mapped_position,
            status=Adventure.Status.ACTIVE,
        )
        other = get_user_model().objects.create_user(
            username="other-viewer",
            password="test-password",
        )
        MemberProfile.objects.create(
            user=other,
            callsign="W5OTHER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        complete_adventure = Adventure.objects.create(
            owner=other,
            title="Other Complete",
            location=self.location,
            operating_location=self.mapped_position,
            status=Adventure.Status.COMPLETED,
        )

        owner_response = self.client.get(reverse("all_adventures"))
        self.assertContains(owner_response, ">View</a>", count=2)
        self.assertContains(owner_response, ">Edit</a>", count=1)
        self.assertContains(owner_response, ">Delete</button>", count=1)
        self.assertContains(owner_response, "<span>All Status</span>", html=True)
        self.assertContains(owner_response, "<span>Open</span>", html=True)
        self.assertContains(owner_response, "<span>Complete</span>", html=True)
        self.assertContains(owner_response, 'class="adventure-panel-list"')
        self.assertNotContains(owner_response, "<table")

        self.client.force_login(other)
        other_response = self.client.get(reverse("all_adventures"))
        self.assertContains(other_response, ">View</a>", count=2)
        self.assertContains(other_response, ">Edit</a>", count=1)
        self.assertContains(other_response, ">Delete</button>", count=1)

        self.client.logout()
        public_response = self.client.get(reverse("all_adventures"))
        self.assertContains(public_response, ">View</a>", count=2)
        self.assertNotContains(public_response, ">Edit</a>")
        self.assertNotContains(public_response, ">Delete</button>")
        self.assertNotContains(public_response, "data-adventure-status-control")

        open_response = self.client.get(reverse("all_adventures"), {"activity": "open"})
        self.assertContains(open_response, open_adventure.title)
        self.assertNotContains(open_response, complete_adventure.title)
        complete_response = self.client.get(reverse("all_adventures"), {"activity": "complete"})
        self.assertContains(complete_response, complete_adventure.title)
        self.assertNotContains(complete_response, open_adventure.title)

    def test_staff_can_manage_and_unrelated_member_cannot(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Permission Status",
            location=self.location,
            operating_location=self.mapped_position,
        )
        unrelated = get_user_model().objects.create_user(
            username="unrelated-member",
            password="test-password",
        )
        MemberProfile.objects.create(
            user=unrelated,
            callsign="W5NOPE",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.client.force_login(unrelated)
        denied = self.client.post(
            reverse("mark_adventure_done", kwargs={"slug": adventure.slug})
        )
        self.assertEqual(denied.status_code, 403)

        staff = get_user_model().objects.create_user(
            username="adventure-admin",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(staff)
        allowed = self.client.post(
            reverse("mark_adventure_done", kwargs={"slug": adventure.slug}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["label"], "Complete")
        menu = self.client.get(reverse("all_adventures"))
        self.assertContains(menu, ">Edit</a>")
        self.assertContains(menu, ">Delete</button>")

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
            moderation_status=Photo.ModerationStatus.APPROVED,
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

    def test_journal_browsing_lists_use_compact_shared_rows(self):
        adventure = Adventure.objects.create(
            owner=self.user,
            title="Compact Journal List",
            location=self.location,
            operating_location=self.mapped_position,
            lessons_learned="Keep Lessons Learned separate.",
        )
        long_body = "A long Journal story that belongs on the detail page. " * 12
        entries = [
            JournalEntry.objects.create(
                adventure=adventure,
                title=f"Journal title {index}",
                body=long_body,
            )
            for index in range(11)
        ]
        long_location = Location.objects.create(
            name="North Shore State Wildlife Management Area Long Prairie Access",
            created_by=self.user,
        )
        entries[0].title = (
            "Late Summer Portable Radio Journal from the North Shore Overlook"
        )
        entries[0].location = long_location
        entries[0].save(update_fields=["title", "location"])
        entries[1].location = self.location
        entries[1].save(update_fields=["location"])
        Photo.objects.create(
            journal_entry=entries[0],
            image="adventure_photos/compact-list.jpg",
            moderation_status=Photo.ModerationStatus.APPROVED,
        )

        detail_response = self.client.get(adventure.get_absolute_url())
        self.assertContains(
            detail_response,
            'class="adventure-dashboard-scroll adventure-dashboard-journal-scroll"',
        )
        self.assertContains(detail_response, 'aria-label="Adventure Journals"')
        self.assertContains(detail_response, 'tabindex="0"')
        self.assertContains(
            detail_response,
            'class="adventure-journal-card-list"',
        )
        self.assertContains(
            detail_response,
            'class="adventure-journal-row-title"',
            count=11,
        )
        self.assertContains(detail_response, "Journal title 10")
        self.assertNotContains(detail_response, long_body)
        self.assertContains(detail_response, "Keep Lessons Learned separate.")
        self.assertNotContains(detail_response, 'class="adventure-story-stats"')
        self.assertContains(detail_response, "11 total")
        self.assertContains(detail_response, "Show All Journals")
        self.assertContains(detail_response, reverse("adventure_journals", args=[adventure.slug]))
        self.assertContains(detail_response, "Photos are stored in Journals")
        self.assertNotContains(detail_response, "embedded-detail-map-layout adventure-journal-map-layout")
        self.assertContains(detail_response, "1 photo")
        self.assertContains(detail_response, 'class="adventure-photo-strip"')
        self.assertContains(detail_response, "<dt>Photos</dt><dd>1</dd>", html=True)

        all_journals = self.client.get(reverse("adventure_journals", args=[adventure.slug]))
        self.assertContains(all_journals, "Journal title", count=10)
        self.assertContains(all_journals, entries[0].title)
        self.assertContains(all_journals, long_location.name)
        self.assertContains(all_journals, self.location.name)
        self.assertContains(
            all_journals,
            reverse("journal_entry_detail", kwargs={"entry_id": entries[0].pk}),
        )
        rendered_journals = all_journals.content.decode()
        location_header = rendered_journals.index(">Location</th>")
        name_header = rendered_journals.index(">Journal Name</th>")
        date_header = rendered_journals.index(">Date</th>")
        self.assertLess(location_header, name_header)
        self.assertLess(name_header, date_header)
        self.assertIn('class="journal-list-location"', rendered_journals)
        self.assertIn('class="journal-list-entry"', rendered_journals)
        self.assertIn('class="journal-list-date"', rendered_journals)

        edit_response = self.client.get(
            reverse("edit_adventure", kwargs={"slug": adventure.slug})
        )
        self.assertContains(
            edit_response,
            'class="compact-contact-table ro-data-table journal-list-table"',
        )
        self.assertContains(edit_response, "View Journal", count=11)
        self.assertContains(
            edit_response,
            'class="primary-feature-button"',
            count=11,
        )
        self.assertContains(edit_response, ">Edit</a>", count=11)

        edit_journal_response = self.client.get(
            reverse("edit_journal_entry", kwargs={"entry_id": entries[0].pk})
        )
        self.assertContains(
            edit_journal_response,
            'class="primary-feature-button">View Journal</a>',
        )

        journal_response = self.client.get(
            reverse("journal_entry_detail", kwargs={"entry_id": entries[0].pk})
        )
        self.assertContains(journal_response, long_body)
        self.assertNotContains(journal_response, "journal-list-table")

    def location_image(self, name="location.png", color="green"):
        image = Image.new("RGB", (2200, 1100), color)
        output = BytesIO()
        image.save(output, format="PNG")
        return SimpleUploadedFile(name, output.getvalue(), "image/png")

    def test_location_name_help_uses_accessible_dialog(self):
        response = self.client.get(reverse("create_location"))

        self.assertContains(response, 'aria-label="Location help"')
        self.assertContains(response, 'aria-controls="location-editor-help-dialog"')
        self.assertContains(response, 'role="dialog"')
        self.assertContains(response, 'aria-modal="true"')
        self.assertContains(response, "Choosing a Location")
        self.assertContains(response, "Benson Airport")
        self.assertContains(response, "A street address is optional, but a map pin is required.")
        self.assertContains(response, "Private Locations and their exact map pins")
        self.assertNotContains(
            response,
            '<p class="section-help">Give the Location a natural name',
        )

    def test_location_photo_create_preview_replace_remove_and_display(self):
        with patch(
            "core.location_default_images.default_storage.exists",
            return_value=False,
        ):
            no_photo_detail = self.client.get(
                reverse("location_detail", kwargs={"location_id": self.location.pk})
            )
        self.assertContains(no_photo_detail, "location-primary-photo-placeholder")

        create_page = self.client.get(reverse("create_location"))
        self.assertContains(create_page, "data-photo-preview")
        self.assertContains(create_page, "Load Photo")
        self.assertContains(create_page, "Nothing is saved until Save Location")
        self.assertContains(create_page, 'enctype="multipart/form-data"')

        response = self.client.post(
            reverse("create_location"),
            {
                "location-name": "Photo Workflow Location",
                "location-visibility": Location.Visibility.PUBLIC,
                "location-location_type": Location.LocationType.PARK,
                "location-country": "USA",
                "location-photo": self.location_image(),
                "location-latitude": "44.123456",
                "location-longitude": "-93.654321",
                "location-parking": "unknown",
                "location-restrooms": "unknown",
                "location-picnic_tables": "unknown",
                "location-shelter": "unknown",
                "location-shade": "unknown",
                "location-power": "unknown",
                "location-drinking_water": "unknown",
                "location-cell_coverage_bars": "0",
                "location-ambient_noise_level": "unknown",
            },
        )
        self.assertEqual(response.status_code, 302)
        location = Location.objects.get(name="Photo Workflow Location")
        self.assertRedirects(
            response,
            reverse("location_detail", kwargs={"location_id": location.pk}),
        )
        self.assertTrue(location.photo)
        original_name = location.photo.name
        with Image.open(location.photo.path) as stored:
            self.assertLessEqual(max(stored.size), 1600)

        list_response = self.client.get(reverse("locations"))
        self.assertContains(list_response, location.photo.url)
        detail_response = self.client.get(
            reverse("location_detail", kwargs={"location_id": location.pk})
        )
        self.assertContains(detail_response, location.photo.url)
        self.assertRegex(
            detail_response.content.decode(),
            r'class="[^"]*\blocation-primary-photo\b[^"]*"',
        )

        self.client.post(
            reverse("edit_location", kwargs={"location_id": location.pk}),
            {
                "location-name": location.name,
                "location-visibility": location.visibility,
                "location-location_type": location.location_type,
                "location-country": location.country,
                "location-photo": self.location_image("replacement.png", "blue"),
                "location-parking": "unknown",
                "location-restrooms": "unknown",
                "location-picnic_tables": "unknown",
                "location-shelter": "unknown",
                "location-shade": "unknown",
                "location-power": "unknown",
                "location-drinking_water": "unknown",
                "location-cell_coverage_bars": "0",
                "location-ambient_noise_level": "unknown",
            },
        )
        location.refresh_from_db()
        self.assertTrue(location.photo)
        self.assertNotEqual(location.photo.name, original_name)

        self.client.post(
            reverse("edit_location", kwargs={"location_id": location.pk}),
            {
                "location-name": location.name,
                "location-visibility": location.visibility,
                "location-location_type": location.location_type,
                "location-country": location.country,
                "location-remove_location_photo": "on",
                "location-parking": "unknown",
                "location-restrooms": "unknown",
                "location-picnic_tables": "unknown",
                "location-shelter": "unknown",
                "location-shade": "unknown",
                "location-power": "unknown",
                "location-drinking_water": "unknown",
                "location-cell_coverage_bars": "0",
                "location-ambient_noise_level": "unknown",
            },
        )
        location.refresh_from_db()
        self.assertFalse(location.photo)
        with patch(
            "core.location_default_images.default_storage.exists",
            return_value=False,
        ):
            removed_detail = self.client.get(
                reverse("location_detail", kwargs={"location_id": location.pk})
            )
        self.assertContains(removed_detail, "location-primary-photo-placeholder")
