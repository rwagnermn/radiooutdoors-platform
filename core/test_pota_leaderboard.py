from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import resolve, reverse

from .models import (
    Adventure,
    JournalEntry,
    MemberProfile,
    PotaActivationImport,
    PotaImportBatch,
)


class PotaLeaderboardRouteTests(TestCase):
    def create_activation(
        self,
        *,
        owner,
        callsign,
        fingerprint,
        park_reference,
        total_contacts,
        cw_contacts=0,
        data_contacts=0,
        phone_contacts=0,
        is_public=True,
    ):
        MemberProfile.objects.get_or_create(
            user=owner,
            defaults={
                "callsign": callsign.upper(),
                "callsign_verified": True,
                "verification_method": MemberProfile.VerificationMethod.QRZ,
            },
        )
        adventure = Adventure.objects.create(
            owner=owner,
            title=f"{callsign} at {park_reference}",
            is_public=is_public,
        )
        journal = JournalEntry.objects.create(
            adventure=adventure,
            title=f"Activation at {park_reference}",
            body="Imported activation",
            is_public=is_public,
            pota=True,
        )
        batch = PotaImportBatch.objects.create(owner=owner)
        return PotaActivationImport.objects.create(
            adventure=adventure,
            journal_entry=journal,
            batch=batch,
            activation_date=date(2026, 8, 18),
            callsign=callsign,
            park_reference=park_reference,
            park_name="Test Park",
            cw_contacts=cw_contacts,
            data_contacts=data_contacts,
            phone_contacts=phone_contacts,
            total_contacts=total_contacts,
            fingerprint=fingerprint,
            location_resolution="existing",
        )

    def test_home_hero_no_longer_links_to_leaderboard(self):
        leaderboard_url = reverse("pota_leaderboard")
        self.assertEqual(leaderboard_url, "/pota/leaderboard/")

        visitor_home = self.client.get(reverse("home"))
        self.assertEqual(visitor_home.status_code, 200)
        self.assertTemplateUsed(visitor_home, "core/home.html")
        self.assertNotContains(
            visitor_home,
            (
                f'<a href="{leaderboard_url}" class="btn-ro-primary home-cta">'
                "POTA Leaderboard</a>"
            ),
            html=True,
        )

    def test_account_dropdown_links_to_leaderboard_immediately_before_account(self):
        leaderboard_url = reverse("pota_leaderboard")
        account_url = reverse("account_home")

        member = get_user_model().objects.create_user(
            username="leaderboard-member",
            password="StrongPass!942",
        )
        self.client.force_login(member)
        member_home = self.client.get(reverse("home"))

        rendered_html = member_home.content.decode()
        leaderboard_link = f'<a href="{leaderboard_url}">POTA Leaderboard</a>'
        account_link = f'<a href="{account_url}">My Account</a>'
        self.assertContains(member_home, leaderboard_link, count=1, html=True)
        self.assertEqual(rendered_html.count(leaderboard_link), 1)
        self.assertIn(
            f"{leaderboard_link}\n{account_link}",
            rendered_html,
        )
        self.assertContains(member_home, account_link, html=True)
        self.assertContains(member_home, "About")
        self.assertContains(member_home, "Help")
        self.assertContains(member_home, "Support Radio Outdoors")
        self.assertContains(member_home, "Sign Out")

        hero_html = rendered_html.split('<div class="hero-buttons">', 1)[1].split(
            "</div>", 1
        )[0]
        self.assertNotIn("POTA Leaderboard", hero_html)
        main_navigation = rendered_html.split(
            '<nav class="main-nav"', 1
        )[1].split("</nav>", 1)[0]
        self.assertNotIn("POTA Leaderboard", main_navigation)

    def test_leaderboard_named_route_is_public_and_renders_page(self):
        match = resolve("/pota/leaderboard/")
        self.assertEqual(match.view_name, "pota_leaderboard")

        response = self.client.get(reverse("pota_leaderboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/pota_leaderboard.html")
        self.assertContains(response, "<h1>POTA Leaderboard</h1>", html=True)

    def test_leaderboard_aggregates_public_activation_history_only(self):
        owner = get_user_model().objects.create_user(username="public-activator")
        self.create_activation(
            owner=owner,
            callsign="w5public",
            fingerprint="public-one",
            park_reference="US-0001",
            total_contacts=8,
            cw_contacts=2,
            data_contacts=1,
            phone_contacts=5,
        )
        self.create_activation(
            owner=owner,
            callsign="W5PUBLIC",
            fingerprint="public-two",
            park_reference="US-0002",
            total_contacts=7,
            cw_contacts=3,
            data_contacts=2,
            phone_contacts=2,
        )
        self.create_activation(
            owner=owner,
            callsign="N0PRIVATE",
            fingerprint="private-one",
            park_reference="US-9999",
            total_contacts=99,
            is_public=False,
        )

        response = self.client.get(reverse("pota_leaderboard"))
        leaders = list(response.context["leaders"])

        self.assertEqual(len(leaders), 1)
        self.assertEqual(leaders[0]["member"], "W5PUBLIC")
        self.assertEqual(leaders[0]["activation_count"], 2)
        self.assertEqual(leaders[0]["cw"], 5)
        self.assertEqual(leaders[0]["data"], 3)
        self.assertEqual(leaders[0]["phone"], 7)
        self.assertEqual(leaders[0]["total"], 15)
        self.assertEqual(leaders[0]["rank"], 1)
        self.assertContains(response, "W5PUBLIC")
        self.assertNotContains(response, "N0PRIVATE")


@override_settings(GOOGLE_GEOCODING_API_KEY="")
class PotaLeaderboardImportRefreshTests(TestCase):
    IMPORT_ROWS = (
        "2026-08-18 W5FRESH US-1001 First Park US-MN 2 3 5 11\n"
        "2026-08-19 W5FRESH US-1002 Second Park US-MN 4 1 6 12"
    )

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="leaderboard-importer", password="test"
        )
        MemberProfile.objects.create(
            user=self.user,
            callsign="W5FRESH",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = get_user_model().objects.create_user(username="other-member")
        MemberProfile.objects.create(
            user=self.other,
            callsign="N0OTHER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.client.force_login(self.user)

    def _import(self, rows=None, name="Fresh POTA Activations"):
        start = self.client.post(
            reverse("import_pota_history"),
            {"pota_history": rows or self.IMPORT_ROWS},
        )
        token = start.url.rstrip("/").split("/")[-1]
        confirm = self.client.post(
            reverse("confirm_pota_history", args=[token]),
            {
                "selected_rows": "[0, 1]",
                "import_organization": "grouped",
                "destination_choice": "new",
                "new_adventure_name": name,
                "new_adventure_visibility": "public",
                "publish_pota_batch": "yes",
            },
        )
        return token, confirm

    def _leader(self, member):
        response = self.client.get(reverse("pota_leaderboard"))
        leaders = list(response.context["leaders"])
        return response, next((row for row in leaders if row["member"] == member), None)

    def _create_other_activation(self, *, total=15, is_public=True):
        adventure = Adventure.objects.create(
            owner=self.other, title="Other POTA", is_public=is_public
        )
        journal = JournalEntry.objects.create(
            adventure=adventure,
            title="Other POTA Journal",
            body="Other member",
            is_public=is_public,
            pota=True,
        )
        batch = PotaImportBatch.objects.create(owner=self.other)
        activation = PotaActivationImport.objects.create(
            adventure=adventure,
            journal_entry=journal,
            batch=batch,
            activation_date=date(2026, 8, 17),
            callsign="N0OTHER",
            park_reference="US-9000",
            park_name="Other Park",
            cw_contacts=5,
            data_contacts=4,
            phone_contacts=6,
            total_contacts=total,
            fingerprint=f"other-{adventure.pk}-{is_public}",
            location_resolution="existing",
        )
        return adventure, journal, activation

    def test_import_updates_all_totals_and_rank_on_the_next_request(self):
        self._create_other_activation(total=15)
        before = self.client.get(reverse("pota_leaderboard"))
        self.assertEqual(
            [(row["member"], row["total"]) for row in before.context["leaders"]],
            [("N0OTHER", 15)],
        )

        _, confirmed = self._import()
        adventure = Adventure.objects.get(title="Fresh POTA Activations")
        self.assertRedirects(confirmed, adventure.get_absolute_url())
        imports = list(
            PotaActivationImport.objects.filter(journal_entry__adventure=adventure)
            .order_by("activation_date")
            .values_list(
                "cw_contacts", "data_contacts", "phone_contacts", "total_contacts"
            )
        )
        self.assertEqual(imports, [(2, 3, 5, 11), (4, 1, 6, 12)])

        response, leader = self._leader("W5FRESH")
        self.assertEqual(
            {key: leader[key] for key in ("cw", "data", "phone", "total", "rank")},
            {"cw": 6, "data": 4, "phone": 11, "total": 23, "rank": 1},
        )
        other = next(row for row in response.context["leaders"] if row["member"] == "N0OTHER")
        self.assertEqual(other["rank"], 2)
        rollup = self.client.get(adventure.get_absolute_url()).context["pota_rollup"]
        self.assertEqual(rollup, {"cw": 6, "data": 4, "phone": 11, "total": 23})

        refreshed, refreshed_leader = self._leader("W5FRESH")
        self.assertEqual(refreshed_leader["total"], 23)
        self.assertEqual(len(refreshed.context["leaders"]), 2)

    def test_duplicate_and_aborted_imports_do_not_change_totals(self):
        self._import()
        before = self._leader("W5FRESH")[1]

        duplicate_start = self.client.post(
            reverse("import_pota_history"), {"pota_history": self.IMPORT_ROWS}
        )
        duplicate_token = duplicate_start.url.rstrip("/").split("/")[-1]
        self.client.post(
            reverse("confirm_pota_history", args=[duplicate_token]),
            {"selected_rows": "[0, 1]"},
        )
        self.assertEqual(PotaActivationImport.objects.filter(batch__owner=self.user).count(), 2)
        self.assertEqual(self._leader("W5FRESH")[1]["total"], before["total"])

        abort_rows = "2026-08-20 W5FRESH US-1003 Third Park US-MN 9 9 9 27"
        abort_start = self.client.post(
            reverse("import_pota_history"), {"pota_history": abort_rows}
        )
        abort_token = abort_start.url.rstrip("/").split("/")[-1]
        self.client.get(reverse("abort_pota_history", args=[abort_token]))
        self.assertEqual(PotaActivationImport.objects.filter(batch__owner=self.user).count(), 2)
        self.assertEqual(self._leader("W5FRESH")[1]["total"], before["total"])

    def test_edit_delete_move_and_visibility_use_current_journal_state(self):
        self._import()
        adventure = Adventure.objects.get(title="Fresh POTA Activations")
        activation = PotaActivationImport.objects.filter(
            journal_entry__adventure=adventure
        ).order_by("activation_date").first()

        activation.cw_contacts = 20
        activation.total_contacts = 29
        activation.save(update_fields=["cw_contacts", "total_contacts"])
        self.assertEqual(self._leader("W5FRESH")[1]["cw"], 24)
        self.assertEqual(self._leader("W5FRESH")[1]["total"], 41)

        activation.journal_entry.is_public = False
        activation.journal_entry.save(update_fields=["is_public", "updated_at"])
        self.assertEqual(self._leader("W5FRESH")[1]["total"], 12)

        activation.journal_entry.is_public = True
        activation.journal_entry.save(update_fields=["is_public", "updated_at"])
        destination = Adventure.objects.create(
            owner=self.other, title="Moved POTA", is_public=True
        )
        activation.journal_entry.adventure = destination
        activation.journal_entry.save(update_fields=["adventure", "updated_at"])
        self.assertEqual(self._leader("W5FRESH")[1]["total"], 12)
        self.assertEqual(self._leader("N0OTHER")[1]["total"], 29)

        activation.journal_entry.delete()
        self.assertIsNone(self._leader("N0OTHER")[1])
        self.assertEqual(self._leader("W5FRESH")[1]["total"], 12)

    def test_private_non_pota_and_other_member_rows_are_not_misattributed(self):
        self._import()
        private_adventure, _, _ = self._create_other_activation(
            total=999, is_public=False
        )
        ordinary = JournalEntry.objects.create(
            adventure=private_adventure,
            title="Not a POTA Journal",
            body="ordinary",
            is_public=True,
            pota=False,
        )
        ordinary_import = PotaActivationImport.objects.create(
            adventure=private_adventure,
            journal_entry=ordinary,
            batch=PotaImportBatch.objects.create(owner=self.other),
            activation_date=date(2026, 8, 16),
            callsign="N0OTHER",
            park_reference="US-9001",
            park_name="Not eligible",
            total_contacts=777,
            fingerprint="ordinary-not-pota",
            location_resolution="existing",
        )

        response, importer = self._leader("W5FRESH")
        self.assertEqual(importer["total"], 23)
        self.assertFalse(any(row["member"] == "N0OTHER" for row in response.context["leaders"]))
        self.assertTrue(PotaActivationImport.objects.filter(pk=ordinary_import.pk).exists())
