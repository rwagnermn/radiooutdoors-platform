from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import Adventure, JournalEntry, MemberProfile


NOTICE = "QSO\u2019s and Contacts, Map Locations & Photos are stored in Journals."
NOTICE_HTML = "QSO\u2019s and Contacts, Map Locations &amp; Photos are stored in Journals."


class AdventureJournalNoticeTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("notice-owner", password="test")
        MemberProfile.objects.create(
            user=self.owner,
            callsign="W0NOTICE",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = users.objects.create_user("notice-other", password="test")
        MemberProfile.objects.create(
            user=self.other,
            callsign="W0OTHER",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.public_adventure = Adventure.objects.create(
            owner=self.owner,
            title="Public Notice Adventure",
            operating_callsign="W0NOTICE",
            is_public=True,
        )
        JournalEntry.objects.create(
            adventure=self.public_adventure,
            title="Public Notice Journal",
            body="Public Journal body.",
            is_public=True,
        )
        self.private_adventure = Adventure.objects.create(
            owner=self.owner,
            title="Private Notice Adventure",
            operating_callsign="W0NOTICE",
            is_public=False,
        )

    def test_notice_appears_once_inside_journal_panel_before_list(self):
        response = self.client.get(self.public_adventure.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, NOTICE_HTML, count=1)

        source = response.content.decode()
        panel = source.split('<section id="journal-entries"', 1)[1].split(
            "</section>", 1
        )[0]
        self.assertIn("<h2>Adventure Journals</h2>", panel)
        self.assertIn(NOTICE_HTML, panel)
        self.assertLess(panel.index("<h2>Adventure Journals</h2>"), panel.index(NOTICE_HTML))
        self.assertLess(panel.index(NOTICE_HTML), panel.index("adventure-journal-scroll-shell"))
        self.assertNotIn("adventure-dashboard-hero-note", source)

    def test_initial_and_permanent_notice_styles_are_accessible_and_visible(self):
        response = self.client.get(self.public_adventure.get_absolute_url())
        self.assertContains(
            response,
            'class="adventure-journal-storage-notice" data-journal-storage-notice role="status"',
        )

        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("background: #8b1e1e; color: #fff", css)
        self.assertIn("font-weight: 900", css)
        self.assertIn("justify-content: center", css)
        self.assertIn("padding: 5px 16px", css)
        self.assertIn("text-align: center", css)
        self.assertIn("transition: background-color .5s ease, color .5s ease", css)
        self.assertIn(
            ".adventure-journal-storage-notice.is-permanent { background: #f7d8cc; color: #4f2118; }",
            css,
        )
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn(".adventure-journal-storage-notice { transition: none; }", css)
        self.assertNotIn("display: none", css[css.index(".adventure-journal-storage-notice"):css.index(".adventure-dashboard-journal-scroll")])

    def test_timer_changes_notice_to_visible_permanent_state(self):
        script = (
            settings.BASE_DIR / "static" / "js" / "adventure-dashboard.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'document.querySelector("[data-journal-storage-notice]")', script
        )
        self.assertIn('notice.classList.add("is-permanent")', script)
        self.assertIn("}, 3000);", script)
        self.assertNotIn("notice.hidden", script)
        self.assertNotIn("notice.remove()", script)

    def test_public_and_private_adventure_permissions_are_unchanged(self):
        public_response = self.client.get(self.public_adventure.get_absolute_url())
        self.assertEqual(public_response.status_code, 200)
        self.assertContains(public_response, NOTICE_HTML, count=1)
        self.assertEqual(
            self.client.get(self.private_adventure.get_absolute_url()).status_code,
            404,
        )

        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(self.public_adventure.get_absolute_url()).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(self.private_adventure.get_absolute_url()).status_code,
            404,
        )

        self.client.force_login(self.owner)
        private_response = self.client.get(self.private_adventure.get_absolute_url())
        self.assertEqual(private_response.status_code, 200)
        self.assertContains(private_response, NOTICE_HTML, count=1)
