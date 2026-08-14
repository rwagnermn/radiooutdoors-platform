from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, JournalContact, JournalEntry, Location, MemberProfile, Photo


class JournalDashboardTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("journal-dashboard-owner", password="test")
        MemberProfile.objects.create(
            user=self.owner,
            callsign="W0JRN",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.visitor = users.objects.create_user("journal-dashboard-visitor", password="test")
        self.staff = users.objects.create_user("journal-dashboard-staff", password="test", is_staff=True)
        self.location = Location.objects.create(
            name="Lake Eleven Woods",
            created_by=self.owner,
            latitude="47.123456",
            longitude="-93.654321",
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Lake Eleven Woods Adventure",
            operating_callsign="W0JRN",
            is_public=True,
        )
        self.entry = JournalEntry.objects.create(
            adventure=self.adventure,
            location=self.location,
            latitude=self.location.latitude,
            longitude=self.location.longitude,
            title="Morning Shoreline Journal",
            body=("First paragraph from the field.\n\nSecond paragraph with more detail. " * 20),
            entry_at=datetime(2026, 8, 13, 20, 45, tzinfo=dt_timezone.utc),
            operating_callsign="W0JRN",
            status=JournalEntry.Status.COMPLETED,
            is_public=True,
        )
        self.url = reverse("journal_entry_detail", args=[self.entry.pk])

    def test_header_uses_real_values_and_authorized_adventure_link_without_story(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Morning Shoreline Journal")
        self.assertContains(response, "Complete / Public")
        self.assertContains(response, "Lake Eleven Woods")
        self.assertContains(response, "W0JRN")
        self.assertContains(response, "August 13, 2026")
        self.assertNotContains(response, "3:45 PM")
        self.assertNotContains(response, "Journal Stories")
        self.assertContains(response, "<strong>Adventure:</strong>", html=True)
        self.assertContains(
            response,
            f'<a href="{self.adventure.get_absolute_url()}">{self.adventure.title}</a>',
            html=True,
        )
        content = response.content.decode()
        header = content[content.index('class="journal-summary-copy"'):content.index('class="journal-primary-photo"')]
        self.assertNotIn("First paragraph from the field.", header)
        self.assertNotContains(response, "data-journal-summary-clamp")
        self.assertNotContains(response, "data-journal-summary-toggle")

    def test_notes_are_one_continuous_existing_body_without_categories(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Journal Notes")
        self.assertContains(response, "First paragraph from the field.")
        self.assertContains(response, "Second paragraph with more detail.")
        self.assertNotContains(response, "Setup Observations")
        self.assertNotContains(response, "Radio/Antenna Notes")
        self.assertNotContains(response, "Conditions")

    def test_contacts_have_exact_dashboard_columns_and_permission_actions(self):
        JournalContact.objects.create(
            journal_entry=self.entry,
            qso_date=self.entry.entry_at.date(),
            callsign="K1ABC",
            band="20m",
            mode="SSB",
            state="Illinois",
            country="USA",
            fingerprint="journal-dashboard-contact",
        )
        visitor = self.client.get(self.url)
        for heading in ("Date", "Callsign", "Band", "Mode", "Location"):
            self.assertContains(visitor, f"<th>{heading}</th>", html=True)
        self.assertNotContains(visitor, "<th>State</th>", html=True)
        self.assertNotContains(visitor, "<th>Country</th>", html=True)
        self.assertContains(visitor, "Illinois, USA")
        self.assertNotContains(visitor, "Add Contact")
        self.assertNotContains(visitor, "Import Contacts")

        self.client.force_login(self.owner)
        owner = self.client.get(self.url)
        self.assertContains(owner, "Add Contact")
        self.assertContains(owner, "Import Contacts")

    def test_map_uses_authorized_coordinates_and_protects_private_location(self):
        public = self.client.get(self.url)
        self.assertContains(public, '"latitude": 47.123456')
        self.assertContains(public, '"longitude": -93.654321')
        self.assertContains(public, "zoom:14")
        self.assertContains(public, "fullscreenControl:true")

        self.location.visibility = Location.Visibility.PRIVATE
        self.location.save(update_fields=["visibility"])
        private = self.client.get(self.url)
        self.assertNotContains(private, "47.123456")
        self.assertNotContains(private, "-93.654321")
        self.assertContains(private, "Private Location")

    def test_photo_filtering_blur_admin_display_carousel_and_enlargement(self):
        approved = Photo.objects.create(
            journal_entry=self.entry,
            image="adventure_photos/journal-approved.jpg",
            moderation_status=Photo.ModerationStatus.APPROVED,
        )
        pending = Photo.objects.create(
            journal_entry=self.entry,
            image="adventure_photos/journal-pending.jpg",
            moderation_status=Photo.ModerationStatus.PENDING,
        )

        visitor = self.client.get(self.url)
        self.assertEqual(visitor.context["journal_photo_count"], 1)
        self.assertContains(visitor, approved.public_image_url)
        self.assertNotContains(visitor, pending.public_image_url)

        self.client.force_login(self.owner)
        owner = self.client.get(self.url)
        self.assertEqual(owner.context["journal_photo_count"], 2)
        self.assertContains(owner, "journal-photo-unapproved")
        self.assertContains(owner, "journal-photo-blurred")
        self.assertContains(owner, "data-journal-carousel-prev")
        self.assertContains(owner, "data-journal-carousel-next")
        self.assertContains(owner, "journal-photo-viewer-trigger")
        self.assertContains(owner, "at original size")

        self.client.force_login(self.staff)
        staff = self.client.get(self.url)
        self.assertEqual(staff.context["journal_photo_count"], 2)
        self.assertNotContains(staff, "journal-photo-unapproved")
        self.assertContains(staff, pending.public_image_url)

    def test_photo_roles_can_share_one_photo_and_previous_photos_remain(self):
        first = Photo.objects.create(
            journal_entry=self.entry,
            image="adventure_photos/journal-first.jpg",
            moderation_status=Photo.ModerationStatus.APPROVED,
        )
        selected = Photo.objects.create(
            journal_entry=self.entry,
            image="adventure_photos/journal-selected.jpg",
            moderation_status=Photo.ModerationStatus.APPROVED,
        )
        self.entry.primary_photo = first
        self.entry.save(update_fields=["primary_photo"])
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("make_journal_photo", args=[self.entry.pk, selected.pk])
        )
        self.assertRedirects(response, self.url)
        response = self.client.post(
            reverse("make_adventure_cover", args=[self.adventure.slug, selected.pk])
        )
        self.assertRedirects(response, self.adventure.get_absolute_url())
        self.entry.refresh_from_db()
        self.adventure.refresh_from_db()
        self.assertEqual(self.entry.primary_photo_id, selected.pk)
        self.assertEqual(self.adventure.cover_photo_id, selected.pk)
        self.assertTrue(Photo.objects.filter(pk=first.pk).exists())
        self.assertTrue(Photo.objects.filter(pk=selected.pk).exists())

        detail = self.client.get(self.url)
        self.assertContains(detail, "Journal Photo")
        self.assertContains(detail, "Adventure Photo")

    def test_photo_role_actions_require_permission_and_approved_photo(self):
        approved = Photo.objects.create(
            journal_entry=self.entry,
            image="adventure_photos/approved-role.jpg",
            moderation_status=Photo.ModerationStatus.APPROVED,
        )
        pending = Photo.objects.create(
            journal_entry=self.entry,
            image="adventure_photos/pending-role.jpg",
            moderation_status=Photo.ModerationStatus.PENDING,
        )
        visitor = self.client.get(self.url)
        self.assertNotContains(visitor, "Make Journal Photo")
        self.assertNotContains(visitor, "Make Adventure Photo")

        self.client.force_login(self.visitor)
        self.assertNotEqual(
            self.client.post(reverse("make_journal_photo", args=[self.entry.pk, approved.pk])).status_code,
            200,
        )
        self.entry.refresh_from_db()
        self.assertIsNone(self.entry.primary_photo_id)

        self.client.force_login(self.owner)
        denied = self.client.post(
            reverse("make_journal_photo", args=[self.entry.pk, pending.pk])
        )
        self.assertEqual(denied.status_code, 403)
        denied = self.client.post(
            reverse("make_adventure_cover", args=[self.adventure.slug, pending.pk])
        )
        self.assertEqual(denied.status_code, 403)

    def test_view_all_photos_gallery_preserves_context_and_authorization(self):
        approved = Photo.objects.create(
            journal_entry=self.entry,
            image="adventure_photos/gallery-approved.jpg",
            moderation_status=Photo.ModerationStatus.APPROVED,
        )
        pending = Photo.objects.create(
            journal_entry=self.entry,
            image="adventure_photos/gallery-pending.jpg",
            moderation_status=Photo.ModerationStatus.PENDING,
        )
        gallery_url = reverse("journal_photo_gallery", args=[self.entry.pk])
        detail = self.client.get(self.url)
        self.assertContains(detail, f'href="{gallery_url}"')

        visitor = self.client.get(gallery_url)
        self.assertContains(visitor, approved.public_image_url)
        self.assertNotContains(visitor, pending.public_image_url)
        self.assertContains(visitor, f'href="{self.url}"')
        self.assertContains(visitor, "journal-photo-viewer-trigger")

        self.client.force_login(self.owner)
        owner = self.client.get(gallery_url)
        self.assertContains(owner, approved.public_image_url)
        self.assertContains(owner, pending.public_thumbnail_url)
        self.assertContains(owner, "journal-photo-blurred")

    def test_photo_gallery_has_authorized_empty_state(self):
        response = self.client.get(reverse("journal_photo_gallery", args=[self.entry.pk]))
        self.assertContains(response, "No photos are available for this Journal.")

    def test_photo_controls_fit_tiles_and_carousel_remains_accessible(self):
        from django.conf import settings

        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn("flex:0 0 150px", css)
        self.assertIn("height:164px", css)
        self.assertIn("object-fit:contain", css)
        self.assertIn("white-space:normal", css)
        self.assertIn("overflow-y:hidden", css)
        template = (settings.BASE_DIR / "templates" / "adventures" / "journal_entry_detail.html").read_text(encoding="utf-8")
        self.assertIn("data-journal-carousel-prev", template)
        self.assertIn("data-journal-carousel-next", template)
        self.assertIn("journal-photo-viewer-trigger", template)

    def test_layout_uses_journal_background_and_nonoverlapping_responsive_grid(self):
        from django.conf import settings

        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn('url("../images/journal-detail-pencil-background.png")', css)
        self.assertIn("body.journal-dashboard-page .content.journal-dashboard", css)
        self.assertIn("max-width: 1240px", css)
        self.assertIn("scrollbar-width:none", css)
        self.assertIn(".journal-summary-panel,.journal-dashboard-grid { grid-template-columns:1fr; }", css)
