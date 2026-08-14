from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    Adventure,
    JournalContact,
    JournalEntry,
    Location,
    MemberProfile,
    Photo,
    PotaActivationImport,
    PotaImportBatch,
)


class StaffRecordIdVisibilityTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.staff = users.objects.create_superuser(
            username="record-id-staff",
            password="StrongPass!942",
            email="staff@example.com",
        )
        self.member = users.objects.create_user(
            username="W5IDS",
            password="StrongPass!942",
        )
        self.profile = MemberProfile.objects.create(
            user=self.member,
            callsign="W5IDS",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.ADMIN,
        )
        self.location = Location.objects.create(
            name="Record ID Location",
            visibility=Location.Visibility.PUBLIC,
        )
        self.adventure = Adventure.objects.create(
            owner=self.member,
            location=self.location,
            title="Record ID Adventure",
            is_public=True,
        )
        self.journal = JournalEntry.objects.create(
            adventure=self.adventure,
            title="Record ID Journal",
            body="Visible journal",
            is_public=True,
        )
        self.contact = JournalContact.objects.create(
            journal_entry=self.journal,
            qso_date=date(2026, 8, 11),
            callsign="W1ID",
            fingerprint="record-id-contact",
        )
        self.photo = Photo.objects.create(
            journal_entry=self.journal,
            image="adventure_photos/record-id.jpg",
        )
        self.photo.refresh_from_db()
        batch = PotaImportBatch.objects.create(owner=self.member)
        self.activation = PotaActivationImport.objects.create(
            adventure=self.adventure,
            batch=batch,
            activation_date=date(2026, 8, 11),
            callsign="W5IDS",
            park_reference="US-0099",
            park_name="Record Park",
            fingerprint="record-id-activation",
            location_resolution="existing",
        )

    def test_staff_sees_member_and_user_ids_in_management(self):
        self.client.force_login(self.staff)

        management = self.client.get(reverse("member_admin_list"))
        deletion = self.client.get(reverse("member_delete", args=[self.profile.pk]))

        self.assertContains(management, f">{self.profile.pk}</strong>")
        self.assertContains(management, f"User {self.member.pk}")
        self.assertContains(deletion, f"Member ID {self.profile.pk}")
        self.assertContains(deletion, f"User ID {self.member.pk}")

    def test_staff_sees_adventure_journal_and_contact_ids(self):
        self.client.force_login(self.staff)

        adventure = self.client.get(self.adventure.get_absolute_url())
        journal = self.client.get(
            reverse("journal_entry_detail", args=[self.journal.pk])
        )
        contacts = self.client.get(
            reverse("adventure_contacts", args=[self.adventure.slug])
        )

        self.assertContains(adventure, f"Adventure ID {self.adventure.pk}")
        self.assertContains(journal, f"Journal ID {self.journal.pk}")
        self.assertContains(contacts, f">{self.contact.pk}</td>")

    def test_staff_sees_location_ids_on_list_and_detail(self):
        self.client.force_login(self.staff)

        listing = self.client.get(reverse("locations"))
        detail = self.client.get(reverse("location_detail", args=[self.location.pk]))

        self.assertContains(listing, f">{self.location.pk}</td>")
        self.assertContains(detail, f"Location ID {self.location.pk}")

    def test_photo_moderation_keeps_reference_and_adds_database_id(self):
        self.client.force_login(self.staff)

        queue = self.client.get(reverse("photo_moderation_queue"))
        detail = self.client.get(
            reverse("photo_moderation_detail", args=["photo", self.photo.pk])
        )

        self.assertContains(queue, self.photo.reference_number)
        self.assertContains(queue, f">{self.photo.pk}</td>")
        self.assertContains(detail, f"Database ID {self.photo.pk}")
        self.assertContains(detail, self.photo.reference_number)

    def test_public_and_normal_member_views_do_not_expose_staff_id_labels(self):
        urls = (
            reverse("all_adventures"),
            self.adventure.get_absolute_url(),
            reverse("locations"),
            reverse("location_detail", args=[self.location.pk]),
            reverse("journal_entry_detail", args=[self.journal.pk]),
            reverse("adventure_contacts", args=[self.adventure.slug]),
        )

        for authenticated in (False, True):
            if authenticated:
                self.client.force_login(self.member)
            else:
                self.client.logout()
            for url in urls:
                with self.subTest(authenticated=authenticated, url=url):
                    response = self.client.get(url)
                    self.assertNotContains(response, "staff-record-id")
                    self.assertNotContains(response, "staff-id-column")
