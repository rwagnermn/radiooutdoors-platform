from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Adventure,
    JournalContact,
    JournalEntry,
    Location,
    MemberProfile,
    Photo,
    PotaActivationImport,
    PotaImportBatch,
)


class PublicReadOnlyPermissionMatrixTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("public-owner", password="test")
        MemberProfile.objects.create(
            user=self.owner,
            callsign="W0OWNER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = users.objects.create_user("public-other", password="test")
        MemberProfile.objects.create(
            user=self.other,
            callsign="W0OTHER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.staff = users.objects.create_user(
            "public-staff", password="test", is_staff=True
        )
        self.public_location = Location.objects.create(
            name="Public Ridge",
            created_by=self.owner,
            latitude="44.100000",
            longitude="-93.200000",
            visibility=Location.Visibility.PUBLIC,
        )
        self.private_location = Location.objects.create(
            name="Secret Private Coordinates",
            created_by=self.owner,
            latitude="45.987654",
            longitude="-94.123456",
            visibility=Location.Visibility.PRIVATE,
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Public Read Only Adventure",
            operating_callsign="W0OWNER",
            summary="Public Adventure story text.",
            lessons_learned="Public lessons learned.",
            location=self.public_location,
            is_public=True,
        )
        self.public_journal = JournalEntry.objects.create(
            adventure=self.adventure,
            location=self.public_location,
            latitude=self.public_location.latitude,
            longitude=self.public_location.longitude,
            title="Visible Public Journal",
            body="Visible public Journal notes.",
            operating_callsign="W0OWNER",
            is_public=True,
            pota=True,
        )
        self.masked_location_journal = JournalEntry.objects.create(
            adventure=self.adventure,
            location=self.private_location,
            latitude=self.private_location.latitude,
            longitude=self.private_location.longitude,
            title="Public Journal With Private Location",
            body="The Journal story is public but its Location is not.",
            is_public=True,
        )
        self.private_journal = JournalEntry.objects.create(
            adventure=self.adventure,
            location=self.private_location,
            latitude=self.private_location.latitude,
            longitude=self.private_location.longitude,
            title="Hidden Private Journal",
            body="Hidden private Journal notes.",
            is_public=False,
            pota=True,
        )
        self.public_contact = JournalContact.objects.create(
            journal_entry=self.public_journal,
            callsign="K1PUBLIC",
            qso_date=self.public_journal.entry_at.date(),
            latitude="40.100000",
            longitude="-75.200000",
            fingerprint="public-contact",
        )
        self.private_contact = JournalContact.objects.create(
            journal_entry=self.private_journal,
            callsign="K1PRIVATE",
            qso_date=self.private_journal.entry_at.date(),
            latitude="41.654321",
            longitude="-76.123456",
            fingerprint="private-contact",
        )
        self.public_photo = Photo.objects.create(
            journal_entry=self.public_journal,
            image=SimpleUploadedFile("public.jpg", b"public-image"),
            caption="Approved public photo",
            moderation_status=Photo.ModerationStatus.APPROVED,
        )
        self.restricted_photo = Photo.objects.create(
            journal_entry=self.public_journal,
            image=SimpleUploadedFile("restricted.jpg", b"restricted-image"),
            caption="Restricted pending photo",
            moderation_status=Photo.ModerationStatus.REJECTED,
        )
        self.private_photo = Photo.objects.create(
            journal_entry=self.private_journal,
            image=SimpleUploadedFile("private.jpg", b"private-image"),
            caption="Private Journal approved photo",
            moderation_status=Photo.ModerationStatus.APPROVED,
        )
        batch = PotaImportBatch.objects.create(
            owner=self.owner,
            source=PotaImportBatch.Source.ACTIVATION_HISTORY,
        )
        self._pota_import(batch, self.public_journal, "public-pota", 3)
        self._pota_import(batch, self.private_journal, "private-pota", 99)

    def _pota_import(self, batch, journal, fingerprint, total):
        PotaActivationImport.objects.create(
            adventure=self.adventure,
            journal_entry=journal,
            batch=batch,
            activation_date=journal.entry_at.date(),
            callsign="W0OWNER",
            park_reference="US-0001",
            park_name="Permission Park",
            total_contacts=total,
            phone_contacts=total,
            fingerprint=fingerprint,
            location_resolution="existing",
        )

    def _assert_public_read_only(self):
        detail = self.client.get(self.adventure.get_absolute_url())
        self.assertEqual(detail.status_code, 200)
        for text in (
            self.adventure.title,
            f"Adventure ID {self.adventure.pk}",
            "Public Adventure story text.",
            "Public lessons learned.",
            "W0OWNER",
            "Visible Public Journal",
            "Public Journal With Private Location",
            "K1PUBLIC",
            "Approved public photo",
            "View Contacts",
            "View All Journals",
        ):
            self.assertContains(detail, text)
        for text in (
            "Hidden Private Journal",
            "Hidden private Journal notes.",
            "K1PRIVATE",
            "Restricted pending photo",
            "Private Journal approved photo",
            "Secret Private Coordinates",
            "Edit Adventure",
            "+ Add Journal Entry",
            "Delete Adventure",
            "Import Contacts",
            "Make Private",
        ):
            self.assertNotContains(detail, text)
        self.assertEqual(detail.context["journal_entry_count"], 2)
        self.assertEqual(detail.context["pota_rollup"]["total"], 3)
        self.assertEqual(len(detail.context["adventure_photos"]), 1)
        self.assertEqual(len(detail.context["journal_location_map_data"]), 1)
        self.assertContains(detail, "Private Location")
        self.assertNotContains(detail, "45.987654")
        self.assertNotContains(detail, "-94.123456")

        journals = self.client.get(
            reverse("adventure_journals", args=[self.adventure.slug])
        )
        self.assertEqual(journals.status_code, 200)
        self.assertContains(journals, "Visible Public Journal")
        self.assertContains(journals, "Public Journal With Private Location")
        self.assertContains(journals, "Private Location")
        self.assertNotContains(journals, "Hidden Private Journal")
        self.assertNotContains(journals, "Secret Private Coordinates")
        visible = {row.pk: row for row in journals.context["journal_entries"]}
        self.assertEqual(visible[self.public_journal.pk].dashboard_photo_count, 1)

        contacts = self.client.get(
            reverse("adventure_contacts", args=[self.adventure.slug])
        )
        self.assertEqual(contacts.status_code, 200)
        self.assertContains(contacts, "K1PUBLIC")
        self.assertNotContains(contacts, "K1PRIVATE")
        self.assertNotContains(contacts, "41.654321")
        self.assertNotContains(contacts, "-76.123456")

        journal = self.client.get(
            reverse("journal_entry_detail", args=[self.public_journal.pk])
        )
        self.assertEqual(journal.status_code, 200)
        for text in (
            "Journal Page",
            "Visible Public Journal",
            self.adventure.title,
            "Visible public Journal notes.",
            "K1PUBLIC",
            "1 total",
            "View Map",
            "View All Photos",
            "Public",
        ):
            self.assertContains(journal, text)
        for text in (
            "Edit Journal",
            "Delete Journal",
            "Add Contact",
            "Import Contacts",
            "Add Photo",
            "Delete Contact",
            "Change Journal visibility",
        ):
            self.assertNotContains(journal, text)
        self.assertEqual(
            self.client.get(
                reverse("journal_contact_map", args=[self.public_journal.pk])
            ).status_code,
            200,
        )
        gallery = self.client.get(
            reverse("journal_photo_gallery", args=[self.public_journal.pk])
        )
        self.assertEqual(gallery.status_code, 200)
        self.assertContains(gallery, "Approved public photo")
        self.assertNotContains(gallery, "Restricted pending photo")
        self.assertNotContains(gallery, "Delete Selected Photos")

        for url in (
            reverse("journal_entry_detail", args=[self.private_journal.pk]),
            reverse("journal_contact_map", args=[self.private_journal.pk]),
            reverse("journal_photo_gallery", args=[self.private_journal.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_anonymous_visitor_has_complete_public_read_only_access(self):
        self._assert_public_read_only()

        book = self.client.get(reverse("all_adventures"))
        row = book.context["adventures"].get(pk=self.adventure.pk)
        self.assertEqual(row.journal_count, 2)
        self.assertEqual(row.photo_count, 1)
        self.assertEqual(row.contact_count, 1)

    def test_signed_in_non_owner_has_complete_public_read_only_access(self):
        self.client.force_login(self.other)
        self._assert_public_read_only()

    def test_owner_retains_management_controls(self):
        self.client.force_login(self.owner)
        adventure = self.client.get(self.adventure.get_absolute_url())
        for text in (
            "+ Add Journal Entry",
            "Edit Adventure",
            "Delete Adventure",
        ):
            self.assertContains(adventure, text)
        self.assertNotContains(adventure, "Make Private")
        self.assertContains(adventure, "Hidden Private Journal")

        journal = self.client.get(
            reverse("journal_entry_detail", args=[self.public_journal.pk])
        )
        for text in (
            "Edit Journal",
            "Delete Journal",
            "Add Contact",
            "Import Contacts",
            "Add Photo",
        ):
            self.assertContains(journal, text)

    def test_authorized_staff_controls_match_server_permissions(self):
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(reverse("edit_adventure", args=[self.adventure.slug])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("add_journal_entry", args=[self.adventure.slug])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("edit_journal_entry", args=[self.public_journal.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("journal_photo_gallery", args=[self.private_journal.pk])).status_code,
            200,
        )
        response = self.client.post(
            reverse("toggle_journal_status", args=[self.public_journal.pk])
        )
        self.assertEqual(response.status_code, 302)

    def test_non_owner_forged_mutations_and_gets_are_blocked(self):
        self.client.force_login(self.other)
        get_only_mutations = (
            reverse("toggle_adventure_visibility", args=[self.adventure.slug]),
            reverse("delete_adventure", args=[self.adventure.slug]),
            reverse("toggle_journal_visibility", args=[self.public_journal.pk]),
            reverse("toggle_journal_status", args=[self.public_journal.pk]),
            reverse("delete_journal_entry", args=[self.public_journal.pk]),
            reverse(
                "delete_journal_contact",
                args=[self.public_journal.pk, self.public_contact.pk],
            ),
            reverse("delete_photo", args=[self.public_photo.pk]),
        )
        for url in get_only_mutations:
            self.assertEqual(self.client.get(url).status_code, 405)

        for url in (
            reverse("edit_adventure", args=[self.adventure.slug]),
            reverse("add_journal_entry", args=[self.adventure.slug]),
            reverse("edit_journal_entry", args=[self.public_journal.pk]),
            reverse("add_journal_contact", args=[self.public_journal.pk]),
            reverse("import_adif", args=[self.public_journal.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 403)

        original_visibility = self.adventure.is_public
        for url in (
            reverse("toggle_adventure_visibility", args=[self.adventure.slug]),
            reverse("delete_adventure", args=[self.adventure.slug]),
            reverse("toggle_journal_visibility", args=[self.public_journal.pk]),
            reverse("toggle_journal_status", args=[self.public_journal.pk]),
            reverse("delete_journal_entry", args=[self.public_journal.pk]),
            reverse(
                "delete_journal_contact",
                args=[self.public_journal.pk, self.public_contact.pk],
            ),
            reverse("delete_photo", args=[self.public_photo.pk]),
        ):
            self.assertEqual(self.client.post(url).status_code, 403)
        self.adventure.refresh_from_db()
        self.assertEqual(self.adventure.is_public, original_visibility)
        self.assertTrue(JournalEntry.objects.filter(pk=self.public_journal.pk).exists())
        self.assertTrue(JournalContact.objects.filter(pk=self.public_contact.pk).exists())
        self.assertTrue(Photo.objects.filter(pk=self.public_photo.pk).exists())

    def test_private_adventure_is_hidden_from_unauthorized_users(self):
        self.adventure.is_public = False
        self.adventure.save(update_fields=["is_public", "updated_at"])
        for user in (None, self.other):
            if user is None:
                self.client.logout()
            else:
                self.client.force_login(user)
            self.assertEqual(
                self.client.get(self.adventure.get_absolute_url()).status_code, 404
            )
