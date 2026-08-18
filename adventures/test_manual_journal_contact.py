from datetime import date, datetime, time, timezone as datetime_timezone
import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from adventures.forms import BatchJournalContactForm, JournalContactForm
from adventures.contact_geography import sanitize_qrz_geography, sign_geography
from core.models import Adventure, JournalContact, JournalEntry, MemberProfile
from core.qrz_service import QRZNotFoundError, QRZResult, QRZUnavailableError


class ManualJournalContactTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username="W5OWNER", password="password")
        MemberProfile.objects.create(user=self.owner, callsign="W5OWNER", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)
        self.adventure = Adventure.objects.create(owner=self.owner, title="Portable Day", operating_callsign="W5OWNER", is_public=True)
        self.journal = JournalEntry.objects.create(adventure=self.adventure, title="Morning Session", body="Notes", operating_callsign="W5OWNER", is_public=True)
        self.url = reverse("add_journal_contact", args=[self.journal.pk])

    def batch_row(self, **overrides):
        row = {
            "qso_date": "2026-08-17", "time_on": "22:10", "callsign": "K1ABC",
            "band": "20M", "frequency": "14.250", "mode": "SSB",
            "signal_report": "59", "state": "", "country": "",
            "comment": "",
        }
        row.update(overrides)
        return row

    def batch_row_with_geography(self, *, callsign, grid, latitude=None, longitude=None, **overrides):
        geography = sanitize_qrz_geography(
            grid=grid, latitude=latitude, longitude=longitude
        )
        return self.batch_row(
            callsign=callsign,
            grid_square=geography.grid_square,
            latitude=(
                format(geography.latitude, ".6f")
                if geography.latitude is not None
                else ""
            ),
            longitude=(
                format(geography.longitude, ".6f")
                if geography.longitude is not None
                else ""
            ),
            geography_token=sign_geography(callsign, geography),
            **overrides,
        )

    def test_owner_sees_add_contact_and_saves_unified_contact(self):
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertContains(detail, "Add Contact")
        response = self.client.post(self.url, {
            "qso_date": "2026-08-11", "time_on": "15:04", "callsign": "k1abc",
            "band": "20M", "mode": "SSB", "frequency": "14.250000",
            "signal_report": "59", "comment": "Strong signal",
            "pota_park_reference": "us-1234", "pota_park_name": "Pike Lake",
        })
        self.assertRedirects(response, reverse("journal_entry_detail", args=[self.journal.pk]))
        contact = JournalContact.objects.get()
        self.assertEqual(contact.owner, self.owner)
        self.assertEqual(contact.adventure, self.adventure)
        self.assertEqual(contact.journal_entry, self.journal)
        self.assertEqual(contact.source, JournalContact.Source.MANUAL)
        self.assertEqual(contact.callsign, "K1ABC")
        self.assertEqual(contact.signal_report, "59")
        self.assertEqual(contact.pota_park_reference, "US-1234")

        journal_detail = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertContains(journal_detail, "K1ABC")
        self.assertContains(journal_detail, "Contacts")
        adventure_contacts = self.client.get(reverse("adventure_contacts", args=[self.adventure.slug]))
        self.assertContains(adventure_contacts, "K1ABC")
        my_adventures = self.client.get(reverse("my_adventures"))
        self.assertContains(my_adventures, "<dt>Contacts</dt><dd>1</dd>", html=True)

    def test_empty_journal_always_shows_contact_section_and_actions(self):
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertContains(detail, "QSO’s and Contacts")
        self.assertContains(detail, "0 total")
        self.assertContains(detail, "No Contacts have been added to this Journal yet.")
        self.assertContains(detail, "Add Contact")
        self.assertNotContains(detail, reverse("import_pota_hunter_log") + f"?journal_entry={self.journal.pk}")

    def test_unauthorized_member_cannot_add_contact(self):
        other = get_user_model().objects.create_user(username="N0OTHER", password="password")
        MemberProfile.objects.create(user=other, callsign="N0OTHER", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)
        self.client.force_login(other)
        self.assertNotContains(self.client.get(reverse("journal_entry_detail", args=[self.journal.pk])), "Add Contact")
        self.assertNotContains(
            self.client.get(reverse("journal_entry_detail", args=[self.journal.pk])),
            reverse("import_pota_hunter_log") + f"?journal_entry={self.journal.pk}",
        )
        self.assertEqual(self.client.get(self.url).status_code, 403)
        import_url = reverse("import_pota_hunter_log") + f"?journal_entry={self.journal.pk}"
        self.assertEqual(self.client.get(import_url).status_code, 404)
        self.assertEqual(JournalContact.objects.count(), 0)

    def test_staff_can_use_manual_contact_form(self):
        staff = get_user_model().objects.create_user(username="STAFF", password="password", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_no_session_defaults_to_configured_local_date_and_time(self):
        self.client.force_login(self.owner)
        local_now = datetime(2026, 8, 17, 13, 42, tzinfo=datetime_timezone.utc)
        with patch("adventures.contact_log_views.timezone.localtime", return_value=local_now), patch(
            "adventures.contact_log_views.timezone.localdate", return_value=date(2026, 8, 17)
        ):
            form = self.client.get(self.url).context["form"]
        self.assertEqual(form.initial["qso_date"], date(2026, 8, 17))
        self.assertEqual(form.initial["time_on"], "13:42")
        self.assertNotIn("band", form.initial)
        self.assertNotIn("mode", form.initial)
        self.assertNotIn("frequency", form.initial)

    def test_valid_user_session_values_supply_all_last_used_defaults(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session[f"journal_contact_last_used:{self.owner.pk}"] = {
            "qso_date": "2026-08-10", "time_on": "09:08", "band": "40M",
            "mode": "FT8", "frequency": "7.074",
        }
        session.save()
        form = self.client.get(self.url).context["form"]
        self.assertEqual(form.initial["qso_date"], date(2026, 8, 10))
        self.assertEqual(form.initial["time_on"], time(9, 8))
        self.assertEqual(form.initial["band"], "40M")
        self.assertEqual(form.initial["mode"], "FT8")
        self.assertEqual(form.initial["frequency"], "7.074")
        html = self.client.get(self.url).content.decode()
        self.assertIn('data-field="band" required aria-label="Band"', html)
        self.assertIn('<option value="40M" selected>', html)
        self.assertIn('data-field="frequency" maxlength="7" required inputmode="decimal" pattern="[0-9]+(?:\\.[0-9]+)?" value="7.074"', html)
        self.assertIn('<option value="FT8" selected>', html)

    def test_invalid_or_other_user_session_values_fall_back_safely(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session[f"journal_contact_last_used:{self.owner.pk}"] = {
            "qso_date": "not-a-date", "time_on": "28:91", "band": "obsolete",
            "mode": "DATA", "frequency": "14.25000",
        }
        session["journal_contact_last_used:999999"] = {
            "qso_date": "2000-01-01", "time_on": "01:01", "band": "2M",
            "mode": "CW", "frequency": "144.200",
        }
        session.save()
        with patch("adventures.contact_log_views.timezone.localtime", return_value=datetime(2026, 8, 17, 14, 5, tzinfo=datetime_timezone.utc)), patch(
            "adventures.contact_log_views.timezone.localdate", return_value=date(2026, 8, 17)
        ):
            form = self.client.get(self.url).context["form"]
        self.assertEqual(form.initial["qso_date"], date(2026, 8, 17))
        self.assertEqual(form.initial["time_on"], "14:05")
        for field in ("band", "mode", "frequency"):
            self.assertNotIn(field, form.initial)

    def test_last_used_session_updates_only_after_successful_save(self):
        self.client.force_login(self.owner)
        key = f"journal_contact_last_used:{self.owner.pk}"
        invalid = self.client.post(self.url, {"qso_date": "2026-08-12"})
        self.assertEqual(invalid.status_code, 200)
        self.assertNotIn(key, self.client.session)
        response = self.client.post(self.url, {
            "qso_date": "2026-08-12", "time_on": "11:22", "callsign": "n0new",
            "band": "2M", "mode": "CW", "frequency": "144.200000",
            "signal_report": "57", "comment": "Saved",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[key], {
            "qso_date": "2026-08-12", "time_on": "11:22", "band": "2M",
            "mode": "CW", "frequency": "144.200000",
        })

    def test_required_fields_band_mode_options_and_disabled_headings(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        form = response.context["form"]
        for name in ("qso_date", "time_on", "callsign", "band", "mode", "frequency"):
            self.assertTrue(form.fields[name].required)
        invalid = self.client.post(self.url, {})
        self.assertEqual(invalid.status_code, 200)
        for name in ("qso_date", "time_on", "callsign", "band", "mode", "frequency"):
            self.assertIn(name, invalid.context["form"].errors)
        self.assertEqual([label for value, label in form.fields["band"].choices], [
            "Band", "1.25 Meters", "2 Meters", "6 Meters", "10 Meters", "12 Meters",
            "15 Meters", "17 Meters", "20 Meters", "30 Meters", "40 Meters",
            "60 Meters", "80 Meters", "160 Meters", "630 Meters", "2,200 Meters",
        ])
        self.assertEqual([value for value, label in form.fields["mode"].choices], [
            "", "AM", "FM", "SSB", "CW", "FT8", "FT4", "JS8", "RTTY",
            "PSK31", "APRS", "DMR", "D-STAR", "FUSION",
        ])

    def test_signal_report_accepts_two_digits_and_rejects_long_or_non_digit_values(self):
        base = {"qso_date": "2026-08-12", "time_on": "11:22", "callsign": "K1ABC", "band": "20M", "mode": "SSB", "frequency": "14.250000"}
        valid = JournalContactForm({**base, "signal_report": "59"})
        self.assertTrue(valid.is_valid(), valid.errors)
        for value in ("599", "5A"):
            invalid = JournalContactForm({**base, "signal_report": value})
            self.assertFalse(invalid.is_valid())
            self.assertIn("signal_report", invalid.errors)
        self.assertEqual(valid.fields["signal_report"].widget.attrs["maxlength"], "2")

    def test_batch_modes_and_compact_field_lengths_are_enforced_server_side(self):
        expected_modes = [
            "AM", "FM", "SSB", "CW", "FT8", "FT4", "JS8", "RTTY", "PSK31",
            "APRS", "DMR", "D-STAR", "FUSION",
        ]
        self.assertEqual([value for value, label in BatchJournalContactForm.base_fields["mode"].choices if value], expected_modes)
        valid = BatchJournalContactForm(self.batch_row(frequency="144.200", signal_report="59", state="MN"))
        self.assertTrue(valid.is_valid(), valid.errors)
        invalid_values = {
            "frequency": "14.25000",
            "signal_report": "599",
            "state": "MIN",
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                invalid = BatchJournalContactForm(self.batch_row(**{field: value}))
                self.assertFalse(invalid.is_valid())
                self.assertIn(field, invalid.errors)

    def test_batch_table_matches_approved_order_controls_and_headerless_shell(self):
        self.client.force_login(self.owner)
        html = self.client.get(self.url).content.decode()
        positions = [html.index(f"<th>{name}</th>") for name in (
            "Date", "Time", "Callsign", "Band", "Frequency", "Mode", "Signal",
            "State", "Country", "Notes",
        )]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(html.count("Save All Contacts"), 2)
        self.assertIn("Discard Unsaved", html)
        self.assertNotIn('class="site-header"', html)
        self.assertNotIn("Radio Outdoors home", html)
        css = (Path(settings.BASE_DIR) / "static" / "css" / "style.css").read_text(encoding="utf-8")
        self.assertIn('url("../images/contacts-radio-telescope-background.png")', css)
        self.assertIn("background: rgba(250, 247, 238, 0.76)", css)
        self.assertIn("width: min(1420px, 100%)", css)
        self.assertIn("min-width: 930px", css)
        self.assertIn("table-layout: fixed", css)

    @patch("adventures.contact_log_views.lookup_callsign")
    def test_qrz_lookup_populates_state_and_country(self, lookup):
        lookup.return_value = QRZResult(callsign="W0ABC", state="CO", country="United States")
        self.client.force_login(self.owner)
        response = self.client.get(reverse("qrz_contact_lookup", args=[self.journal.pk]), {"callsign": "w0abc"})
        self.assertEqual(response.json(), {
            "state": "CO", "country": "United States", "grid_square": "",
            "latitude": None, "longitude": None, "geography_token": "",
        })
        lookup.assert_called_once_with("W0ABC")

    @patch("adventures.contact_log_views.lookup_callsign")
    def test_qrz_lookup_returns_direct_coordinates_and_grid(self, lookup):
        lookup.return_value = QRZResult(
            callsign="W0ABC", state="MN", country="United States",
            grid="en35im", latitude="45.123456", longitude="-93.654321",
        )
        self.client.force_login(self.owner)
        payload = self.client.get(
            reverse("qrz_contact_lookup", args=[self.journal.pk]),
            {"callsign": "w0abc"},
        ).json()
        self.assertEqual(payload["grid_square"], "EN35IM")
        self.assertEqual(payload["latitude"], 45.123456)
        self.assertEqual(payload["longitude"], -93.654321)
        self.assertTrue(payload["geography_token"])

    @patch("adventures.contact_log_views.lookup_callsign")
    def test_qrz_grid_without_coordinates_is_converted_to_center(self, lookup):
        lookup.return_value = QRZResult(
            callsign="W0GRID", grid="en35im", country="United States"
        )
        self.client.force_login(self.owner)
        payload = self.client.get(
            reverse("qrz_contact_lookup", args=[self.journal.pk]),
            {"callsign": "W0GRID"},
        ).json()
        self.assertEqual(payload["grid_square"], "EN35IM")
        self.assertAlmostEqual(payload["latitude"], 45.520833, places=6)
        self.assertAlmostEqual(payload["longitude"], -93.291667, places=6)
        self.assertTrue(payload["geography_token"])

    @patch("adventures.contact_log_views.lookup_callsign")
    def test_qrz_lookup_with_only_country_leaves_state_empty(self, lookup):
        lookup.return_value = QRZResult(callsign="PA7ZZ", country="Netherlands")
        self.client.force_login(self.owner)
        response = self.client.get(reverse("qrz_contact_lookup", args=[self.journal.pk]), {"callsign": "PA7ZZ"})
        self.assertEqual(response.json()["state"], "")
        self.assertEqual(response.json()["country"], "Netherlands")

    @patch("adventures.contact_log_views.lookup_callsign")
    def test_qrz_lookup_with_only_state_leaves_country_empty(self, lookup):
        lookup.return_value = QRZResult(callsign="W0STATE", state="MN")
        self.client.force_login(self.owner)
        response = self.client.get(reverse("qrz_contact_lookup", args=[self.journal.pk]), {"callsign": "W0STATE"})
        self.assertEqual(response.json()["state"], "MN")
        self.assertEqual(response.json()["country"], "")

    @patch("adventures.contact_log_views.lookup_callsign")
    def test_qrz_lookup_with_no_geography_returns_empty_fields(self, lookup):
        lookup.return_value = QRZResult(callsign="K1EMPTY")
        self.client.force_login(self.owner)
        response = self.client.get(reverse("qrz_contact_lookup", args=[self.journal.pk]), {"callsign": "K1EMPTY"})
        self.assertEqual(response.json(), {
            "state": "", "country": "", "grid_square": "",
            "latitude": None, "longitude": None, "geography_token": "",
        })

    def test_qrz_not_found_or_network_failure_is_empty_and_does_not_block_batch(self):
        self.client.force_login(self.owner)
        lookup_url = reverse("qrz_contact_lookup", args=[self.journal.pk])
        for error in (QRZNotFoundError("missing"), QRZUnavailableError("offline")):
            with self.subTest(error=type(error).__name__), patch("adventures.contact_log_views.lookup_callsign", side_effect=error):
                self.assertEqual(self.client.get(lookup_url, {"callsign": "K1FAIL"}).json(), {
                    "state": "", "country": "", "grid_square": "",
                    "latitude": None, "longitude": None, "geography_token": "",
                })
        rows = [self.batch_row(callsign="K1FAIL", comment="Manual entry remains available")]
        response = self.client.post(self.url, {"contacts_json": json.dumps(rows)})
        self.assertRedirects(response, reverse("journal_entry_detail", args=[self.journal.pk]))
        self.assertTrue(JournalContact.objects.filter(callsign="K1FAIL", state="", country="").exists())

    def test_batch_javascript_adds_on_enter_keeps_rows_editable_and_guards_lookup_races(self):
        source = (Path(settings.BASE_DIR) / "static" / "js" / "add-contact-batch.js").read_text(encoding="utf-8")
        self.assertIn('event.key === "Enter"', source)
        self.assertIn("tbody.appendChild(makeUnsavedRow(values))", source)
        self.assertIn('row.dataset.unsavedRow = "true"', source)
        self.assertIn("cell.appendChild(input)", source)
        self.assertIn("row.dataset.lookupToken !== token", source)
        self.assertIn('callsign.addEventListener("input"', source)
        self.assertIn("clearQrzGeography()", source)
        self.assertIn("row.dataset.gridSquare = result.grid_square", source)
        self.assertIn("row.dataset.geographyToken = result.geography_token", source)
        self.assertIn('row.dataset.stateManual = "1"', source)
        self.assertIn('state.value = result.state || ""', source)
        self.assertIn('country.value = result.country || ""', source)
        self.assertIn('const defaultFieldNames = ["qso_date", "time_on", "band", "frequency", "mode"]', source)
        self.assertNotIn('data-field="power"', source)
        self.assertIn("clearActiveRow(values)", source)
        self.assertIn("window.confirm(\"Discard all unsaved Contacts? This cannot be undone.\")", source)
        self.assertIn("input.classList.add(\"add-contacts-field-error\")", source)

    def test_batch_rejects_unverified_or_invalid_client_coordinates(self):
        unverified = BatchJournalContactForm(self.batch_row(
            grid_square="EN35IM", latitude="45.520833", longitude="-93.291667"
        ))
        self.assertFalse(unverified.is_valid())
        self.assertIn("__all__", unverified.errors)
        for field, value in (("latitude", "91"), ("longitude", "-181")):
            with self.subTest(field=field):
                invalid = self.batch_row_with_geography(
                    callsign="K1BAD", grid="EN35IM"
                )
                invalid[field] = value
                form = BatchJournalContactForm(invalid)
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_save_all_persists_independent_signed_geography_for_each_row(self):
        self.client.force_login(self.owner)
        rows = [
            self.batch_row_with_geography(
                callsign="KF0DEK", grid="EN35IM", time_on="22:31"
            ),
            self.batch_row_with_geography(
                callsign="N2JIM", grid="EN35HG", time_on="22:32"
            ),
        ]
        response = self.client.post(
            self.url, {"contacts_json": json.dumps(rows)}
        )
        self.assertRedirects(
            response, reverse("journal_entry_detail", args=[self.journal.pk])
        )
        contacts = list(JournalContact.objects.order_by("time_on"))
        self.assertEqual(
            [contact.grid_square for contact in contacts], ["EN35IM", "EN35HG"]
        )
        self.assertNotEqual(contacts[0].longitude, contacts[1].longitude)
        self.assertTrue(all(contact.latitude is not None for contact in contacts))

    def test_save_all_persists_editable_batch_and_journal_association(self):
        self.client.force_login(self.owner)
        rows = [
            self.batch_row(time_on="22:01", callsign="w0abc", state="CO", country="United States", comment="Great sigs"),
            self.batch_row(time_on="22:02", callsign="pa7zz", band="40M", frequency="7.074", mode="FT8", signal_report="55", country="Netherlands", comment="QSL"),
        ]
        response = self.client.post(self.url, {"contacts_json": json.dumps(rows)})
        self.assertRedirects(response, reverse("journal_entry_detail", args=[self.journal.pk]))
        contacts = list(JournalContact.objects.order_by("time_on"))
        self.assertEqual([contact.callsign for contact in contacts], ["W0ABC", "PA7ZZ"])
        self.assertTrue(all(contact.journal_entry == self.journal for contact in contacts))
        self.assertEqual((contacts[0].state, contacts[0].country, contacts[0].comment), ("CO", "United States", "Great sigs"))
        self.assertEqual((contacts[1].band, str(contacts[1].frequency), contacts[1].mode), ("40M", "7.074000", "FT8"))
        self.assertEqual(self.client.session[f"journal_contact_last_used:{self.owner.pk}"], {
            "qso_date": "2026-08-17", "time_on": "22:02", "band": "40M",
            "frequency": "7.074", "mode": "FT8",
        })

    def test_batch_duplicate_and_required_rules_are_enforced_atomically(self):
        self.client.force_login(self.owner)
        duplicate = self.batch_row(time_on="22:01", callsign="W0ABC")
        response = self.client.post(self.url, {"contacts_json": json.dumps([duplicate, duplicate])})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "duplicates another Contact")
        self.assertEqual(JournalContact.objects.count(), 0)
        response = self.client.post(self.url, {"contacts_json": json.dumps([{**duplicate, "callsign": ""}])})
        self.assertContains(response, "This field is required")
        self.assertEqual(JournalContact.objects.count(), 0)

    def test_invalid_row_reporting_names_fields_and_preserves_all_unsaved_rows(self):
        self.client.force_login(self.owner)
        rows = [
            self.batch_row(callsign="K1GOOD"),
            self.batch_row(time_on="22:11", callsign="K1BAD", frequency="14.25000"),
        ]
        response = self.client.post(self.url, {"contacts_json": json.dumps(rows)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Row 2, Frequency")
        self.assertContains(response, "K1GOOD")
        self.assertContains(response, "K1BAD")
        self.assertEqual(response.context["batch_rows"], rows)
        self.assertEqual(JournalContact.objects.count(), 0)

    def test_batch_rejects_duplicate_of_existing_journal_contact(self):
        self.client.force_login(self.owner)
        JournalContact.objects.create(
            journal_entry=self.journal, owner=self.owner, adventure=self.adventure,
            qso_date="2026-08-17", time_on="22:01", callsign="W0ABC",
            fingerprint="existing-manual-contact", source=JournalContact.Source.MANUAL,
        )
        row = self.batch_row(time_on="22:01", callsign="w0abc", signal_report="")
        response = self.client.post(self.url, {"contacts_json": json.dumps([row])})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "duplicates another Contact")
        self.assertEqual(JournalContact.objects.count(), 1)

    def test_nearly_full_warning_precedes_batch_limit(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.context["batch_warning_at"], 45)
        self.assertEqual(response.context["batch_limit"], 50)
        self.assertContains(response, "Table nearly full")

    def test_non_owner_cannot_post_batch_or_use_contact_qrz_lookup(self):
        other = get_user_model().objects.create_user(username="N1BLOCK", password="password")
        MemberProfile.objects.create(user=other, callsign="N1BLOCK", callsign_verified=True, verification_method=MemberProfile.VerificationMethod.QRZ)
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {"contacts_json": json.dumps([self.batch_row()])}).status_code, 403)
        self.assertEqual(self.client.get(reverse("qrz_contact_lookup", args=[self.journal.pk]), {"callsign": "K1ABC"}).status_code, 403)
        self.assertEqual(JournalContact.objects.count(), 0)

    def test_existing_import_and_contact_map_routes_remain_available(self):
        self.client.force_login(self.owner)
        import_response = self.client.get(reverse("import_pota_hunter_log") + f"?journal_entry={self.journal.pk}")
        map_response = self.client.get(reverse("journal_contact_map", args=[self.journal.pk]))
        self.assertEqual(import_response.status_code, 200)
        self.assertEqual(map_response.status_code, 200)
