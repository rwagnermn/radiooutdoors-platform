from io import BytesIO
import json
from pathlib import Path
import socket
import tempfile
from unittest.mock import patch
from urllib.error import HTTPError

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.test import RequestFactory
from django.urls import reverse
from PIL import Image

from core.models import (
    Adventure,
    JournalEntry,
    Location,
    MemberProfile,
    Photo,
    PhotoModerationActionAudit,
    QuarantinedPhoto,
)
from core.photo_moderation import (
    ModerationDecision,
    ModerationUnavailable,
    OpenAIModerationProvider,
    moderate_photo,
)
from core.photo_upload_notices import add_photo_upload_notice
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages import get_messages


def image_upload(name="photo.png"):
    output = BytesIO()
    Image.new("RGB", (40, 30), "orange").save(output, "PNG")
    return SimpleUploadedFile(name, output.getvalue(), "image/png")


class SafeProvider:
    def moderate(self, image_bytes, **kwargs):
        return ModerationDecision("approved", [], 0.99, provider_decision="safe")


class ReviewProvider:
    def moderate(self, image_bytes, **kwargs):
        return ModerationDecision("review", ["uncertain"], 0.55, "Administrator review required", "review")


class ExplicitProvider:
    def moderate(self, image_bytes, **kwargs):
        return ModerationDecision("rejected", ["sexual"], 0.99, "Unsafe public content", "reject")


class FailingProvider:
    def moderate(self, image_bytes, **kwargs):
        raise ModerationUnavailable("provider offline")


class LeakyFailureProvider:
    def moderate(self, image_bytes, **kwargs):
        raise ValueError("iVBOR-test-key-never-log")


def openai_response(*, flagged=False, flagged_categories=None, scores=None):
    flagged_categories = set(flagged_categories or [])
    category_names = {
        "sexual", "sexual/minors", "violence", "violence/graphic", "self-harm",
        "self-harm/intent", "self-harm/instructions", "hate", "hate/threatening",
        "illicit/violent",
    }
    return {
        "model": "omni-moderation-2024-09-26",
        "results": [{
            "flagged": flagged,
            "categories": {name: name in flagged_categories for name in category_names},
            "category_scores": {name: (scores or {}).get(name, 0.001) for name in category_names},
        }],
    }


@override_settings(OPENAI_API_KEY="test-key-never-log")
class OpenAIProviderTests(TestCase):
    def provider(self):
        return OpenAIModerationProvider()

    def test_safe_response_is_approved_and_audit_is_normalized(self):
        provider = self.provider()
        with patch.object(provider, "_request", return_value=openai_response()):
            decision = provider.moderate(b"image bytes", content_type="image/png")
        self.assertEqual(decision.status, "approved")
        self.assertEqual(decision.provider, "OpenAI")
        self.assertEqual(decision.provider_model, "omni-moderation-2024-09-26")

    def test_explicit_response_is_rejected(self):
        provider = self.provider()
        response = openai_response(
            flagged=True, flagged_categories={"sexual"}, scores={"sexual": 0.98}
        )
        with patch.object(provider, "_request", return_value=response):
            self.assertEqual(provider.moderate(b"bytes", content_type="image/png").status, "rejected")

    def test_questionable_score_requires_review(self):
        provider = self.provider()
        response = openai_response(scores={"violence": 0.20})
        with patch.object(provider, "_request", return_value=response):
            self.assertEqual(provider.moderate(b"bytes", content_type="image/png").status, "review")

    @override_settings(OPENAI_API_KEY="")
    def test_missing_key_fails_closed(self):
        with self.assertRaises(ModerationUnavailable):
            self.provider().moderate(b"bytes")

    def test_network_permission_error_is_sanitized(self):
        provider = self.provider()
        with patch.object(provider, "_request", side_effect=PermissionError("secret path")):
            with self.assertRaisesMessage(ModerationUnavailable, "permission was denied"):
                provider.moderate(b"bytes", content_type="image/png")

    def test_timeout_is_sanitized(self):
        provider = self.provider()
        with patch.object(provider, "_request", side_effect=socket.timeout("secret")):
            with self.assertRaisesMessage(ModerationUnavailable, "timed out"):
                provider.moderate(b"bytes", content_type="image/png")

    def test_rate_limit_is_sanitized(self):
        provider = self.provider()
        error = HTTPError(
            provider.endpoint,
            429,
            "secret",
            {},
            BytesIO(json.dumps({"error": {
                "type": "invalid_request_error",
                "message": "Image rate limit reached for this project.",
            }}).encode()),
        )
        with patch.object(provider, "_request", side_effect=error):
            with self.assertRaises(ModerationUnavailable) as captured:
                provider.moderate(b"bytes", content_type="image/png")
        self.assertEqual(captured.exception.category, "rate_limit")
        self.assertEqual(captured.exception.http_status, 429)
        self.assertNotIn("project", str(captured.exception).lower())

    def test_authentication_failure_is_categorized(self):
        provider = self.provider()
        error = HTTPError(provider.endpoint, 401, "secret", {}, BytesIO(b"{}"))
        with patch.object(provider, "_request", side_effect=error):
            with self.assertRaises(ModerationUnavailable) as captured:
                provider.moderate(b"bytes", content_type="image/png")
        self.assertEqual(captured.exception.category, "authentication")
        self.assertEqual(captured.exception.http_status, 401)

    def test_billing_quota_failure_is_categorized(self):
        provider = self.provider()
        body = {"error": {
            "type": "insufficient_quota",
            "code": "insufficient_quota",
            "message": "Billing quota unavailable for this project.",
        }}
        error = HTTPError(
            provider.endpoint, 429, "secret", {},
            BytesIO(json.dumps(body).encode()),
        )
        with patch.object(provider, "_request", side_effect=error):
            with self.assertRaises(ModerationUnavailable) as captured:
                provider.moderate(b"bytes", content_type="image/png")
        self.assertEqual(captured.exception.category, "billing_quota")
        self.assertEqual(captured.exception.provider_error_code, "insufficient_quota")

    def test_invalid_request_is_categorized(self):
        provider = self.provider()
        body = {"error": {"type": "invalid_request_error", "code": "bad_input"}}
        error = HTTPError(
            provider.endpoint, 400, "secret", {},
            BytesIO(json.dumps(body).encode()),
        )
        with patch.object(provider, "_request", side_effect=error):
            with self.assertRaises(ModerationUnavailable) as captured:
                provider.moderate(b"bytes", content_type="image/png")
        self.assertEqual(captured.exception.category, "invalid_request")
        self.assertEqual(captured.exception.provider_error_type, "invalid_request_error")

    def test_malformed_response_is_categorized(self):
        provider = self.provider()
        with patch.object(provider, "_request", return_value={"results": []}):
            with self.assertRaises(ModerationUnavailable) as captured:
                provider.moderate(b"bytes", content_type="image/png")
        self.assertEqual(captured.exception.category, "malformed_response")


@override_settings(
    MEDIA_ROOT=tempfile.mkdtemp(),
    PHOTO_MODERATION_BACKEND="core.photo_moderation.DisabledModerationProvider",
)
class PhotoModerationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("operator", password="secret")
        MemberProfile.objects.create(user=self.user, callsign="W5SAFE", callsign_verified=True)
        self.location = Location.objects.create(name="Safe Park")
        self.adventure = Adventure.objects.create(owner=self.user, title="Photo Story", location=self.location)
        self.entry = JournalEntry.objects.create(adventure=self.adventure, title="Day one", body="Notes")

    def make_photo(self):
        return Photo.objects.create(journal_entry=self.entry, image=image_upload())

    def make_safe_recommendation(self, name="safe.png"):
        return Photo.objects.create(
            journal_entry=self.entry,
            image=image_upload(name),
            moderation_status=Photo.ModerationStatus.PENDING,
            automated_decision="safe",
            moderation_categories=[],
            moderation_provider="OpenAI",
            moderation_provider_model="omni-moderation-latest",
        )

    def test_pending_image_is_hidden_from_public_adventure(self):
        photo = self.make_photo()
        self.adventure.cover_photo = photo
        self.adventure.save(update_fields=["cover_photo"])
        response = self.client.get(self.adventure.get_absolute_url())
        self.assertNotContains(response, photo.image.url)
        self.assertEqual(photo.moderation_status, "pending")
        self.assertEqual(self.client.get(photo.image.url).status_code, 404)

    @override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.SafeProvider")
    def test_safe_provider_approves_and_public_page_displays(self):
        photo = self.make_photo()
        moderate_photo(photo)
        photo.refresh_from_db()
        response = self.client.get(self.adventure.get_absolute_url())
        self.assertContains(response, photo.public_image_url)
        self.assertEqual(self.client.get(photo.public_image_url).status_code, 200)
        self.assertEqual(self.client.get(photo.image.url).status_code, 200)

    @override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.ExplicitProvider")
    def test_explicit_image_is_rejected_without_removing_adventure(self):
        photo = self.make_photo()
        moderate_photo(photo)
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "rejected")
        self.assertTrue(Adventure.objects.filter(pk=self.adventure.pk).exists())
        self.assertNotContains(self.client.get(self.adventure.get_absolute_url()), photo.image.url)

    @override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.ReviewProvider")
    def test_questionable_image_enters_review(self):
        photo = self.make_photo()
        moderate_photo(photo)
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "review")
        self.assertEqual(photo.moderation_categories, ["uncertain"])

    def test_severe_image_has_no_ordinary_staff_preview(self):
        photo = self.make_photo()
        photo.moderation_status = "review"
        photo.moderation_categories = ["suspected-csam"]
        photo.save(update_fields=["moderation_status", "moderation_categories"])
        staff = get_user_model().objects.create_user("reviewer", password="secret", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(photo.image.url).status_code, 404)
        queue = self.client.get(reverse("photo_moderation_queue"))
        self.assertContains(queue, "Restricted safety review.")

    @override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.FailingProvider")
    def test_service_failure_fails_closed(self):
        photo = self.make_photo()
        moderate_photo(photo)
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "pending")
        self.assertEqual(photo.automated_decision, "scan_failed")
        self.assertEqual(photo.moderation_display_status, "Scan failed")
        self.assertIn("provider_unavailable", photo.moderation_reason)

    @override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.FailingProvider")
    def test_scan_failed_is_private_and_staff_gets_sanitized_category(self):
        photo = self.make_photo()
        moderate_photo(photo)
        self.assertFalse(photo.is_publicly_visible)
        staff = get_user_model().objects.create_user(
            "failure-reviewer", password="secret", is_staff=True
        )
        self.client.force_login(staff)
        queue = self.client.get(reverse("photo_moderation_queue"))
        self.assertContains(queue, "Scan failed")
        self.assertContains(queue, "provider_unavailable")

    @override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.SafeProvider")
    def test_individual_retry_scans_once_and_creates_one_audit(self):
        photo = self.make_photo()
        photo.automated_decision = "scan_failed"
        photo.save(update_fields=["automated_decision"])
        staff = get_user_model().objects.create_user(
            "retry-reviewer", password="secret", is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse("photo_moderation_action", args=["photo", photo.pk, "retry"])
        )
        self.assertRedirects(response, reverse("photo_moderation_queue"))
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "approved")
        self.assertEqual(photo.automated_decision, "safe")
        self.assertEqual(
            PhotoModerationActionAudit.objects.filter(
                action="retry", requested_target_ids=[f"photo:{photo.pk}"]
            ).count(),
            1,
        )

    @override_settings(
        PHOTO_MODERATION_BACKEND="core.photo_moderation.OpenAIModerationProvider",
        OPENAI_API_KEY="",
    )
    def test_missing_openai_key_records_provider_and_stays_pending(self):
        photo = self.make_photo()
        moderate_photo(photo)
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "pending")
        self.assertEqual(photo.moderation_provider, "OpenAI")
        self.assertEqual(photo.moderation_provider_model, "omni-moderation-latest")

    @override_settings(
        PHOTO_MODERATION_BACKEND="core.photo_moderation.OpenAIModerationProvider",
        OPENAI_API_KEY="configured-for-mocked-request",
    )
    def test_openai_transport_failures_keep_stored_photo_pending(self):
        failures = (
            PermissionError("blocked"),
            socket.timeout("slow"),
            HTTPError("https://api.openai.com/v1/moderations", 429, "limited", {}, None),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                photo = self.make_photo()
                with patch.object(OpenAIModerationProvider, "_request", side_effect=failure):
                    moderate_photo(photo)
                photo.refresh_from_db()
                self.assertEqual(photo.moderation_status, "pending")

    @override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.LeakyFailureProvider")
    def test_logs_do_not_contain_api_key_or_image_data(self):
        photo = self.make_photo()
        with self.assertLogs("core.photo_moderation", level="WARNING") as captured:
            moderate_photo(photo)
        log_text = " ".join(captured.output)
        self.assertNotIn("test-key-never-log", log_text)
        self.assertNotIn("iVBOR", log_text)

    def test_staff_can_manually_approve_pending_photo(self):
        photo = self.make_photo()
        staff = get_user_model().objects.create_user("approver", password="secret", is_staff=True)
        self.client.force_login(staff)
        response = self.client.post(
            reverse("photo_moderation_action", args=["photo", photo.pk, "approve"])
        )
        self.assertRedirects(response, reverse("photo_moderation_queue"))
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "approved")
        self.assertEqual(photo.reviewed_by, staff)
        audit = PhotoModerationActionAudit.objects.get()
        self.assertEqual(audit.successful_target_ids, [f"photo:{photo.pk}"])
        self.assertEqual(audit.decision_source, "individual-manual")

    def test_persistent_upload_notice_has_count_and_continue_contract(self):
        request = RequestFactory().get("/")
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request._messages = FallbackStorage(request)
        add_photo_upload_notice(request, ["pending", "review", "approved"])
        notice = list(get_messages(request))[0]
        self.assertEqual(
            str(notice),
            "3 photos were uploaded. 2 are awaiting review and 1 was approved.",
        )
        self.assertIn("persistent", notice.tags)
        base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("Continue", base)
        self.assertIn('.flash-message:not(.persistent)', base)

    def test_staff_gets_clear_thumbnail_and_preview_without_acknowledgment(self):
        photo = self.make_photo()
        photo.moderation_status = "review"
        photo.moderation_categories = ["sexual"]
        photo.save(update_fields=["moderation_status", "moderation_categories"])
        thumbnail_url = reverse("photo_moderation_thumbnail", args=["photo", photo.pk])
        preview_url = reverse("photo_moderation_preview_file", args=["photo", photo.pk])
        detail_url = reverse("photo_moderation_detail", args=["photo", photo.pk])
        self.assertEqual(self.client.get(thumbnail_url).status_code, 302)
        staff = get_user_model().objects.create_user("previewer", password="secret", is_staff=True)
        self.client.force_login(staff)
        thumbnail = self.client.get(thumbnail_url)
        self.assertEqual(thumbnail.status_code, 200)
        self.assertEqual(thumbnail["X-Robots-Tag"], "noindex, nofollow, noarchive")
        self.assertEqual(thumbnail["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.get(preview_url).status_code, 200)
        detail = self.client.get(detail_url)
        self.assertContains(detail, 'alt="Photo under moderation"')
        self.assertNotContains(detail, "This image may contain sensitive content")
        queue = self.client.get(reverse("photo_moderation_queue"))
        self.assertContains(queue, f'alt="Moderation thumbnail for {self.adventure.title}')
        self.assertNotContains(queue, "Blurred moderation thumbnail")

    def test_minor_safety_image_has_no_thumbnail_or_preview(self):
        photo = self.make_photo()
        photo.moderation_status = "review"
        photo.moderation_categories = ["sexual/minors"]
        photo.save(update_fields=["moderation_status", "moderation_categories"])
        staff = get_user_model().objects.create_user("restricted-reviewer", password="secret", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("photo_moderation_thumbnail", args=["photo", photo.pk])).status_code, 404)
        detail = self.client.get(reverse("photo_moderation_detail", args=["photo", photo.pk]))
        self.assertContains(detail, "Restricted safety review.")
        self.assertNotContains(detail, "View Image")

    def test_rejection_reason_and_other_explanation_are_required_and_stored(self):
        photo = self.make_photo()
        staff = get_user_model().objects.create_user("rejecter", password="secret", is_staff=True)
        self.client.force_login(staff)
        reject_url = reverse("photo_moderation_action", args=["photo", photo.pk, "reject"])
        self.client.post(reject_url, {})
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "pending")
        self.client.post(reject_url, {"rejection_reason": "other"})
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "pending")
        self.client.post(reject_url, {
            "rejection_reason": "other", "rejection_explanation": "Not related to outdoor radio.",
        })
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "rejected")
        self.assertEqual(photo.rejection_reason_code, "other")
        self.assertEqual(photo.rejection_explanation, "Not related to outdoor radio.")

    def test_queue_is_compact_and_action_menu_is_accessible(self):
        photo = self.make_photo()
        photo.moderation_provider = "OpenAI"
        photo.moderation_provider_model = "omni-moderation-latest"
        photo.save(update_fields=["moderation_provider", "moderation_provider_model"])
        staff = get_user_model().objects.create_user("compact-reviewer", password="secret", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("photo_moderation_queue"))
        self.assertContains(response, 'aria-label="Actions for ')
        self.assertContains(response, "0 selected")
        self.assertContains(response, 'data-select-page')
        self.assertNotContains(response, "omni-moderation-latest")

    def test_bulk_confirmation_shows_thumbnails_and_subset_can_be_approved(self):
        first = self.make_safe_recommendation("confirm-one.png")
        second = self.make_safe_recommendation("confirm-two.png")
        staff = get_user_model().objects.create_user("batch-reviewer", password="secret", is_staff=True)
        self.client.force_login(staff)
        preview = self.client.post(reverse("photo_moderation_bulk_preview"), {
            "bulk_action": "approve", "status_filter": "all",
            "selected": [f"photo:{first.pk}", f"photo:{second.pk}"],
        })
        self.assertContains(preview, "moderation-thumbnail-grid")
        self.assertContains(preview, first.journal_entry.adventure.title)
        self.assertContains(preview, "Remove from batch", count=2)
        self.assertNotContains(preview, "Blurred thumbnail")
        applied = self.client.post(reverse("photo_moderation_bulk_apply"), {
            "bulk_action": "approve", "selected": [f"photo:{first.pk}"],
        }, follow=True)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.moderation_status, "approved")
        self.assertEqual(second.moderation_status, "pending")
        self.assertContains(applied, "1 photo approved successfully.")

    def test_return_from_bulk_confirmation_makes_no_changes(self):
        first = self.make_safe_recommendation("return-one.png")
        second = self.make_safe_recommendation("return-two.png")
        staff = get_user_model().objects.create_user("batch-returner", password="secret", is_staff=True)
        self.client.force_login(staff)
        preview = self.client.post(reverse("photo_moderation_bulk_preview"), {
            "bulk_action": "approve", "status_filter": "all",
            "selected": [f"photo:{first.pk}", f"photo:{second.pk}"],
        })
        self.assertContains(preview, "Return to Review Queue")
        self.client.get(reverse("photo_moderation_queue"))
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.moderation_status, "pending")
        self.assertEqual(second.moderation_status, "pending")

    def test_bulk_queue_controls_and_safe_count_are_visible(self):
        self.make_safe_recommendation()
        staff = get_user_model().objects.create_user("bulk-ui", password="secret", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("photo_moderation_queue"))
        self.assertContains(response, "Select all photos on this page")
        self.assertContains(response, "Clear Selection")
        self.assertContains(response, "Approve Selected")
        self.assertContains(response, "Reject Selected")
        self.assertContains(response, "Approve All Safe Recommendations")
        self.assertContains(response, "1 safe recommendation on this page")
        self.assertContains(response, "ro-scroll-table-region")
        self.assertContains(response, "ro-record-table")
        self.assertContains(response, "photo-checkbox-target")
        self.assertContains(response, "Actions for ")
        self.assertContains(response, "account-menu-icon")

    def test_empty_bulk_selection_has_exact_persistent_feedback(self):
        staff = get_user_model().objects.create_user(
            "empty-bulk-reviewer", password="secret", is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse("photo_moderation_bulk_preview"),
            {"bulk_action": "approve", "status_filter": "all"},
            follow=True,
        )
        self.assertContains(
            response,
            "Select at least one photo before applying a bulk action.",
        )
        self.assertContains(response, "persistent bulk-selection-error")

    def test_safe_bulk_approval_requires_counted_confirmation_and_records_audit(self):
        first = self.make_safe_recommendation("safe-one.png")
        second = self.make_safe_recommendation("safe-two.png")
        staff = get_user_model().objects.create_user("bulk-safe", password="secret", is_staff=True)
        self.client.force_login(staff)
        preview = self.client.post(reverse("photo_moderation_bulk_preview"), {
            "bulk_action": "approve_safe",
            "scope": "page",
            "status_filter": "all",
            "selected": [f"photo:{first.pk}", f"photo:{second.pk}"],
        })
        self.assertContains(
            preview,
            "Approve 2 photos recommended as safe? Approved photos will become publicly visible.",
        )
        apply_response = self.client.post(reverse("photo_moderation_bulk_apply"), {
            "bulk_action": "approve_safe",
            "scope": "page",
            "selected": [f"photo:{first.pk}", f"photo:{second.pk}"],
        }, follow=True)
        self.assertRedirects(apply_response, reverse("photo_moderation_queue"))
        self.assertContains(apply_response, "2 photos approved successfully.")
        self.assertEqual(
            Photo.objects.filter(pk__in=[first.pk, second.pk], moderation_status="approved").count(),
            2,
        )
        audit = PhotoModerationActionAudit.objects.get(decision_source="bulk-safe-recommendation")
        self.assertEqual(audit.actor, staff)
        self.assertEqual(set(audit.successful_target_ids), {f"photo:{first.pk}", f"photo:{second.pk}"})

    def test_safe_bulk_excludes_flagged_pending_review_failed_and_unscanned(self):
        safe = self.make_safe_recommendation("eligible.png")
        explicit = self.make_safe_recommendation("explicit.png")
        explicit.automated_decision = "reject"
        explicit.moderation_categories = ["sexual"]
        explicit.save(update_fields=["automated_decision", "moderation_categories"])
        review = self.make_safe_recommendation("review.png")
        review.automated_decision = "review"
        review.moderation_status = "review"
        review.save(update_fields=["automated_decision", "moderation_status"])
        unscanned = self.make_photo()
        staff = get_user_model().objects.create_user("bulk-exclude", password="secret", is_staff=True)
        self.client.force_login(staff)
        preview = self.client.post(reverse("photo_moderation_bulk_preview"), {
            "bulk_action": "approve_safe", "scope": "matching", "status_filter": "all",
        })
        self.assertEqual(preview.context["count"], 1)
        preview_tokens = [row["token"] for row in preview.context["rows"]]
        self.assertIn(f"photo:{safe.pk}", preview_tokens)
        self.assertNotIn(f"photo:{explicit.pk}", preview_tokens)
        self.assertNotIn(f"photo:{review.pk}", preview_tokens)
        self.assertNotIn(f"photo:{unscanned.pk}", preview_tokens)

    def test_bulk_selection_is_limited_to_explicit_current_page_tokens(self):
        safe = self.make_safe_recommendation()
        rejected = self.make_photo()
        rejected.moderation_status = "rejected"
        rejected.save(update_fields=["moderation_status"])
        staff = get_user_model().objects.create_user("bulk-filter", password="secret", is_staff=True)
        self.client.force_login(staff)
        preview = self.client.post(reverse("photo_moderation_bulk_preview"), {
            "bulk_action": "approve", "status_filter": "pending",
            "selected": [f"photo:{safe.pk}"],
        })
        preview_tokens = [row["token"] for row in preview.context["rows"]]
        self.assertEqual(preview_tokens, [f"photo:{safe.pk}"])
        self.assertNotIn(f"photo:{rejected.pk}", preview_tokens)
        approved = self.client.post(reverse("photo_moderation_bulk_apply"), {
            "bulk_action": "approve",
            "selected": [f"photo:{safe.pk}"],
        })
        self.assertEqual(approved.status_code, 302)
        safe.refresh_from_db()
        self.assertEqual(safe.moderation_status, "approved")

    def test_bulk_endpoints_require_staff(self):
        photo = self.make_safe_recommendation()
        payload = {
            "bulk_action": "approve", "scope": "page",
            "selected": [f"photo:{photo.pk}"],
        }
        self.assertEqual(self.client.post(reverse("photo_moderation_bulk_preview"), payload).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("photo_moderation_bulk_apply"), payload).status_code, 302)
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "pending")

    def test_bulk_partial_failure_continues_and_reports_failed_target(self):
        photo = self.make_safe_recommendation()
        staff = get_user_model().objects.create_user("bulk-partial", password="secret", is_staff=True)
        self.client.force_login(staff)
        response = self.client.post(reverse("photo_moderation_bulk_apply"), {
            "bulk_action": "approve", "scope": "page",
            "selected": [f"photo:{photo.pk}", "photo:999999"],
        }, follow=True)
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "approved")
        self.assertContains(response, "1 photo approved; 1 could not be processed.")
        self.assertContains(response, "Could not process: photo:999999")
        audit = PhotoModerationActionAudit.objects.get(decision_source="bulk-manual")
        self.assertEqual(audit.successful_target_ids, [f"photo:{photo.pk}"])
        self.assertEqual(audit.failed_targets[0]["target"], "photo:999999")

    def test_bulk_confirmation_has_no_second_dialog_and_guards_double_submit(self):
        script = (settings.BASE_DIR / "static" / "js" / "photo-moderation-bulk.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("window.confirm", script)
        self.assertIn("if (submitting", script)
        self.assertIn('confirmForm.dataset.actionKind === "approve"', script)
        self.assertIn('button.setAttribute("aria-busy", "true")', script)
        self.assertIn("button.disabled = true", script)
        self.assertIn('"Removing..."', script)

    def test_bulk_remove_confirmation_lists_only_explicit_selection(self):
        first = self.make_safe_recommendation("remove-one.png")
        second = self.make_safe_recommendation("remove-two.png")
        staff = get_user_model().objects.create_user("bulk-removal-reviewer", password="secret", is_staff=True)
        self.client.force_login(staff)
        preview = self.client.post(reverse("photo_moderation_bulk_preview"), {
            "bulk_action": "remove", "status_filter": "all",
            "selected": [f"photo:{first.pk}", f"photo:{second.pk}"],
        })
        self.assertContains(preview, "Remove 2 selected photos?")
        self.assertContains(preview, "Include this photo", count=2)
        self.assertContains(preview, "Remove Selected Photos")
        self.assertContains(preview, "Current moderation status", count=2)
        self.assertContains(preview, "Existing provider recommendation", count=2)

    def test_bulk_remove_quarantines_photo_preserves_file_parent_and_audit(self):
        photo = self.make_safe_recommendation("recoverable.png")
        photo.moderation_status = Photo.ModerationStatus.APPROVED
        photo.save(update_fields=["moderation_status"])
        original_pk, image_name = photo.pk, photo.image.name
        staff = get_user_model().objects.create_user("bulk-remover", password="secret", is_staff=True)
        self.client.force_login(staff)
        response = self.client.post(reverse("photo_moderation_bulk_apply"), {
            "bulk_action": "remove", "selected": [f"photo:{original_pk}"],
            "removal_reason": "member_request",
        }, follow=True)
        self.assertContains(response, "1 photo removed successfully.")
        self.assertFalse(Photo.objects.filter(pk=original_pk).exists())
        quarantine = QuarantinedPhoto.objects.get(original_target=f"photo:{original_pk}")
        self.assertEqual(quarantine.removed_by, staff)
        self.assertEqual(quarantine.removal_reason, "member_request")
        self.assertEqual(quarantine.metadata["status"], "approved")
        self.assertEqual(self.client.get(photo.image.url).status_code, 404)
        self.assertTrue(default_storage.exists(image_name))
        self.assertTrue(Adventure.objects.filter(pk=self.adventure.pk).exists())
        self.assertTrue(JournalEntry.objects.filter(pk=self.entry.pk).exists())
        audit = PhotoModerationActionAudit.objects.get(decision_source="bulk-quarantine")
        self.assertEqual(audit.successful_target_ids, [f"photo:{original_pk}"])

    def test_bulk_remove_subset_partial_failure_and_duplicate_are_safe(self):
        first, second = self.make_photo(), self.make_photo()
        staff = get_user_model().objects.create_user("bulk-subset-remover", password="secret", is_staff=True)
        self.client.force_login(staff)
        token = f"photo:{first.pk}"
        response = self.client.post(reverse("photo_moderation_bulk_apply"), {
            "bulk_action": "remove", "selected": [token, token, "photo:999999"],
            "removal_reason": "duplicate",
        }, follow=True)
        self.assertContains(response, "1 photo removed; 1 could not be processed.")
        self.assertEqual(QuarantinedPhoto.objects.count(), 1)
        self.assertTrue(Photo.objects.filter(pk=second.pk).exists())
        repeat = self.client.post(reverse("photo_moderation_bulk_apply"), {
            "bulk_action": "remove", "selected": [token], "removal_reason": "duplicate",
        }, follow=True)
        self.assertContains(repeat, "0 photos removed; 1 could not be processed.")
        self.assertEqual(QuarantinedPhoto.objects.count(), 1)

    def test_removed_filter_preview_permissions_and_restore(self):
        photo = self.make_safe_recommendation("restore.png")
        photo.moderation_status = Photo.ModerationStatus.APPROVED
        photo.save(update_fields=["moderation_status"])
        staff = get_user_model().objects.create_user("bulk-restorer", password="secret", is_staff=True)
        self.client.force_login(staff)
        self.client.post(reverse("photo_moderation_bulk_apply"), {
            "bulk_action": "remove", "selected": [f"photo:{photo.pk}"],
            "removal_reason": "accidental",
        })
        quarantine = QuarantinedPhoto.objects.get()
        removed = self.client.get(reverse("photo_moderation_queue") + "?status=removed")
        self.assertContains(removed, "Removed / Quarantined")
        self.assertContains(removed, "Uploaded accidentally")
        self.assertEqual(self.client.get(reverse("photo_quarantine_thumbnail", args=[quarantine.pk])).status_code, 200)
        restored = self.client.post(reverse("photo_quarantine_restore", args=[quarantine.pk]), follow=True)
        self.assertContains(restored, "Photo restored successfully.")
        quarantine.refresh_from_db()
        self.assertTrue(quarantine.is_restored)
        self.assertEqual(Photo.objects.get(journal_entry=self.entry).moderation_status, Photo.ModerationStatus.APPROVED)
        self.assertEqual(PhotoModerationActionAudit.objects.filter(decision_source="quarantine-restore").count(), 1)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("photo_quarantine_thumbnail", args=[quarantine.pk])).status_code, 302)

    def test_bulk_remove_requires_reason_staff_and_csrf(self):
        photo = self.make_photo()
        payload = {"bulk_action": "remove", "selected": [f"photo:{photo.pk}"]}
        self.assertEqual(self.client.post(reverse("photo_moderation_bulk_apply"), payload).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("photo_moderation_bulk_apply"), payload).status_code, 302)
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())
        staff = get_user_model().objects.create_user("csrf-remover", password="secret", is_staff=True)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(staff)
        self.assertEqual(csrf_client.post(reverse("photo_moderation_bulk_apply"), {
            **payload, "removal_reason": "spam",
        }).status_code, 403)
        self.client.force_login(staff)
        missing_reason = self.client.post(reverse("photo_moderation_bulk_apply"), payload, follow=True)
        self.assertContains(missing_reason, "Choose a reason for removal.")
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())

    def test_duplicate_bulk_tokens_are_processed_once(self):
        photo = self.make_safe_recommendation("duplicate-submit.png")
        staff = get_user_model().objects.create_user("bulk-deduplicate", password="secret", is_staff=True)
        self.client.force_login(staff)
        token = f"photo:{photo.pk}"
        response = self.client.post(reverse("photo_moderation_bulk_apply"), {
            "bulk_action": "approve", "selected": [token, token],
        }, follow=True)
        self.assertContains(response, "1 photo approved successfully.")
        audit = PhotoModerationActionAudit.objects.get(decision_source="bulk-manual")
        self.assertEqual(audit.successful_target_ids, [token])

    def test_moderation_queue_requires_staff(self):
        self.assertEqual(self.client.get(reverse("photo_moderation_queue")).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("photo_moderation_queue")).status_code, 302)

    @override_settings(PHOTO_MODERATION_BACKEND="core.test_photo_moderation.SafeProvider")
    def test_backfill_scans_existing_pending_image(self):
        photo = self.make_photo()
        call_command("backfill_photo_moderation")
        photo.refresh_from_db()
        self.assertEqual(photo.moderation_status, "approved")

    def test_duplicate_hash_prevents_second_adventure_upload(self):
        self.client.force_login(self.user)
        # Existing workflow hashes within an Adventure and skips repeat bytes.
        first = image_upload("one.png")
        second = SimpleUploadedFile("two.png", first.read(), "image/png")
        from adventures.views import _save_entry_photos
        saved, duplicates, statuses = _save_entry_photos(self.entry, [first, second])
        self.assertEqual((saved, duplicates), (1, 1))
        self.assertEqual(statuses, ["pending"])

    def test_all_browser_upload_sources_enter_same_pending_scan_path(self):
        # File picker, clipboard paste, and drag/drop all arrive as multipart
        # files; the server deliberately does not trust a client-side origin.
        from adventures.views import _save_entry_photos
        uploads = []
        for index, color in enumerate(("red", "green", "blue")):
            output = BytesIO()
            Image.new("RGB", (40, 30), color).save(output, "PNG")
            uploads.append(SimpleUploadedFile(f"source-{index}.png", output.getvalue(), "image/png"))
        saved, duplicates, statuses = _save_entry_photos(self.entry, uploads)
        self.assertEqual((saved, duplicates), (3, 0))
        self.assertFalse(
            self.entry.photos.exclude(moderation_status=Photo.ModerationStatus.PENDING).exists()
        )
