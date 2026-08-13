import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import MemberProfile
from .recovery_views import _rate_limit_key, _within_rate_limit
from .sms_forms import (
    MobilePhoneForm,
    SmsPasswordResetForm,
    SmsRecoveryStartForm,
    VerificationCodeForm,
)
from .twilio_verify import TwilioVerifyClient, TwilioVerifyError

logger = logging.getLogger(__name__)
PHONE_SESSION = "phone_verification_profile_id"
RECOVERY_SESSION = "sms_recovery_user_id"
RECOVERY_APPROVED_SESSION = "sms_recovery_approved_user_id"


def mask_phone(phone):
    return f"ending in {phone[-4:]}" if phone else "your mobile phone"


def _provider_error(request, exc):
    logger.warning(
        "Twilio Verify request failed category=%s exception_type=%s",
        exc.category,
        type(exc).__name__,
    )
    if exc.category == "rate_limited":
        messages.error(request, "Too many text-message requests. Please try again later.")
    elif exc.category in {"verification_failed", "verification_expired"}:
        messages.error(request, "That verification code is invalid or has expired.")
    else:
        messages.error(request, "Text-message verification is temporarily unavailable. Please try again later.")


@login_required
def mobile_phone_settings(request):
    profile = getattr(request.user, "member_profile", None)
    if not profile:
        raise Http404
    if request.method == "POST" and request.POST.get("action") == "remove":
        profile.mobile_phone = ""
        profile.phone_verified_at = None
        profile.save(update_fields=["mobile_phone", "phone_verified_at", "updated_at"])
        request.session.pop(PHONE_SESSION, None)
        messages.success(request, "Mobile number removed.")
        return redirect("mobile_phone_settings")
    form = MobilePhoneForm(request.POST or None, initial={"mobile_phone": profile.mobile_phone})
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["mobile_phone"]
        if phone != profile.mobile_phone:
            profile.mobile_phone = phone
            profile.phone_verified_at = None
            profile.save(update_fields=["mobile_phone", "phone_verified_at", "updated_at"])
        messages.success(request, "Mobile number saved. Verify it before using SMS recovery.")
        return redirect("mobile_phone_settings")
    return render(request, "accounts/mobile_phone_settings.html", {"form": form, "profile": profile, "masked_phone": mask_phone(profile.mobile_phone)})


@login_required
def mobile_phone_send(request):
    if request.method != "POST":
        return redirect("mobile_phone_settings")
    profile = getattr(request.user, "member_profile", None)
    if not profile or not profile.mobile_phone:
        return redirect("mobile_phone_settings")
    key = _rate_limit_key("phone-send", f"{profile.pk}:{request.META.get('REMOTE_ADDR', 'unknown')}")
    if not _within_rate_limit(key, limit=settings.SMS_RECOVERY_RATE_LIMIT, timeout=settings.SMS_RECOVERY_RATE_LIMIT_WINDOW):
        messages.error(request, "Too many verification requests. Please try again later.")
        return redirect("mobile_phone_settings")
    try:
        TwilioVerifyClient().send_code(profile.mobile_phone)
    except TwilioVerifyError as exc:
        _provider_error(request, exc)
        return redirect("mobile_phone_settings")
    request.session[PHONE_SESSION] = profile.pk
    return redirect("mobile_phone_verify")


@login_required
def mobile_phone_verify(request):
    profile = getattr(request.user, "member_profile", None)
    if not profile or request.session.get(PHONE_SESSION) != profile.pk:
        return redirect("mobile_phone_settings")
    form = VerificationCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            TwilioVerifyClient().check_code(profile.mobile_phone, form.cleaned_data["code"])
        except TwilioVerifyError as exc:
            _provider_error(request, exc)
        else:
            profile.phone_verified_at = timezone.now()
            profile.save(update_fields=["phone_verified_at", "updated_at"])
            request.session.pop(PHONE_SESSION, None)
            messages.success(request, "Mobile number verified.")
            return redirect("mobile_phone_settings")
    return render(request, "accounts/mobile_phone_verify.html", {"form": form, "masked_phone": mask_phone(profile.mobile_phone)})


def sms_recovery_start(request):
    form = SmsRecoveryStartForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        identity = form.cleaned_data["identity"].strip()
        remote = request.META.get("REMOTE_ADDR", "unknown")
        allowed = _within_rate_limit(_rate_limit_key("sms-start-ip", remote), limit=settings.SMS_RECOVERY_RATE_LIMIT, timeout=settings.SMS_RECOVERY_RATE_LIMIT_WINDOW)
        allowed = _within_rate_limit(_rate_limit_key("sms-start-id", identity.casefold()), limit=settings.SMS_RECOVERY_RATE_LIMIT, timeout=settings.SMS_RECOVERY_RATE_LIMIT_WINDOW) and allowed
        profiles = list(MemberProfile.objects.select_related("user").filter(Q(callsign__iexact=identity) | Q(user__email__iexact=identity), user__is_active=True).exclude(mobile_phone="").exclude(phone_verified_at=None)[:2]) if allowed else []
        if len(profiles) == 1:
            request.session[RECOVERY_SESSION] = profiles[0].user_id
            return redirect("sms_recovery_send")
        messages.info(request, "If the account is eligible for SMS recovery, a verification option will be available.")
    return render(request, "registration/sms_recovery_start.html", {"form": form})


def _recovery_profile(request):
    user_id = request.session.get(RECOVERY_SESSION)
    if not user_id:
        return None
    return MemberProfile.objects.select_related("user").filter(user_id=user_id, user__is_active=True, phone_verified_at__isnull=False).exclude(mobile_phone="").first()


def sms_recovery_send(request):
    profile = _recovery_profile(request)
    if not profile:
        return redirect("sms_recovery_start")
    if request.method == "POST":
        key = _rate_limit_key("sms-send", f"{profile.user_id}:{request.META.get('REMOTE_ADDR', 'unknown')}")
        if not _within_rate_limit(key, limit=settings.SMS_RECOVERY_RATE_LIMIT, timeout=settings.SMS_RECOVERY_RATE_LIMIT_WINDOW):
            messages.error(request, "Too many text-message requests. Please try again later.")
        else:
            try:
                TwilioVerifyClient().send_code(profile.mobile_phone)
            except TwilioVerifyError as exc:
                _provider_error(request, exc)
            else:
                return redirect("sms_recovery_verify")
    return render(request, "registration/sms_recovery_send.html", {"masked_phone": mask_phone(profile.mobile_phone)})


def sms_recovery_verify(request):
    profile = _recovery_profile(request)
    if not profile:
        return redirect("sms_recovery_start")
    form = VerificationCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        key = _rate_limit_key("sms-check", f"{profile.user_id}:{request.META.get('REMOTE_ADDR', 'unknown')}")
        if not _within_rate_limit(key, limit=settings.SMS_RECOVERY_VERIFY_LIMIT, timeout=settings.SMS_RECOVERY_RATE_LIMIT_WINDOW):
            messages.error(request, "Too many verification attempts. Please start again later.")
        else:
            try:
                TwilioVerifyClient().check_code(profile.mobile_phone, form.cleaned_data["code"])
            except TwilioVerifyError as exc:
                _provider_error(request, exc)
            else:
                request.session[RECOVERY_APPROVED_SESSION] = profile.user_id
                request.session.pop(RECOVERY_SESSION, None)
                return redirect("sms_recovery_reset")
    return render(request, "registration/sms_recovery_verify.html", {"form": form, "masked_phone": mask_phone(profile.mobile_phone)})


def sms_recovery_reset(request):
    user_id = request.session.get(RECOVERY_APPROVED_SESSION)
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if not user:
        return redirect("sms_recovery_start")
    form = SmsPasswordResetForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        request.session.pop(RECOVERY_APPROVED_SESSION, None)
        request.session.cycle_key()
        return redirect("account_recovery_complete")
    return render(request, "registration/sms_recovery_reset.html", {"form": form})
