from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, JournalEntry, Location, MemberProfile


class AdventureBookDashboardTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("book-owner", password="test-password")
        MemberProfile.objects.create(
            user=self.owner,
            callsign="W0BOOK",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = users.objects.create_user("book-other", password="test-password")
        self.lake = Location.objects.create(
            name="Extremely Long Lake and Wildlife Management Area",
            city="North Woods",
            state="MN",
            created_by=self.owner,
        )
        self.park = Location.objects.create(
            name="Short Park", city="Duluth", state="MN", created_by=self.owner
        )
        self.open_adventure = Adventure.objects.create(
            owner=self.owner,
            title="A Very Long Adventure Name That Must Wrap Without Overlapping Counts",
            location=self.lake,
            status=Adventure.Status.ACTIVE,
            is_public=True,
        )
        self.complete_adventure = Adventure.objects.create(
            owner=self.owner,
            title="Completed Forest Adventure",
            location=self.park,
            status=Adventure.Status.COMPLETED,
            is_public=False,
        )
        self.open_journal = JournalEntry.objects.create(
            adventure=self.open_adventure,
            location=self.lake,
            title="Lake journal",
            body="At the lake.",
            is_public=True,
        )
        self.complete_journal = JournalEntry.objects.create(
            adventure=self.complete_adventure,
            location=self.park,
            status=JournalEntry.Status.COMPLETED,
            title="Park journal",
            body="At the park.",
            is_public=True,
        )
        self.client.force_login(self.owner)

    def test_my_book_has_actions_modes_panels_and_real_links(self):
        response = self.client.get(reverse("my_adventures"))
        self.assertContains(response, "My Adventures")
        self.assertContains(response, "Import POTA History")
        self.assertContains(response, "Import POTA Contacts")
        self.assertContains(response, "Import POTA History", count=1)
        self.assertContains(response, "Import POTA Contacts", count=1)
        self.assertContains(response, "Add Adventure")
        self.assertContains(response, 'class="adventure-panel-list"')
        self.assertNotContains(response, "<table")
        self.assertContains(response, self.open_adventure.get_absolute_url())
        self.assertContains(response, f"Adventure ID {self.open_adventure.pk}")
        self.assertContains(response, "Public")
        self.assertContains(response, "Private")
        self.assertContains(response, 'class="ro-action-menu adventure-row-menu"')
        self.assertContains(response, ">View</a>")
        self.assertContains(response, ">Edit</a>")
        self.assertContains(response, ">Delete</button>")
        self.assertContains(response, reverse("all_adventures"))

    def test_my_book_search_status_and_location_filters_work(self):
        searched = self.client.get(reverse("my_adventures"), {"q": "Wildlife"})
        self.assertContains(searched, self.open_adventure.title)
        self.assertNotContains(searched, self.complete_adventure.title)

        completed = self.client.get(reverse("my_adventures"), {"activity": "complete"})
        self.assertContains(completed, self.complete_adventure.title)
        self.assertNotContains(completed, self.open_adventure.title)

        located = self.client.get(reverse("my_adventures"), {"place": self.park.pk})
        self.assertContains(located, self.complete_adventure.title)
        self.assertNotContains(located, self.open_adventure.title)

    def test_book_panels_never_present_an_adventure_location(self):
        no_journals = Adventure.objects.create(
            owner=self.owner,
            title="Adventure Without Journals",
            is_public=True,
        )
        second_location = Location.objects.create(
            name="Second Journal Location",
            created_by=self.owner,
        )
        JournalEntry.objects.create(
            adventure=self.open_adventure,
            location=second_location,
            title="Second place",
            body="At another place.",
        )

        for url in (reverse("my_adventures"), reverse("all_adventures")):
            response = self.client.get(url)
            panel_markup = response.content.decode().split(
                '<div class="adventure-panel-list"', 1
            )[1]
            self.assertContains(response, no_journals.title)
            self.assertNotContains(response, "Location not specified")
            self.assertNotContains(response, 'class="adventure-panel-location"')
            self.assertNotContains(response, "⌖")
            self.assertNotIn(self.lake.name, panel_markup)
            self.assertNotIn(second_location.name, panel_markup)

    def test_location_filter_uses_authorized_journals_without_duplicates(self):
        JournalEntry.objects.create(
            adventure=self.open_adventure,
            location=self.lake,
            title="Same place again",
            body="A return visit.",
        )
        located = self.client.get(reverse("my_adventures"), {"place": self.lake.pk})
        self.assertEqual(
            list(located.context["adventures"]).count(self.open_adventure),
            1,
        )

        private_location = Location.objects.create(
            name="Owner Secret Journal Place",
            created_by=self.owner,
            visibility=Location.Visibility.PRIVATE,
        )
        JournalEntry.objects.create(
            adventure=self.open_adventure,
            location=private_location,
            title="Public journal at private location",
            body="The Location itself is private.",
            is_public=True,
        )
        private_journal_location = Location.objects.create(
            name="Private Journal Public Place",
            created_by=self.owner,
        )
        JournalEntry.objects.create(
            adventure=self.open_adventure,
            location=private_journal_location,
            title="Private journal",
            body="The Journal is not public.",
            is_public=False,
        )
        self.client.logout()
        for hidden_location in (private_location, private_journal_location):
            public_filter = self.client.get(
                reverse("all_adventures"), {"place": hidden_location.pk}
            )
            self.assertNotContains(public_filter, self.open_adventure.title)
            self.assertNotContains(public_filter, hidden_location.name)

    def test_journal_location_still_displays_on_journal_page(self):
        response = self.client.get(
            reverse("journal_entry_detail", args=[self.open_journal.pk])
        )
        self.assertContains(response, self.lake.name)

    def test_public_switch_and_filters_preserve_visibility_permissions(self):
        public = self.client.get(reverse("all_adventures"), {"activity": "open"})
        self.assertContains(public, self.open_adventure.title)
        self.assertNotContains(public, self.complete_adventure.title)
        self.assertContains(public, reverse("my_adventures"))

        self.client.logout()
        anonymous = self.client.get(reverse("all_adventures"))
        self.assertContains(anonymous, self.open_adventure.title)
        self.assertNotContains(anonymous, self.complete_adventure.title)
        self.assertNotContains(anonymous, ">Edit</a>")
        self.assertNotContains(anonymous, ">Delete</button>")

    def test_empty_state_is_a_panel_not_a_table_row(self):
        response = self.client.get(reverse("my_adventures"), {"q": "no-match-value"})
        self.assertContains(response, "No adventures match these filters.")
        self.assertContains(response, 'class="adventure-panel-empty"')
        self.assertNotContains(response, "empty-table-message")

    def test_book_css_keeps_document_scroll_and_responsive_wrapping(self):
        from django.conf import settings

        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn(".adventure-book-page { min-height:100%;", css)
        self.assertIn("overflow-y:auto", css)
        self.assertIn("body.adventure-book-page .content.adventure-book-content", css)
        self.assertIn('url("../images/adventure-detail-pencil-background.png")', css)
        self.assertIn("overflow-wrap:anywhere", css)
        self.assertNotIn(".adventure-panel-location", css)
        self.assertIn(".adventure-panel-list { display:grid; gap:10px; overflow:visible; }", css)
        self.assertNotIn(".adventure-panel-list { height:100vh", css)
        self.assertIn("@media (max-width:700px)", css)
        self.assertIn(".adventure-panel-photo { grid-column:1/3; width:100%;", css)
