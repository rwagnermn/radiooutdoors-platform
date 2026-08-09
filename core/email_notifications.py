"""Central, privacy-conscious organizational email notifications."""
import hashlib

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone


def public_email_footer():
    return (
        "\n\nRadio Outdoors\n"
        f"Questions or account assistance: {settings.RADIO_OUTDOORS_CONTACT_EMAIL}"
    )


def _staff_url(route_name):
    return f"{settings.RADIO_OUTDOORS_SITE_URL}{reverse(route_name)}"


def notify_pending_verification_created(verification_request):
    """Send exactly one notice when a new request record is submitted."""
    send_mail(
        subject=f"Manual verification request: {verification_request.member.callsign}",
        message=(
            "A new Radio Outdoors manual-verification request is ready.\n\n"
            f"Applicant: {verification_request.full_name}\n"
            f"Callsign: {verification_request.member.callsign}\n"
            f"Submitted: {verification_request.created_at.isoformat()}\n\n"
            f"Review queue: {_staff_url('manual_verification_queue')}"
        ),
        from_email=settings.SERVER_EMAIL,
        recipient_list=[settings.RADIO_OUTDOORS_ADMIN_EMAIL],
        fail_silently=True,
    )


def notify_moderation_failure(instance, failure_category):
    """Notify staff once per record/category during the suppression window."""
    association_type = instance._meta.verbose_name.title()
    record_id = instance.pk or "unsaved"
    safe_category = str(failure_category)[:120]
    digest = hashlib.sha256(safe_category.encode("utf-8")).hexdigest()[:16]
    cache_key = (
        f"moderation-admin-notice:{instance._meta.label_lower}:"
        f"{digest}"
    )
    if not cache.add(
        cache_key,
        True,
        timeout=settings.ADMIN_NOTIFICATION_SUPPRESSION_SECONDS,
    ):
        return False

    send_mail(
        subject=f"Photo moderation failure: {association_type} {record_id}",
        message=(
            "Radio Outdoors kept an image hidden because moderation failed.\n\n"
            f"Photo record identifier: {record_id}\n"
            f"Association type: {association_type}\n"
            f"Failure category: {safe_category}\n"
            f"Timestamp: {timezone.now().isoformat()}\n\n"
            f"Moderation queue: {_staff_url('photo_moderation_queue')}"
        ),
        from_email=settings.SERVER_EMAIL,
        recipient_list=[settings.RADIO_OUTDOORS_ADMIN_EMAIL],
        fail_silently=True,
    )
    return True
