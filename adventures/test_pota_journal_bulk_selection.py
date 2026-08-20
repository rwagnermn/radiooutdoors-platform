import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Adventure, JournalContact, JournalEntry, MemberProfile, Photo
from .views import PENDING_JOURNAL_BULK_DELETE_SESSION_KEY


class PotaJournalBulkSelectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = self.verified_user("W5OWNER")
        self.other = self.verified_user("W5OTHER")
        self.staff = get_user_model().objects.create_user(
            username="W5STAFF", password="password", is_staff=True
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Journals for POTA Activations",
            operating_callsign="W5OWNER",
            is_public=True,
        )
        self.other_adventure = Adventure.objects.create(
            owner=self.other,
            title="Other POTA Adventure",
            operating_callsign="W5OTHER",
            is_public=True,
        )
        self.journals = [
            JournalEntry.objects.create(
                adventure=self.adventure,
                title=f"POTA Journal {index:02d}",
                body="Imported POTA activation",
                pota=True,
                is_public=index != 29,
            )
            for index in range(30)
        ]
        self.other_journals = [
            JournalEntry.objects.create(
                adventure=self.other_adventure,
                title=f"Other Journal {index}",
                body="Unrelated",
                pota=True,
            )
            for index in range(3)
        ]
        self.list_url = reverse("adventure_journals", args=[self.adventure.slug])
        self.selection_url = reverse(
            "select_adventure_journals", args=[self.adventure.slug]
        )
        self.delete_url = reverse(
            "bulk_delete_adventure_journals", args=[self.adventure.slug]
        )

    def verified_user(self, callsign):
        user = get_user_model().objects.create_user(
            username=callsign, password="password"
        )
        MemberProfile.objects.create(
            user=user,
            callsign=callsign,
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        return user

    def review_selection(self, journal_ids):
        return self.client.post(
            self.delete_url,
            {
                "decision": "review",
                "selected_journal_ids": json.dumps(journal_ids),
            },
        )

    def test_owner_page_has_accessible_selector_for_every_eligible_journal(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select Journals")
        for label in (
            "Select All",
            "Select None",
            "Select Random 10",
            "Select Random 25",
            "Select Random 50",
            "Select Random 100",
            "Select Random Number…",
        ):
            self.assertContains(response, label)
        self.assertContains(response, "data-journal-selector", count=30)
        self.assertContains(response, "aria-label=\"Select Journal ", count=30)
        self.assertContains(response, "0 of 30 Journals selected")
        self.assertContains(response, "Delete Selected Journals")
        self.assertContains(response, "data-delete-selected-journals disabled")
        self.assertContains(
            response,
            "Selection covers every eligible Journal in this Adventure, not only currently visible rows.",
        )

    def test_select_all_returns_every_current_adventure_journal_only(self):
        self.client.force_login(self.owner)
        before_count = JournalEntry.objects.count()
        response = self.client.get(self.selection_url, {"mode": "all"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["eligible_count"], 30)
        self.assertEqual(payload["selected_count"], 30)
        self.assertEqual(
            set(payload["journal_ids"]), {journal.pk for journal in self.journals}
        )
        self.assertFalse(
            set(payload["journal_ids"])
            & {journal.pk for journal in self.other_journals}
        )
        none_payload = self.client.get(
            self.selection_url, {"mode": "none"}
        ).json()
        self.assertEqual(none_payload["journal_ids"], [])
        self.assertEqual(none_payload["selected_count"], 0)
        self.assertEqual(none_payload["eligible_count"], 30)
        self.assertEqual(JournalEntry.objects.count(), before_count)

    def test_random_selection_has_exact_unique_count_and_current_scope(self):
        self.client.force_login(self.owner)
        eligible_ids = {journal.pk for journal in self.journals}
        other_ids = {journal.pk for journal in self.other_journals}
        before_ids = set(JournalEntry.objects.values_list("pk", flat=True))

        for count in (10, 25):
            with self.subTest(count=count):
                response = self.client.get(
                    self.selection_url, {"mode": "random", "count": str(count)}
                )
                self.assertEqual(response.status_code, 200)
                selected_ids = response.json()["journal_ids"]
                self.assertEqual(len(selected_ids), count)
                self.assertEqual(len(set(selected_ids)), count)
                self.assertTrue(set(selected_ids) <= eligible_ids)
                self.assertFalse(set(selected_ids) & other_ids)
        self.assertEqual(
            set(JournalEntry.objects.values_list("pk", flat=True)), before_ids
        )

    def test_random_selection_rejects_invalid_counts(self):
        self.client.force_login(self.owner)
        for invalid_count in ("0", "-1", "not-a-number", "31"):
            with self.subTest(count=invalid_count):
                response = self.client.get(
                    self.selection_url,
                    {"mode": "random", "count": invalid_count},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
        self.assertEqual(
            JournalEntry.objects.filter(adventure=self.adventure).count(), 30
        )

    def test_nonmanager_never_receives_selectors_or_selection_ids(self):
        self.client.force_login(self.other)
        page = self.client.get(self.list_url)
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "data-journal-selector")
        self.assertNotContains(page, "Delete Selected Journals")
        self.assertEqual(
            self.client.get(self.selection_url, {"mode": "all"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                self.delete_url,
                {
                    "decision": "review",
                    "selected_journal_ids": json.dumps([self.journals[0].pk]),
                },
            ).status_code,
            403,
        )
        self.assertTrue(JournalEntry.objects.filter(pk=self.journals[0].pk).exists())

    def test_staff_has_the_same_adventure_scoped_selection(self):
        self.client.force_login(self.staff)
        page = self.client.get(self.list_url)
        self.assertContains(page, "data-journal-selector", count=30)
        selection = self.client.get(self.selection_url, {"mode": "all"}).json()
        self.assertEqual(
            set(selection["journal_ids"]), {journal.pk for journal in self.journals}
        )

    def test_delete_requires_post_csrf_and_explicit_confirmation(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.delete_url).status_code, 405)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        csrf_client.get(self.list_url)
        denied = csrf_client.post(
            self.delete_url,
            {
                "decision": "review",
                "selected_journal_ids": json.dumps([self.journals[0].pk]),
            },
        )
        self.assertEqual(denied.status_code, 403)

        review = self.review_selection([self.journals[0].pk, self.journals[1].pk])
        self.assertEqual(review.status_code, 200)
        self.assertContains(review, "Confirm Journal Deletion")
        self.assertContains(review, "2 Journals")
        self.assertContains(review, self.adventure.title)
        self.assertContains(review, f"Adventure ID {self.adventure.pk}")
        self.assertContains(review, "Confirm Delete 2 Journals")
        self.assertContains(review, "Cancel")
        self.assertTrue(JournalEntry.objects.filter(pk=self.journals[0].pk).exists())

        missing_confirmation = self.client.post(
            self.delete_url, {"decision": "confirm"}
        )
        self.assertEqual(missing_confirmation.status_code, 400)
        self.assertTrue(JournalEntry.objects.filter(pk=self.journals[0].pk).exists())

    def test_tampered_missing_duplicate_and_cross_adventure_ids_are_rejected(self):
        self.client.force_login(self.owner)
        submissions = (
            "",
            "not-json",
            json.dumps([]),
            json.dumps([self.journals[0].pk, self.journals[0].pk]),
            json.dumps([self.journals[0].pk, self.other_journals[0].pk]),
            json.dumps([999999]),
        )
        before_ids = set(JournalEntry.objects.values_list("pk", flat=True))
        for submitted in submissions:
            with self.subTest(submitted=submitted):
                response = self.client.post(
                    self.delete_url,
                    {"decision": "review", "selected_journal_ids": submitted},
                )
                self.assertEqual(response.status_code, 400)
        self.assertEqual(
            set(JournalEntry.objects.values_list("pk", flat=True)), before_ids
        )

    def test_cancel_clears_confirmation_and_deletes_nothing(self):
        self.client.force_login(self.owner)
        selected_ids = [self.journals[0].pk, self.journals[1].pk]
        review = self.review_selection(selected_ids)
        token = review.context["confirmation_token"]

        canceled = self.client.post(
            self.delete_url,
            {"decision": "cancel", "confirmation_token": token},
        )
        self.assertRedirects(canceled, self.list_url)
        self.assertTrue(all(JournalEntry.objects.filter(pk=pk).exists() for pk in selected_ids))
        self.assertNotIn(
            PENDING_JOURNAL_BULK_DELETE_SESSION_KEY, self.client.session
        )

    def test_confirmed_delete_is_atomic_and_removes_only_selected_journals(self):
        self.client.force_login(self.owner)
        selected = self.journals[:2]
        retained = self.journals[2]
        selected_contact = JournalContact.objects.create(
            journal_entry=selected[0],
            owner=self.owner,
            adventure=self.adventure,
            qso_date="2026-08-19",
            callsign="W1DELETE",
        )
        retained_contact = JournalContact.objects.create(
            journal_entry=retained,
            owner=self.owner,
            adventure=self.adventure,
            qso_date="2026-08-19",
            callsign="W1KEEP",
        )
        selected_photo = Photo.objects.create(
            journal_entry=selected[0], image="test/selected-cover.jpg"
        )
        self.adventure.cover_photo = selected_photo
        self.adventure.cover_photo_is_explicit = True
        self.adventure.save(
            update_fields=["cover_photo", "cover_photo_is_explicit", "updated_at"]
        )
        before_other_ids = set(
            self.other_adventure.journal_entries.values_list("pk", flat=True)
        )
        review = self.review_selection([journal.pk for journal in selected])
        token = review.context["confirmation_token"]

        confirmed = self.client.post(
            self.delete_url,
            {"decision": "confirm", "confirmation_token": token},
            follow=True,
        )

        self.assertRedirects(confirmed, self.list_url)
        self.assertContains(
            confirmed,
            f"Deleted 2 Journals from {self.adventure.title} (Adventure ID {self.adventure.pk}).",
        )
        self.assertFalse(
            JournalEntry.objects.filter(pk__in=[journal.pk for journal in selected]).exists()
        )
        self.assertFalse(JournalContact.objects.filter(pk=selected_contact.pk).exists())
        self.assertTrue(JournalEntry.objects.filter(pk=retained.pk).exists())
        self.assertTrue(JournalContact.objects.filter(pk=retained_contact.pk).exists())
        self.assertEqual(
            set(self.other_adventure.journal_entries.values_list("pk", flat=True)),
            before_other_ids,
        )
        self.assertTrue(Adventure.objects.filter(pk=self.adventure.pk).exists())
        self.adventure.refresh_from_db()
        self.assertIsNone(self.adventure.cover_photo_id)
        self.assertFalse(self.adventure.cover_photo_is_explicit)

    def test_final_confirmation_rechecks_session_ids_and_authorization(self):
        self.client.force_login(self.owner)
        review = self.review_selection([self.journals[0].pk])
        token = review.context["confirmation_token"]
        session = self.client.session
        pending = session[PENDING_JOURNAL_BULK_DELETE_SESSION_KEY]
        pending["journal_ids"].append(self.other_journals[0].pk)
        session[PENDING_JOURNAL_BULK_DELETE_SESSION_KEY] = pending
        session.save()

        rejected = self.client.post(
            self.delete_url,
            {"decision": "confirm", "confirmation_token": token},
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertTrue(JournalEntry.objects.filter(pk=self.journals[0].pk).exists())
        self.assertTrue(
            JournalEntry.objects.filter(pk=self.other_journals[0].pk).exists()
        )
