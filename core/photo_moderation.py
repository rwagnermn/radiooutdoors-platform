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
from django.utils.module_loading import import_string
from PIL import Image, UnidentifiedImageError


logger = logging.getLogger(__name__)
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "HEIC"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000


class ModerationUnavailable(RuntimeError):
    pass


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
                raise ModerationUnavailable("Validated image content could not be read.") from exc
        if not mime_type:
            raise ModerationUnavailable("Validated image format is not supported for moderation.")
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
            if exc.code in {401, 403}:
                category = "authentication failure"
            elif exc.code == 429:
                category = "rate limit"
            else:
                category = "HTTP failure"
            raise ModerationUnavailable(f"OpenAI {category} (status {exc.code}).") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ModerationUnavailable("OpenAI moderation request timed out.") from exc
        except ssl.SSLError as exc:
            raise ModerationUnavailable("OpenAI moderation TLS connection failed.") from exc
        except PermissionError as exc:
            raise ModerationUnavailable("Outbound network permission was denied.") from exc
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, PermissionError):
                message = "Outbound network permission was denied."
            elif isinstance(reason, socket.gaierror):
                message = "OpenAI moderation DNS lookup failed."
            elif isinstance(reason, ssl.SSLError):
                message = "OpenAI moderation TLS connection failed."
            elif isinstance(reason, (TimeoutError, socket.timeout)):
                message = "OpenAI moderation request timed out."
            else:
                message = "OpenAI moderation network request failed."
            raise ModerationUnavailable(message) from exc
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ModerationUnavailable("OpenAI returned an invalid moderation response.") from exc

        try:
            result = response["results"][0]
            categories = result["categories"]
            scores = result["category_scores"]
            if not isinstance(categories, dict) or not isinstance(scores, dict):
                raise TypeError
        except (KeyError, IndexError, TypeError) as exc:
            raise ModerationUnavailable("OpenAI returned an invalid moderation response.") from exc

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
        raise ValidationError("Choose an image smaller than 12 MB.")
    try:
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            image.verify()
            image_format = (image.format or "").upper()
        uploaded_file.seek(0)
        with Image.open(uploaded_file) as image:
            if image.width * image.height > getattr(settings, "PHOTO_MAX_PIXELS", MAX_IMAGE_PIXELS):
                raise ValidationError("The image dimensions are too large.")
        uploaded_file.seek(0)
    except ValidationError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError("Choose a valid JPG, PNG, HEIC, or WebP image.") from exc
    if image_format not in ALLOWED_FORMATS:
        raise ValidationError("Choose a JPG, PNG, HEIC, or WebP image.")
    return image_format


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
    try:
        provider = get_provider()
        setattr(instance, provider_field, getattr(provider, "provider_name", "")[:80])
        setattr(instance, provider_model_field, getattr(provider, "model", "")[:80])
        image.open("rb")
        try:
            payload = image.read()
        finally:
            image.close()
        decision = provider.moderate(payload, content_type="image/*")
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
        setattr(instance, automated_decision_field, "scan_failed")
        setattr(instance, reason_field, "Moderation could not be completed.")
        update_fields.extend([automated_decision_field])
        safe_detail = (
            str(exc)[:200]
            if isinstance(exc, (ModerationUnavailable, ImproperlyConfigured))
            else "Unexpected moderation failure."
        )
        logger.warning(
            "Photo moderation failed closed (%s): %s",
            type(exc).__name__, safe_detail,
        )
    instance.save(update_fields=update_fields)
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
