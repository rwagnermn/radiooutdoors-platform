from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import (
    Adventure,
    JournalEntry,
    Location,
    PotaActivationImport,
    PotaImportBatch,
    PotaTestResetAudit,
)
from .pota_test_reset import PotaResetResult, build_reset_preview, execute_reset


@override_settings(DEBUG=True)
class PotaResetToolTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("W5RESET", password="password")
        self.staff = get_user_model().objects.create_user("STAFF", password="password", is_staff=True)

    def make_import(self, *, manual_content=False):
        location = Location.objects.create(
            name="Imported Park", reference_code="US-1234", created_by=self.user,
            description="Created from POTA historical import. Pin supplied.",
            latitude="46.1", longitude="-92.6",
        )
        adventure = Adventure.objects.create(owner=self.user, title="Imported Adventure", location=location)
        batch = PotaImportBatch.objects.create(owner=self.user)
        audit = PotaActivationImport.objects.create(
            adventure=adventure, batch=batch, activation_date="2025-01-01",
            callsign="W5RESET", park_reference="US-1234", park_name="Imported Park",
            entity="US-MN", fingerprint="b" * 64, location_resolution="existing",
        )
        if manual_content:
            JournalEntry.objects.create(adventure=adventure, title="Manual notes", body="Keep this")
        return adventure, location, batch, audit

    def test_default_command_is_dry_run_and_changes_nothing(self):
        adventure, _, batch, _ = self.make_import()
        output = StringIO()
        call_command("reset_pota_import_test_data", "--no-input", stdout=output)
        self.assertIn("Dry-run only", output.getvalue())
        self.assertTrue(Adventure.objects.filter(pk=adventure.pk).exists())
        self.assertTrue(PotaImportBatch.objects.filter(pk=batch.pk).exists())

    @patch("core.pota_test_reset.create_database_backup", return_value="test-backup.sqlite3")
    def test_execute_removes_only_provenance_records_and_fingerprints(self, backup):
        imported, imported_location, _, _ = self.make_import()
        manual_location = Location.objects.create(name="Manual Park", reference_code="US-9999")
        manual = Adventure.objects.create(owner=self.user, title="POTA-looking manual title", location=manual_location)
        output = StringIO()
        call_command("reset_pota_import_test_data", "--execute", "--no-input", stdout=output)
        self.assertFalse(Adventure.objects.filter(pk=imported.pk).exists())
        self.assertFalse(Location.objects.filter(pk=imported_location.pk).exists())
        self.assertTrue(Adventure.objects.filter(pk=manual.pk).exists())
        self.assertTrue(Location.objects.filter(pk=manual_location.pk).exists())
        self.assertEqual(PotaActivationImport.objects.count(), 0)
        self.assertEqual(PotaImportBatch.objects.count(), 0)
        self.assertTrue(PotaTestResetAudit.objects.get().succeeded)
        backup.assert_called_once()

    @patch("core.pota_test_reset.create_database_backup", side_effect=OSError("backup failed"))
    def test_backup_failure_prevents_deletion(self, backup):
        adventure, _, _, _ = self.make_import()
        with self.assertRaises(CommandError):
            call_command("reset_pota_import_test_data", "--execute", "--no-input")
        self.assertTrue(Adventure.objects.filter(pk=adventure.pk).exists())
        self.assertFalse(PotaTestResetAudit.objects.get().succeeded)

    @patch("builtins.input", return_value="not the phrase")
    @patch("core.management.commands.reset_pota_import_test_data.assert_development_database")
    def test_execute_requires_exact_interactive_confirmation(self, environment_check, entered):
        adventure, _, _, _ = self.make_import()
        with self.assertRaises(CommandError):
            call_command("reset_pota_import_test_data", "--execute")
        self.assertTrue(Adventure.objects.filter(pk=adventure.pk).exists())

    @patch("core.pota_test_reset.create_database_backup", return_value="test-backup.sqlite3")
    @patch("core.pota_test_reset.PotaTestResetAudit.objects.create", side_effect=RuntimeError("audit write failed"))
    def test_transaction_rolls_back_on_failure(self, audit_create, backup):
        adventure, location, batch, _ = self.make_import()
        with self.assertRaises(RuntimeError):
            execute_reset(allow_test_database=True)
        self.assertTrue(Adventure.objects.filter(pk=adventure.pk).exists())
        self.assertTrue(Location.objects.filter(pk=location.pk).exists())
        self.assertTrue(PotaImportBatch.objects.filter(pk=batch.pk).exists())

    @patch("core.pota_test_reset.create_database_backup", return_value="test-backup.sqlite3")
    def test_manual_content_blocks_affected_import(self, backup):
        adventure, location, batch, _ = self.make_import(manual_content=True)
        result = execute_reset(allow_test_database=True)
        self.assertTrue(Adventure.objects.filter(pk=adventure.pk).exists())
        self.assertTrue(Location.objects.filter(pk=location.pk).exists())
        self.assertTrue(PotaImportBatch.objects.filter(pk=batch.pk).exists())
        self.assertEqual(result.retained["adventures"], 1)
        self.assertEqual(len(result.blocked), 1)

    @patch("core.pota_test_reset.create_database_backup", return_value="test-backup.sqlite3")
    def test_shared_import_location_is_retained(self, backup):
        imported, location, _, _ = self.make_import()
        manual = Adventure.objects.create(owner=self.user, title="Manual Adventure", location=location)
        execute_reset(allow_test_database=True)
        self.assertFalse(Adventure.objects.filter(pk=imported.pk).exists())
        self.assertTrue(Adventure.objects.filter(pk=manual.pk).exists())
        self.assertTrue(Location.objects.filter(pk=location.pk).exists())

    @override_settings(DEBUG=False)
    def test_execute_and_staff_page_are_disabled_in_production(self):
        with self.assertRaises(CommandError):
            call_command("reset_pota_import_test_data", "--execute", "--no-input")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("pota_test_reset")).status_code, 404)
        self.assertNotContains(self.client.get(reverse("home")), "Reset POTA Test Imports")

    def test_staff_menu_and_two_step_page(self):
        self.make_import()
        self.client.force_login(self.staff)
        home = self.client.get(reverse("home"))
        self.assertContains(home, "Reset POTA Test Imports")
        preview = self.client.get(reverse("pota_test_reset"))
        self.assertContains(preview, "Dry-run preview")
        bad = self.client.post(reverse("pota_test_reset"), {"confirmation_phrase": "wrong"})
        self.assertEqual(bad.status_code, 400)
        review = self.client.post(reverse("pota_test_reset"), {"confirmation_phrase": "DELETE POTA TEST DATA"})
        self.assertContains(review, "Final Confirmation")
        self.assertTrue(Adventure.objects.exists())

    def test_nonstaff_is_denied(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("pota_test_reset")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("home")), "Reset POTA Test Imports")

    def test_staff_posts_require_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff)
        response = csrf_client.post(reverse("pota_test_reset"), {
            "confirmation_phrase": "DELETE POTA TEST DATA",
        })
        self.assertEqual(response.status_code, 403)

    @patch("core.pota_reset_views.execute_reset")
    def test_second_post_calls_canonical_service(self, reset_service):
        reset_service.return_value = PotaResetResult(
            backup_path="test-backup.sqlite3", deleted={}, retained={}, blocked=[], integrity="ok"
        )
        self.client.force_login(self.staff)
        self.client.post(reverse("pota_test_reset"), {
            "confirmation_phrase": "DELETE POTA TEST DATA",
        })
        response = self.client.post(reverse("pota_test_reset_execute"))
        self.assertEqual(response.status_code, 200)
        reset_service.assert_called_once_with(actor=self.staff)

    def test_preview_reports_fingerprint_without_contact_contents(self):
        self.make_import()
        preview = build_reset_preview()
        self.assertEqual(preview["counts"]["fingerprints"], 1)
        self.assertNotIn("contact contents", str(preview).lower())
