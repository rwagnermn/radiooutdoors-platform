"""Fail-closed, provider-neutral image moderation services."""
from dataclasses import dataclass, field
import base64
import hashlib
from io import BytesIO
import json
import logging
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import ContentFile
from django.utils.module_loading import import_string
from PIL import Image, UnidentifiedImageError

from .email_notifications import notify_moderation_failure
from .photo_normalization import (
    ImageNormalizationError, JPEG_MIME_TYPE, normalize_image_bytes,
    read_and_normalize,
)


logger = logging.getLogger(__name__)
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "HEIC"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000


class ModerationUnavailable(RuntimeError):
    """A public-safe provider failure with structured staff diagnostics."""

    def __init__(
        self,
        message,
        *,
        category="provider_unavailable",
        http_status=None,
        provider_error_type="",
        provider_error_code="",
    ):
        super().__init__(message)
        self.category = category
        self.http_status = http_status
        self.provider_error_type = provider_error_type[:80]
        self.provider_error_code = provider_error_code[:80]


@dataclass(frozen=True)
class ModerationDecision:
    status: str
    categories: list[str] = field(default_factory=list)
    confidence: float | None = None
    reason: str = ""
    provider_decision: str = ""
    provider: str = ""
    provider_model: str = ""


class DisabledModerationProvider:
    """Safe default: no image is approved when no real provider is configured."""

    def moderate(self, image_bytes, *, content_type=""):
        raise ModerationUnavailable("No production photo-moderation provider is configured.")


class OpenAIModerationProvider:
    """Moderate image bytes with OpenAI without exposing a public media URL."""

    endpoint = "https://api.openai.com/v1/moderations"
    provider_name = "OpenAI"

    def __init__(self):
        self.api_key = getattr(settings, "OPENAI_API_KEY", "").strip()
        self.model = getattr(
            settings, "OPENAI_MODERATION_MODEL", "omni-moderation-latest"
        ).strip()
        self.timeout = getattr(settings, "OPENAI_MODERATION_TIMEOUT", 20)

    def _request(self, payload):
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    @staticmethod
    def _http_failure(exc):
        error_type = ""
        error_code = ""
        message = ""
        try:
            body = json.loads(exc.read().decode("utf-8"))
            error = body.get("error", {}) if isinstance(body, dict) else {}
            if isinstance(error, dict):
                error_type = str(error.get("type") or "")[:80]
                error_code = str(error.get("code") or "")[:80]
                message = str(error.get("message") or "").lower()
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, OSError):
            pass

        if exc.code in {401, 403}:
            category = "authentication"
            safe_message = f"OpenAI authentication was rejected (status {exc.code})."
        elif exc.code == 429:
            quota_markers = ("quota", "billing", "insufficient_quota")
            if error_code == "insufficient_quota" or any(x in message for x in quota_markers):
                category = "billing_quota"
                safe_message = "OpenAI billing or quota is unavailable (status 429)."
            else:
                category = "rate_limit"
                safe_message = "OpenAI image moderation capacity is unavailable (status 429)."
        elif exc.code in {400, 404, 405, 422}:
            category = "invalid_request"
            safe_message = f"OpenAI rejected the moderation request (status {exc.code})."
        elif exc.code == 413:
            category = "image_size"
            safe_message = "OpenAI rejected the image size (status 413)."
        else:
            category = "http_failure"
            safe_message = f"OpenAI moderation HTTP failure (status {exc.code})."
        return ModerationUnavailable(
            safe_message,
            category=category,
            http_status=exc.code,
            provider_error_type=error_type,
            provider_error_code=error_code,
        )

    def moderate(self, image_bytes, *, content_type=""):
        if not self.api_key:
            raise ModerationUnavailable("OpenAI API key is not configured.")
        mime_type = content_type if content_type in {
            "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"
        } else ""
        if not mime_type:
            try:
                with Image.open(BytesIO(image_bytes)) as image:
                    mime_type = {
                        "JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp",
                        "HEIC": "image/heic", "HEIF": "image/heif",
                    }.get((image.format or "").upper(), "")
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise ModerationUnavailable(
                    "Validated image content could not be read.",
                    category="image_read",
                ) from exc
        if not mime_type:
            raise ModerationUnavailable(
                "Validated image format is not supported for moderation.",
                category="unsupported_image_format",
            )
        payload = {
            "model": self.model,
            "input": [{
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
                },
            }],
        }
        try:
            response = self._request(payload)
        except HTTPError as exc:
            raise self._http_failure(exc) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ModerationUnavailable(
                "OpenAI moderation request timed out.", category="timeout"
            ) from exc
        except ssl.SSLError as exc:
            raise ModerationUnavailable(
                "OpenAI moderation TLS connection failed.", category="tls"
            ) from exc
        except PermissionError as exc:
            raise ModerationUnavailable(
                "Outbound network permission was denied.", category="network_permission"
            ) from exc
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, PermissionError):
                message = "Outbound network permission was denied."
            elif isinstance(reason, socket.gaierror):
                message = "OpenAI moderation DNS lookup failed."
                category = "dns"
            elif isinstance(reason, ssl.SSLError):
                message = "OpenAI moderation TLS connection failed."
                category = "tls"
            elif isinstance(reason, (TimeoutError, socket.timeout)):
                message = "OpenAI moderation request timed out."
                category = "timeout"
            else:
                message = "OpenAI moderation network request failed."
                category = "network"
            if isinstance(reason, PermissionError):
                category = "network_permission"
            raise ModerationUnavailable(message, category=category) from exc
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ModerationUnavailable(
                "OpenAI returned an invalid moderation response.",
                category="malformed_response",
            ) from exc

        try:
            result = response["results"][0]
            categories = result["categories"]
            scores = result["category_scores"]
            if not isinstance(categories, dict) or not isinstance(scores, dict):
                raise TypeError
        except (KeyError, IndexError, TypeError) as exc:
            raise ModerationUnavailable(
                "OpenAI returned an invalid moderation response.",
                category="malformed_response",
            ) from exc

        flagged = sorted(name for name, value in categories.items() if value is True)
        severe = {"sexual/minors"}
        reject = {"sexual", "violence/graphic"}
        review = {
            "self-harm", "self-harm/intent", "self-harm/instructions",
            "hate", "hate/threatening", "violence", "illicit/violent",
        }
        borderline = sorted(
            name for name in reject | review
            if isinstance(scores.get(name), (int, float)) and scores[name] >= 0.15
        )
        audit_categories = sorted(set(flagged) | set(borderline))
        confidence = max(
            (float(scores[name]) for name in audit_categories if name in scores),
            default=max((float(value) for value in scores.values()), default=0.0),
        )
        provider_model = str(response.get("model") or self.model)[:80]
        if severe.intersection(flagged):
            return ModerationDecision(
                "rejected", audit_categories, confidence,
                "Unsafe image cannot be published.", "reject-critical",
                self.provider_name, provider_model,
            )
        if reject.intersection(flagged):
            return ModerationDecision(
                "rejected", audit_categories, confidence,
                "Image does not meet public-content requirements.", "reject",
                self.provider_name, provider_model,
            )
        if flagged or borderline:
            return ModerationDecision(
                "review", audit_categories, confidence,
                "Administrator review required.", "review",
                self.provider_name, provider_model,
            )
        return ModerationDecision(
            "approved", [], confidence, "", "safe",
            self.provider_name, provider_model,
        )


def get_provider():
    backend = getattr(
        settings,
        "PHOTO_MODERATION_BACKEND",
        "core.photo_moderation.DisabledModerationProvider",
    )
    try:
        return import_string(backend)()
    except (ImportError, AttributeError, TypeError) as exc:
        raise ImproperlyConfigured("The configured photo moderation backend cannot be loaded.") from exc


def validate_image_file(uploaded_file):
    if uploaded_file.size > getattr(settings, "PHOTO_MAX_UPLOAD_BYTES", MAX_IMAGE_BYTES):
        raise ValidationError("The image is too large to process safely.")
    try:
        uploaded_file.seek(0)
        normalized = normalize_image_bytes(uploaded_file.read())
        uploaded_file.seek(0)
    except ImageNormalizationError:
        uploaded_file.seek(0)
        raise
    return normalized.source_format


def _photo_derivatives(photo):
    """Return a stored moderation derivative, creating all derivatives once."""
    if (
        photo.derivative_status == "ready"
        and photo.moderation_image and photo.web_image and photo.thumbnail_image
    ):
        photo.moderation_image.open("rb")
        try:
            return photo.moderation_image.read()
        finally:
            photo.moderation_image.close()

    normalized = read_and_normalize(photo.image)
    stem = (photo.reference_number or f"RO-PH-{photo.pk:06d}").lower()
    photo.moderation_image.save(
        f"{stem}-moderation.jpg", ContentFile(normalized.moderation_bytes), save=False
    )
    photo.web_image.save(
        f"{stem}-web.jpg", ContentFile(normalized.web_bytes), save=False
    )
    photo.thumbnail_image.save(
        f"{stem}-thumbnail.jpg", ContentFile(normalized.thumbnail_bytes), save=False
    )
    photo.derivative_status = "ready"
    photo.derivative_metadata = {
        "source_format": normalized.source_format,
        "source_dimensions": [normalized.source_width, normalized.source_height],
        "source_mode": normalized.source_mode,
        "exif_orientation": normalized.exif_orientation,
        "moderation_dimensions": [normalized.moderation_width, normalized.moderation_height],
        "moderation_bytes": len(normalized.moderation_bytes),
        "web_dimensions": [normalized.web_width, normalized.web_height],
        "web_bytes": len(normalized.web_bytes),
        "thumbnail_dimensions": [normalized.thumbnail_width, normalized.thumbnail_height],
        "thumbnail_bytes": len(normalized.thumbnail_bytes),
        "moderation_mime_type": JPEG_MIME_TYPE,
    }
    photo.save(update_fields=[
        "moderation_image", "web_image", "thumbnail_image",
        "derivative_status", "derivative_metadata",
    ])
    return normalized.moderation_bytes


def file_digest(file_field):
    digest = hashlib.sha256()
    file_field.open("rb")
    try:
        for chunk in iter(lambda: file_field.read(1024 * 1024), b""):
            digest.update(chunk)
    finally:
        file_field.close()
    return digest.hexdigest()


def moderate_file_field(instance, field_name, *, status_field, categories_field,
                        confidence_field, reason_field, provider_field,
                        provider_model_field, automated_decision_field):
    """Scan one stored image and persist a fail-closed result."""
    image = getattr(instance, field_name)
    if not image:
        return None
    setattr(instance, status_field, "pending")
    setattr(instance, categories_field, [])
    setattr(instance, confidence_field, None)
    setattr(instance, reason_field, "")
    provider = None
    update_fields = [
        status_field, categories_field, confidence_field, reason_field,
        provider_field, provider_model_field,
    ]
    failure_category = ""
    try:
        provider = get_provider()
        setattr(instance, provider_field, getattr(provider, "provider_name", "")[:80])
        setattr(instance, provider_model_field, getattr(provider, "model", "")[:80])
        if instance.__class__.__name__ == "Photo" and field_name == "image":
            payload = _photo_derivatives(instance)
        else:
            normalized = read_and_normalize(image)
            payload = normalized.moderation_bytes
        decision = provider.moderate(payload, content_type=JPEG_MIME_TYPE)
        if decision.status not in {"approved", "review", "rejected"}:
            raise ModerationUnavailable("The moderation provider returned an invalid decision.")
        setattr(instance, status_field, decision.status)
        setattr(instance, categories_field, list(decision.categories))
        setattr(instance, confidence_field, decision.confidence)
        setattr(instance, reason_field, decision.reason[:240])
        setattr(instance, provider_field, decision.provider[:80])
        setattr(instance, provider_model_field, decision.provider_model[:80])
        setattr(instance, automated_decision_field, decision.provider_decision[:32])
        update_fields.append(automated_decision_field)
    except Exception as exc:
        failure_category = type(exc).__name__
        setattr(instance, automated_decision_field, "scan_failed")
        if isinstance(exc, ImageNormalizationError):
            if hasattr(instance, "derivative_status"):
                instance.derivative_status = "failed"
                update_fields.append("derivative_status")
            stored_reason = f"{exc.category}: {exc.messages[0]}"[:240]
        elif isinstance(exc, ModerationUnavailable):
            stored_reason = f"{exc.category}: {str(exc)}"[:240]
        elif isinstance(exc, ImproperlyConfigured):
            stored_reason = "configuration: Moderation provider configuration failed."
        else:
            stored_reason = "unexpected: Moderation could not be completed."
        setattr(instance, reason_field, stored_reason)
        update_fields.extend([automated_decision_field])
        safe_detail = (
            str(exc)[:200]
            if isinstance(exc, (ModerationUnavailable, ImproperlyConfigured))
            else "Unexpected moderation failure."
        )
        logger.warning(
            "Photo moderation failed closed exception=%s category=%s "
            "http_status=%s provider_error_type=%s provider_error_code=%s detail=%s",
            type(exc).__name__,
            getattr(exc, "category", "unexpected"),
            getattr(exc, "http_status", None),
            getattr(exc, "provider_error_type", ""),
            getattr(exc, "provider_error_code", ""),
            safe_detail,
        )
    instance.save(update_fields=update_fields)
    if failure_category:
        notify_moderation_failure(instance, failure_category)
    return getattr(instance, status_field)


def moderate_photo(photo):
    return moderate_file_field(
        photo, "image", status_field="moderation_status",
        categories_field="moderation_categories",
        confidence_field="moderation_confidence", reason_field="moderation_reason",
        provider_field="moderation_provider", provider_model_field="moderation_provider_model",
        automated_decision_field="automated_decision",
    )


def moderate_location_photo(location):
    return moderate_file_field(
        location, "photo", status_field="photo_moderation_status",
        categories_field="photo_moderation_categories",
        confidence_field="photo_moderation_confidence", reason_field="photo_moderation_reason",
        provider_field="photo_moderation_provider", provider_model_field="photo_moderation_provider_model",
        automated_decision_field="photo_automated_decision",
    )


def moderate_profile_photo(profile):
    return moderate_file_field(
        profile, "profile_photo", status_field="profile_photo_moderation_status",
        categories_field="profile_photo_moderation_categories",
        confidence_field="profile_photo_moderation_confidence", reason_field="profile_photo_moderation_reason",
        provider_field="profile_photo_moderation_provider", provider_model_field="profile_photo_moderation_provider_model",
        automated_decision_field="profile_photo_automated_decision",
    )


def moderate_default_location_image(default_image):
    return moderate_file_field(
        default_image, "image", status_field="moderation_status",
        categories_field="moderation_categories",
        confidence_field="moderation_confidence", reason_field="moderation_reason",
        provider_field="moderation_provider", provider_model_field="moderation_provider_model",
        automated_decision_field="automated_decision",
    )
