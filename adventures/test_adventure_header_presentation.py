from datetime import date

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from core.models import Adventure, JournalContact, JournalEntry, MemberProfile, Photo


class AdventureHeaderPresentationTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("header-owner", password="test")
        MemberProfile.objects.create(
            user=self.owner,
            callsign="W0HEAD",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.other = users.objects.create_user("header-other", password="test")
        MemberProfile.objects.create(
            user=self.other,
            callsign="W0VIEW",
            callsign_verified=True,
            verification_method=MemberProfile.VerificationMethod.QRZ,
        )
        self.staff = users.objects.create_user(
            "header-staff", password="test", is_staff=True
        )
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Header Presentation Adventure",
            operating_callsign="W0HEAD",
            operating_callsign_url="https://example.com/event?id=346",
            is_public=True,
        )
        JournalEntry.objects.create(
            adventure=self.adventure,
            title="Open Journal",
            is_public=True,
            status=JournalEntry.Status.OPEN,
        )

    def test_header_keeps_calculated_status_without_visibility_controls(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(
            response,
            'class="adventure-status adventure-status-active"',
        )
        self.assertContains(response, "Active")
        self.assertNotContains(response, "adventure-dashboard-state")
        self.assertNotContains(response, "Active / Public")
        self.assertNotContains(response, "Make Private")
        self.assertNotContains(
            response,
            reverse("toggle_adventure_visibility", args=[self.adventure.slug]),
        )

    def test_adventure_page_header_has_requested_placement_and_permissions(self):
        self.client.force_login(self.owner)
        owner = self.client.get(self.adventure.get_absolute_url())
        source = owner.content.decode()
        toolbar = source.split('class="adventure-dashboard-toolbar"', 1)[1].split(
            "</div>", 1
        )[0]
        self.assertLess(toolbar.index("← Back to My Adventures"), toolbar.index("ADVENTURE"))
        self.assertLess(toolbar.index("ADVENTURE"), toolbar.index("Adventure actions"))
        self.assertContains(owner, "Edit Adventure")
        self.assertContains(owner, "+ Add Journal Entry")

        self.client.force_login(self.staff)
        staff = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(staff, 'aria-label="Adventure actions"')
        self.assertContains(staff, "Edit Adventure")
        self.assertEqual(
            self.client.get(
                reverse("edit_adventure", args=[self.adventure.slug])
            ).status_code,
            200,
        )

        self.client.force_login(self.other)
        other = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(other, "ADVENTURE")
        self.assertNotContains(other, 'aria-label="Adventure actions"')
        self.assertNotContains(other, "Edit Adventure")
        self.assertEqual(
            self.client.get(
                reverse("edit_adventure", args=[self.adventure.slug])
            ).status_code,
            403,
        )

    def test_add_journal_entry_uses_shared_orange_button_without_heading_override(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(
            response,
            'class="button-primary adventure-journal-add-action"',
        )

        stylesheet = (
            settings.BASE_DIR / "static" / "css" / "style.css"
        ).read_text(encoding="utf-8")
        self.assertIn(
            ".adventure-dashboard-section-heading a:not(.button-primary)",
            stylesheet,
        )
        self.assertIn(
            ".button-primary{background:var(--ro-color-action-orange);"
            "border:2px solid var(--ro-color-action-orange);color:#fff;",
            stylesheet,
        )
        self.assertIn("--ro-color-action-orange:#b95500;", stylesheet)
        self.assertIn("--ro-color-action-orange-hover:#984600;", stylesheet)

    def test_http_reference_is_a_safe_external_link_for_public_visitors(self):
        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(response, "Event Website or Reference:")
        self.assertContains(
            response,
            '<a href="https://example.com/event?id=346" target="_blank" rel="noopener noreferrer">',
        )

    def test_https_reference_is_visible_to_signed_in_non_owner(self):
        self.client.force_login(self.other)
        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(response, "Event Website or Reference:")
        self.assertContains(response, "https://example.com/event?id=346")
        self.assertNotContains(response, "Edit Adventure")

    def test_http_reference_is_linked(self):
        self.adventure.operating_callsign_url = "http://example.org/reference"
        self.adventure.save(update_fields=["operating_callsign_url"])

        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(
            response,
            '<a href="http://example.org/reference" target="_blank" rel="noopener noreferrer">',
        )

    def test_plain_reference_is_escaped_and_not_linked(self):
        self.adventure.operating_callsign_url = "Field Day <script>alert(1)</script>"
        self.adventure.save(update_fields=["operating_callsign_url"])

        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(response, "Event Website or Reference:")
        self.assertContains(
            response,
            "Field Day &lt;script&gt;alert(1)&lt;/script&gt;",
        )
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertNotContains(response, 'target="_blank"')

    def test_empty_reference_omits_the_complete_row(self):
        self.adventure.operating_callsign_url = "   "
        self.adventure.save(update_fields=["operating_callsign_url"])

        response = self.client.get(self.adventure.get_absolute_url())

        self.assertNotContains(response, "Event Website or Reference:")
        self.assertNotContains(response, "adventure-dashboard-reference")

    def test_journal_notice_and_photos_heading_use_exact_required_copy(self):
        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(
            response,
            "QSO’s and Contacts, Map Locations &amp; Photos are stored in Journals.",
            html=True,
        )
        self.assertNotContains(response, "Status: QSO’s and Contacts")
        self.assertContains(response, "<h2>Photos</h2>", html=True)
        self.assertNotContains(response, "(Photos are stored in Journals)")

    def test_journal_rows_keep_real_links_and_add_safe_row_navigation(self):
        entry = self.adventure.journal_entries.get()
        response = self.client.get(self.adventure.get_absolute_url())
        journal_url = reverse("journal_entry_detail", args=[entry.pk])
        all_journals_url = reverse(
            "adventure_journals", args=[self.adventure.slug]
        )

        self.assertContains(response, f'data-journal-url="{journal_url}"')
        self.assertContains(
            response,
            f'class="adventure-journal-row-title" href="{journal_url}"',
        )
        self.assertContains(response, "adventure-journal-row-chevron")
        self.assertContains(
            response,
            f'class="adventure-dashboard-view-all" href="{all_journals_url}">View All Journals</a>',
        )
        self.assertNotContains(response, ">View Journal</a>")

        source = response.content.decode()
        journal_panel = source.split('<section id="journal-entries"', 1)[1].split(
            "</section>", 1
        )[0]
        column_headings = journal_panel.split('class="adventure-journal-column-headings"', 1)[1].split("</div>", 1)[0]
        heading_row = journal_panel.split('class="adventure-dashboard-section-heading adventure-journals-heading"', 1)[1].split('class="adventure-journal-storage-notice"', 1)[0]
        self.assertIn("View All Journals", heading_row)
        self.assertNotIn("View All Journals", column_headings)
        self.assertLess(column_headings.index("Date"), column_headings.index("Journal Name"))
        self.assertLess(column_headings.index("Journal Name"), column_headings.index("Location"))
        self.assertLess(column_headings.index("Location"), column_headings.index("Photos"))
        self.assertLess(column_headings.index("Photos"), column_headings.index("Contacts"))
        self.assertLess(column_headings.index("Contacts"), column_headings.index("Status"))
        self.assertNotIn("Activity", journal_panel)
        self.assertIn("adventure-journal-row-photos", journal_panel)
        self.assertIn("adventure-journal-row-contacts", journal_panel)
        self.assertNotIn("adventure-journal-row-menu", journal_panel)
        self.assertNotIn("visibility-badge", journal_panel)
        self.assertIn("<h2>Adventure Journals</h2>", journal_panel)

        script = (settings.BASE_DIR / "static" / "js" / "adventure-dashboard.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('event.target.closest("a, button, input, select, textarea, summary, details, form")', script)
        self.assertIn("window.getSelection()", script)

    def test_view_all_journals_has_linked_names_without_redundant_actions(self):
        entry = self.adventure.journal_entries.get()
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("adventure_journals", args=[self.adventure.slug])
        )
        detail_url = reverse("journal_entry_detail", args=[entry.pk])

        self.assertContains(
            response,
            f'class="journal-list-title" href="{detail_url}"',
        )
        self.assertNotContains(response, ">View Journal</a>")
        self.assertNotContains(response, ">Edit</a>")
        self.assertNotContains(response, "journal-list-action-column")
        self.assertNotContains(response, "journal-list-actions")

    def test_journal_rows_show_zero_and_permission_safe_multiple_counts(self):
        empty_entry = self.adventure.journal_entries.get()
        counted_entry = JournalEntry.objects.create(
            adventure=self.adventure,
            title="Counted Journal",
            is_public=True,
            status=JournalEntry.Status.OPEN,
        )
        for index in range(3):
            JournalContact.objects.create(
                journal_entry=counted_entry,
                callsign=f"W1CNT{index}",
                qso_date=date(2026, 8, 16),
                fingerprint=f"counted-contact-{index}",
            )
        for index in range(2):
            Photo.objects.create(
                journal_entry=counted_entry,
                image=f"adventure_photos/count-{index}.jpg",
                moderation_status=Photo.ModerationStatus.APPROVED,
            )
        Photo.objects.create(
            journal_entry=counted_entry,
            image="adventure_photos/restricted-count.jpg",
            moderation_status=Photo.ModerationStatus.REJECTED,
        )

        self.client.force_login(self.owner)
        owner_response = self.client.get(self.adventure.get_absolute_url())
        owner_source = owner_response.content.decode()
        empty_row = owner_source.split(
            f'data-journal-url="{reverse("journal_entry_detail", args=[empty_entry.pk])}">', 1
        )[1].split("</article>", 1)[0]
        counted_owner_row = owner_source.split(
            f'data-journal-url="{reverse("journal_entry_detail", args=[counted_entry.pk])}">', 1
        )[1].split("</article>", 1)[0]
        self.assertIn('adventure-journal-row-photos">0</span>', empty_row)
        self.assertIn('adventure-journal-row-contacts">0</span>', empty_row)
        self.assertIn('adventure-journal-row-photos">3</span>', counted_owner_row)
        self.assertIn('adventure-journal-row-contacts">3</span>', counted_owner_row)

        self.client.force_login(self.other)
        visitor_response = self.client.get(self.adventure.get_absolute_url())
        visitor_source = visitor_response.content.decode()
        counted_visitor_row = visitor_source.split(
            f'data-journal-url="{reverse("journal_entry_detail", args=[counted_entry.pk])}">', 1
        )[1].split("</article>", 1)[0]
        self.assertIn('adventure-journal-row-photos">2</span>', counted_visitor_row)
        self.assertIn('adventure-journal-row-contacts">3</span>', counted_visitor_row)

    def test_individual_journal_actions_and_routes_remain_available(self):
        entry = self.adventure.journal_entries.get()
        self.client.force_login(self.owner)

        journal = self.client.get(reverse("journal_entry_detail", args=[entry.pk]))

        self.assertContains(
            journal,
            reverse("edit_journal_entry", args=[entry.pk]),
        )
        self.assertContains(
            journal,
            reverse("delete_journal_entry", args=[entry.pk]),
        )
        self.assertContains(journal, "Edit Journal")
        self.assertContains(journal, "Delete Journal")

    def test_contact_list_has_visible_scroll_controls_and_thumb(self):
        entry = self.adventure.journal_entries.get()
        JournalContact.objects.create(
            journal_entry=entry,
            qso_date=date(2026, 8, 16),
            callsign="W1SCROLL",
            fingerprint="header-scroll-contact",
        )

        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(response, 'aria-label="Scroll contacts up"')
        self.assertContains(response, 'aria-label="Scroll contacts down"')
        self.assertContains(response, 'aria-label="Contact list scroll position"')
        self.assertContains(response, 'data-scroll-thumb')

    def test_photo_carousel_preserves_cards_and_adds_arrow_controls(self):
        entry = self.adventure.journal_entries.get()
        for index in range(6):
            Photo.objects.create(
                journal_entry=entry,
                image=f"adventure_photos/carousel-{index}.jpg",
                caption=f"Carousel photo {index}",
                moderation_status=Photo.ModerationStatus.APPROVED,
            )

        response = self.client.get(self.adventure.get_absolute_url())

        self.assertContains(response, 'data-photo-carousel')
        self.assertContains(response, 'aria-label="Show previous Adventure photos"')
        self.assertContains(response, 'aria-label="Show next Adventure photos"')
        self.assertContains(response, 'data-carousel-track')
        self.assertContains(response, 'class="journal-photo journal-photo-manage"', count=6)

    def test_redesign_styles_keep_reference_link_standard_and_hide_carousel_scrollbar(self):
        css = (settings.BASE_DIR / "static" / "css" / "style.css").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            ".adventure-dashboard-reference a { color: #0645ad; text-decoration: underline;",
            css,
        )
        self.assertIn(".adventure-photo-strip::-webkit-scrollbar { display: none; }", css)
        self.assertIn("grid-template-columns: 32px minmax(0,1fr) 32px", css)
        self.assertIn("data-journal-url", (settings.BASE_DIR / "templates" / "adventures" / "_journal_entry_list.html").read_text(encoding="utf-8"))

    def test_edit_form_retains_visibility_control_for_owner(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("edit_adventure", args=[self.adventure.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="is_public"')
        self.assertContains(response, "Visible to Everyone")

    def test_non_owner_cannot_open_edit_form(self):
        self.client.force_login(self.other)
        response = self.client.get(
            reverse("edit_adventure", args=[self.adventure.slug])
        )

        self.assertIn(response.status_code, (403, 404))
