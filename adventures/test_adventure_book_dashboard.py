from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, Location, MemberProfile


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
        self.assertIn(".adventure-panel-list { display:grid; gap:10px; overflow:visible; }", css)
        self.assertNotIn(".adventure-panel-list { height:100vh", css)
        self.assertIn("@media (max-width:700px)", css)
        self.assertIn(".adventure-panel-photo { grid-column:1/3; width:100%;", css)
