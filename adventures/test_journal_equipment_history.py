from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from core.models import Adventure, JournalEntry, Location, MemberProfile

from .forms import JournalEntryForm


class JournalEquipmentHistoryTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user("equipment-owner", password="test")
        self.other = users.objects.create_user("equipment-other", password="test")
        for user, callsign in (
            (self.owner, "W5EQUIP"),
            (self.other, "N0EQUIP"),
        ):
            MemberProfile.objects.create(
                user=user,
                callsign=callsign,
                callsign_verified=True,
                verification_method=MemberProfile.VerificationMethod.QRZ,
            )
        self.adventure = Adventure.objects.create(
            owner=self.owner,
            title="Equipment History Adventure",
            operating_callsign="W5EQUIP",
        )
        self.location = Location.objects.create(
            name="Equipment Park",
            created_by=self.owner,
            latitude="44.100000",
            longitude="-93.100000",
        )

    def journal(self, title, when, *, radio="", antenna="", adventure=None):
        return JournalEntry.objects.create(
            adventure=adventure or self.adventure,
            location=self.location if adventure is None else None,
            title=title,
            body="Equipment notes",
            entry_at=when,
            operating_callsign=(adventure or self.adventure).operating_callsign,
            radio=radio,
            antenna=antenna,
        )

    def form_data(self, *, radio, antenna, title="Current Journal"):
        return {
            "entry_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "status": JournalEntry.Status.OPEN,
            "is_public": "on",
            "location": str(self.location.pk),
            "location_name": self.location.name,
            "location_source": "existing",
            "latitude": str(self.location.latitude),
            "longitude": str(self.location.longitude),
            "operating_callsign": "W5EQUIP",
            "title": title,
            "body": "Current equipment notes",
            "radio": radio,
            "antenna": antenna,
        }

    def test_defaults_are_independent_and_history_is_distinct_newest_first(self):
        now = timezone.now()
        self.journal(
            "Old",
            now - timedelta(days=3),
            radio="Icom IC-705",
            antenna="Old wire dipole",
        )
        self.journal(
            "Middle",
            now - timedelta(days=2),
            radio="Yaesu FT-710",
            antenna="",
        )
        self.journal(
            "Newer case duplicate",
            now - timedelta(days=1),
            radio="yaesu ft-710",
            antenna="21-foot telescoping vertical",
        )
        self.journal("Newest radio blank", now, radio="", antenna="")

        form = JournalEntryForm(adventure=self.adventure, user=self.owner)

        self.assertEqual(form.initial["radio"], "yaesu ft-710")
        self.assertEqual(form.initial["antenna"], "21-foot telescoping vertical")
        self.assertEqual(
            form.fields["radio"].history_options,
            ["yaesu ft-710", "Icom IC-705"],
        )
        self.assertEqual(
            form.fields["antenna"].history_options,
            ["21-foot telescoping vertical", "Old wire dipole"],
        )
        self.assertEqual(form.fields["radio"].max_length, 150)
        self.assertEqual(form.fields["antenna"].max_length, 150)

    def test_rendered_member_history_spans_adventures_without_replacing_current(self):
        second_adventure = Adventure.objects.create(
            owner=self.owner,
            title="Second Equipment Adventure",
            operating_callsign="W5EQUIP",
        )
        now = timezone.now()
        oldest = self.journal(
            "Oldest",
            now - timedelta(days=5),
            radio="Yaesu FT-897D",
            antenna="Wire dipole",
        )
        self.journal(
            "Other Adventure",
            now - timedelta(days=4),
            radio="Yaesu FT-891",
            antenna="Vertical",
            adventure=second_adventure,
        )
        self.journal(
            "Newer spelling",
            now - timedelta(days=3),
            radio="YAESU FT-891",
            antenna="vertical",
        )
        self.journal(
            "Newest equipment",
            now - timedelta(days=2),
            radio="Yaesu FT-710",
            antenna="Three-element beam",
            adventure=second_adventure,
        )
        self.journal("Blank equipment", now - timedelta(days=1))
        other_adventure = Adventure.objects.create(
            owner=self.other,
            title="Other Member Equipment",
            operating_callsign="N0EQUIP",
        )
        self.journal(
            "Private other-member values",
            now,
            radio="Other Member Radio",
            antenna="Other Member Antenna",
            adventure=other_adventure,
        )

        self.client.force_login(self.owner)
        add_response = self.client.get(
            reverse("add_journal_entry", args=[self.adventure.slug])
        )
        edit_response = self.client.get(
            reverse("edit_journal_entry", args=[oldest.pk])
        )

        expected_radios = ["Yaesu FT-710", "YAESU FT-891", "Yaesu FT-897D"]
        expected_antennas = ["Three-element beam", "vertical", "Wire dipole"]
        for response in (add_response, edit_response):
            html = response.content.decode()
            for value in expected_radios + expected_antennas:
                self.assertContains(response, f'<option value="{value}">{value}</option>')
            self.assertNotContains(response, "Yaesu FT-891</option>")
            self.assertNotContains(response, "Other Member Radio")
            self.assertNotContains(response, "Other Member Antenna")
            radio_positions = [html.index(f'<option value="{value}">') for value in expected_radios]
            antenna_positions = [html.index(f'<option value="{value}">') for value in expected_antennas]
            self.assertEqual(radio_positions, sorted(radio_positions))
            self.assertEqual(antenna_positions, sorted(antenna_positions))

        self.assertContains(add_response, 'name="radio" value="Yaesu FT-710"')
        self.assertContains(
            add_response,
            'name="antenna" value="Three-element beam"',
        )
        self.assertContains(edit_response, 'name="radio" value="Yaesu FT-897D"')
        self.assertContains(edit_response, 'name="antenna" value="Wire dipole"')

    def test_edit_history_includes_current_value_when_photo_collection_is_excluded(self):
        photo_collection = self.journal(
            "System photo collection",
            timezone.now(),
            radio="Current excluded Radio",
            antenna="Current excluded Antenna",
        )
        photo_collection.is_adventure_photo_collection = True
        photo_collection.save(update_fields=["is_adventure_photo_collection"])

        form = JournalEntryForm(
            instance=photo_collection,
            adventure=self.adventure,
            user=self.owner,
        )

        self.assertEqual(
            form.fields["radio"].history_options,
            ["Current excluded Radio"],
        )
        self.assertEqual(
            form.fields["antenna"].history_options,
            ["Current excluded Antenna"],
        )

    def test_another_members_history_is_never_exposed(self):
        other_adventure = Adventure.objects.create(
            owner=self.other,
            title="Private Equipment",
            operating_callsign="N0EQUIP",
            is_public=False,
        )
        self.journal(
            "Other private Journal",
            timezone.now(),
            radio="Secret Other Radio",
            antenna="Secret Other Antenna",
            adventure=other_adventure,
        )
        self.journal(
            "Owner Journal",
            timezone.now() - timedelta(minutes=1),
            radio="Owner Radio",
            antenna="Owner Antenna",
        )

        form = JournalEntryForm(adventure=self.adventure, user=self.owner)

        self.assertEqual(form.fields["radio"].history_options, ["Owner Radio"])
        self.assertEqual(form.fields["antenna"].history_options, ["Owner Antenna"])

    def test_member_with_no_history_receives_blank_editable_fields(self):
        form = JournalEntryForm(adventure=self.adventure, user=self.owner)

        self.assertEqual(form.initial.get("radio", ""), "")
        self.assertEqual(form.initial.get("antenna", ""), "")
        self.assertEqual(form.fields["radio"].history_options, [])
        self.assertEqual(form.fields["antenna"].history_options, [])
        self.assertEqual(form.fields["radio"].widget.input_type, "text")
        self.assertEqual(form.fields["antenna"].widget.input_type, "text")

    def test_existing_selected_edited_and_new_text_can_be_saved(self):
        historical = self.journal(
            "Historical",
            timezone.now() - timedelta(days=1),
            radio="Yaesu FT-710",
            antenna="21-foot telescoping vertical",
        )
        selected_form = JournalEntryForm(
            self.form_data(
                radio="Yaesu FT-710",
                antenna="21-foot telescoping vertical",
                title="Selected",
            ),
            adventure=self.adventure,
            user=self.owner,
        )
        self.assertTrue(selected_form.is_valid(), selected_form.errors)
        selected = selected_form.save(commit=False)
        selected.adventure = self.adventure
        selected.location = self.location
        selected.save()

        edited_form = JournalEntryForm(
            self.form_data(
                radio="Yaesu FT-710 AESS",
                antenna="21-foot telescoping vertical with loading coil",
                title="Edited",
            ),
            instance=selected,
            adventure=self.adventure,
            user=self.owner,
        )
        self.assertTrue(edited_form.is_valid(), edited_form.errors)
        edited_form.save()

        new_form = JournalEntryForm(
            self.form_data(
                radio="Elecraft KX3",
                antenna="End-fed half wave",
                title="New",
            ),
            adventure=self.adventure,
            user=self.owner,
        )
        self.assertTrue(new_form.is_valid(), new_form.errors)
        new_entry = new_form.save(commit=False)
        new_entry.adventure = self.adventure
        new_entry.location = self.location
        new_entry.save()

        historical.refresh_from_db()
        selected.refresh_from_db()
        self.assertEqual(historical.radio, "Yaesu FT-710")
        self.assertEqual(historical.antenna, "21-foot telescoping vertical")
        self.assertEqual(selected.radio, "Yaesu FT-710 AESS")
        self.assertEqual(
            selected.antenna,
            "21-foot telescoping vertical with loading coil",
        )
        future = JournalEntryForm(adventure=self.adventure, user=self.owner)
        self.assertIn("Elecraft KX3", future.fields["radio"].history_options)
        self.assertIn("End-fed half wave", future.fields["antenna"].history_options)

    def test_edit_preserves_saved_values_and_permissions(self):
        older = self.journal(
            "Older",
            timezone.now() - timedelta(days=1),
            radio="Older Radio",
            antenna="Older Antenna",
        )
        current = self.journal(
            "Current",
            timezone.now(),
            radio="Current Radio",
            antenna="Current Antenna",
        )
        form = JournalEntryForm(
            instance=older, adventure=self.adventure, user=self.owner
        )
        self.assertEqual(form["radio"].value(), "Older Radio")
        self.assertEqual(form["antenna"].value(), "Older Antenna")

        self.client.force_login(self.owner)
        response = self.client.get(reverse("add_journal_entry", args=[self.adventure.slug]))
        self.assertContains(response, 'id="id_radio-history"')
        self.assertContains(response, 'data-equipment-history-target="id_radio"')
        self.assertContains(response, 'id="id_antenna-history"')
        self.assertContains(response, 'data-equipment-history-target="id_antenna"')
        self.assertContains(response, 'value="Current Radio"', count=2)
        self.assertContains(response, 'value="Current Antenna"', count=2)
        self.assertContains(response, "Current Radio")
        self.assertContains(response, "Current Antenna")

        response = self.client.get(reverse("edit_journal_entry", args=[older.pk]))
        self.assertContains(response, 'value="Older Radio"', count=2)
        self.assertContains(response, 'value="Older Antenna"', count=2)
        self.assertContains(response, '<option value="Current Radio">Current Radio</option>')
        self.assertContains(
            response,
            '<option value="Current Antenna">Current Antenna</option>',
        )

        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse("edit_journal_entry", args=[current.pk])).status_code,
            403,
        )

    def test_prefixed_forms_render_unique_matching_history_targets(self):
        self.journal(
            "History",
            timezone.now(),
            radio="Prefixed Radio",
            antenna="Prefixed Antenna",
        )
        first = JournalEntryForm(
            adventure=self.adventure, user=self.owner, prefix="journal-0"
        )
        second = JournalEntryForm(
            adventure=self.adventure, user=self.owner, prefix="journal-1"
        )

        first_html = render_to_string(
            "adventures/_journal_entry_fields.html",
            {"form": first, "journal_location_choices": [], "journal_map_defaults": {}},
        )
        second_html = render_to_string(
            "adventures/_journal_entry_fields.html",
            {"form": second, "journal_location_choices": [], "journal_map_defaults": {}},
        )
        combined = first_html + second_html

        for prefix in ("journal-0", "journal-1"):
            radio_id = f"id_{prefix}-radio"
            antenna_id = f"id_{prefix}-antenna"
            self.assertEqual(combined.count(f'id="{radio_id}"'), 1)
            self.assertEqual(combined.count(f'id="{radio_id}-history"'), 1)
            self.assertEqual(
                combined.count(f'data-equipment-history-target="{radio_id}"'), 1
            )
            self.assertEqual(combined.count(f'id="{antenna_id}"'), 1)
            self.assertEqual(combined.count(f'id="{antenna_id}-history"'), 1)
            self.assertEqual(
                combined.count(f'data-equipment-history-target="{antenna_id}"'), 1
            )

    def test_modified_history_value_submitted_through_add_page_is_saved(self):
        self.journal(
            "History",
            timezone.now() - timedelta(days=1),
            radio="Yaesu FT-710",
            antenna="21-foot telescoping vertical",
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("add_journal_entry", args=[self.adventure.slug]),
            self.form_data(
                radio="Yaesu FT-710 AESS",
                antenna="21-foot telescoping vertical with loading coil",
                title="Browser-style submission",
            ),
        )

        self.assertEqual(response.status_code, 302)
        saved = JournalEntry.objects.get(title="Browser-style submission")
        self.assertEqual(saved.radio, "Yaesu FT-710 AESS")
        self.assertEqual(
            saved.antenna,
            "21-foot telescoping vertical with loading coil",
        )
