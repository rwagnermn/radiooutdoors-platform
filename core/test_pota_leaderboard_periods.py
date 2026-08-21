from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Adventure,
    JournalContact,
    JournalEntry,
    MemberProfile,
    PotaActivationImport,
    PotaImportBatch,
)


@override_settings(TIME_ZONE="America/Chicago")
class PotaLeaderboardPeriodTests(TestCase):
    def setUp(self):
        self.year = timezone.localdate().year
        self.sequence = 0

    def member(self, callsign):
        user = get_user_model().objects.create_user(
            username=callsign.lower(), password="test"
        )
        MemberProfile.objects.create(
            user=user,
            callsign=callsign,
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        return user

    def activation(
        self,
        owner,
        activation_date,
        counts,
        *,
        journal_public=True,
        adventure_public=True,
        pota=True,
        source=PotaImportBatch.Source.ACTIVATION_HISTORY,
        journal_date=None,
    ):
        self.sequence += 1
        adventure = Adventure.objects.create(
            owner=owner,
            title=f"Period Adventure {self.sequence}",
            is_public=adventure_public,
        )
        journal = JournalEntry.objects.create(
            adventure=adventure,
            title=f"Period Journal {self.sequence}",
            body="Period test",
            pota=pota,
            is_public=journal_public,
            entry_at=journal_date or timezone.now(),
        )
        batch = PotaImportBatch.objects.create(owner=owner, source=source)
        imported = PotaActivationImport.objects.create(
            adventure=adventure,
            journal_entry=journal,
            batch=batch,
            source=source,
            activation_date=activation_date,
            callsign=owner.member_profile.callsign,
            park_reference=f"US-{self.sequence:04d}",
            park_name=f"Period Park {self.sequence}",
            cw_contacts=counts[0],
            data_contacts=counts[1],
            phone_contacts=counts[2],
            total_contacts=999,
            fingerprint=f"period-{self.sequence}",
            location_resolution="existing",
        )
        return adventure, journal, imported

    def leaders(self, period="all"):
        url = reverse("pota_leaderboard")
        if period == "current":
            url += "?period=current"
        response = self.client.get(url)
        return response, list(response.context["leaders"])

    def leader(self, leaders, member_id):
        return next((row for row in leaders if row["member_id"] == member_id), None)

    def test_all_time_and_current_year_use_activation_date_boundaries(self):
        owner = self.member("W5BOUND")
        current_journal_date = timezone.make_aware(
            datetime(self.year, 6, 15, 12), timezone.get_current_timezone()
        )
        self.activation(
            owner,
            date(self.year - 1, 12, 31),
            (1, 2, 3),
            journal_date=current_journal_date,
        )
        self.activation(owner, date(self.year, 1, 1), (4, 5, 6))
        self.activation(owner, date(self.year, 12, 31), (7, 8, 9))

        all_response, all_leaders = self.leaders()
        current_response, current_leaders = self.leaders("current")
        self.assertEqual(
            {key: self.leader(all_leaders, owner.pk)[key] for key in ("cw", "data", "phone", "total")},
            {"cw": 12, "data": 15, "phone": 18, "total": 45},
        )
        self.assertEqual(
            {key: self.leader(current_leaders, owner.pk)[key] for key in ("cw", "data", "phone", "total")},
            {"cw": 11, "data": 13, "phone": 15, "total": 39},
        )
        self.assertContains(all_response, "All Time Rankings")
        self.assertContains(current_response, f"Current Year ({self.year})")
        self.assertContains(current_response, f"{self.year} Rankings")
        self.assertContains(current_response, 'aria-current="page"')

    def test_privacy_eligibility_and_related_records_do_not_double_count(self):
        owner = self.member("W5ELIG")
        _, eligible, _ = self.activation(
            owner, date(self.year, 5, 1), (2, 3, 4)
        )
        for index in range(3):
            JournalContact.objects.create(
                journal_entry=eligible,
                adventure=eligible.adventure,
                owner=owner,
                qso_date=date(self.year, 5, 1),
                callsign=f"K0DOUBLE{index}",
                fingerprint=f"period-contact-{index}",
            )
        self.activation(
            owner, date(self.year, 5, 2), (10, 10, 10), journal_public=False
        )
        self.activation(
            owner, date(self.year, 5, 3), (20, 20, 20), adventure_public=False
        )
        self.activation(
            owner, date(self.year, 5, 4), (30, 30, 30), pota=False
        )
        self.activation(
            owner,
            date(self.year, 5, 5),
            (40, 40, 40),
            source=PotaImportBatch.Source.HUNTER_LOG,
        )

        for period in ("all", "current"):
            _, leaders = self.leaders(period)
            row = self.leader(leaders, owner.pk)
            self.assertEqual(row["activation_count"], 1)
            self.assertEqual(
                {key: row[key] for key in ("cw", "data", "phone", "total")},
                {"cw": 2, "data": 3, "phone": 4, "total": 9},
            )

    def test_ranking_and_tie_breaking_are_period_specific(self):
        alpha = self.member("A1AAA")
        bravo = self.member("B1BBB")
        charlie = self.member("C1CCC")
        self.activation(alpha, date(self.year, 2, 1), (10, 0, 0))
        self.activation(bravo, date(self.year, 2, 2), (5, 0, 0))
        self.activation(bravo, date(self.year, 2, 3), (5, 0, 0))
        self.activation(charlie, date(self.year, 2, 4), (10, 0, 0))
        self.activation(alpha, date(self.year - 1, 2, 1), (100, 0, 0))

        _, current = self.leaders("current")
        self.assertEqual(
            [(row["member"], row["rank"]) for row in current],
            [("B1BBB", 1), ("A1AAA", 2), ("C1CCC", 3)],
        )
        _, all_time = self.leaders()
        self.assertEqual(
            [(row["member"], row["rank"]) for row in all_time],
            [("A1AAA", 1), ("B1BBB", 2), ("C1CCC", 3)],
        )

    def test_current_year_deletion_updates_both_periods_and_can_reach_zero(self):
        owner = self.member("W5CURR")
        _, journal, _ = self.activation(
            owner, date(self.year, 7, 1), (3, 4, 5)
        )
        self.client.force_login(owner)

        self.client.post(reverse("delete_journal_entry", args=[journal.pk]))

        self.assertIsNone(self.leader(self.leaders()[1], owner.pk))
        self.assertIsNone(self.leader(self.leaders("current")[1], owner.pk))

    def test_prior_year_deletion_changes_all_time_but_not_current_year(self):
        owner = self.member("W5PRIOR")
        _, old_journal, _ = self.activation(
            owner, date(self.year - 1, 7, 1), (10, 20, 30)
        )
        self.activation(owner, date(self.year, 7, 1), (1, 2, 3))
        current_before = self.leader(self.leaders("current")[1], owner.pk).copy()
        self.client.force_login(owner)

        self.client.post(reverse("delete_journal_entry", args=[old_journal.pk]))

        all_after = self.leader(self.leaders()[1], owner.pk)
        current_after = self.leader(self.leaders("current")[1], owner.pk)
        self.assertEqual(all_after["total"], 6)
        self.assertEqual(
            {key: current_after[key] for key in ("cw", "data", "phone", "total", "activation_count")},
            {key: current_before[key] for key in ("cw", "data", "phone", "total", "activation_count")},
        )
