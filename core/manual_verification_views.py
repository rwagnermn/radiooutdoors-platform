from functools import wraps

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .auth import is_verified_member
from .manual_verification_forms import (
    ManualVerificationRequestForm,
    ManualVerificationReviewForm,
)
from .models import ManualVerificationRequest, MemberProfile


def pending_member_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        profile = getattr(request.user, "member_profile", None)
        if not profile or is_verified_member(request.user):
            return HttpResponseForbidden(
                "This page is only available to Members pending verification."
            )
        request.pending_member_profile = profile
        return view_func(request, *args, **kwargs)

    return wrapped


@pending_member_required
def manual_verification_status(request):
    verification_request = getattr(
        request.pending_member_profile, "manual_verification_request", None
    )
    return render(
        request,
        "accounts/manual_verification_status.html",
        {
            "profile": request.pending_member_profile,
            "verification_request": verification_request,
        },
    )


@pending_member_required
def manual_verification_request(request):
    profile = request.pending_member_profile
    instance = getattr(profile, "manual_verification_request", None)
    if request.method == "POST":
        form = ManualVerificationRequestForm(request.POST, instance=instance)
        if form.is_valid():
            with transaction.atomic():
                verification_request = form.save(commit=False)
                verification_request.member = profile
                verification_request.status = ManualVerificationRequest.Status.PENDING
                verification_request.reviewer_message = ""
                verification_request.reviewed_by = None
                verification_request.reviewed_at = None
                verification_request.save()

                name_parts = verification_request.full_name.split(maxsplit=1)
                profile.display_name = verification_request.full_name
                profile.home_country = verification_request.country
                profile.save(update_fields=["display_name", "home_country", "updated_at"])
                profile.user.first_name = name_parts[0]
                profile.user.last_name = name_parts[1] if len(name_parts) > 1 else ""
                profile.user.save(update_fields=["first_name", "last_name"])

            messages.success(request, "Your verification request was submitted for review.")
            return redirect("manual_verification_status")
    else:
        form = ManualVerificationRequestForm(
            instance=instance,
            initial={
                "full_name": profile.public_name
                if profile.display_name or profile.user.get_full_name()
                else "",
                "country": profile.home_country if instance else "",
            },
        )
    return render(
        request,
        "accounts/manual_verification_form.html",
        {"form": form, "profile": profile, "verification_request": instance},
    )


@staff_member_required
def manual_verification_queue(request):
    requests = ManualVerificationRequest.objects.select_related(
        "member", "member__user", "reviewed_by"
    ).order_by("status", "created_at")
    return render(
        request,
        "members/manual_verification_queue.html",
        {"verification_requests": requests},
    )


@staff_member_required
def manual_verification_review(request, request_id):
    verification_request = get_object_or_404(
        ManualVerificationRequest.objects.select_related("member", "member__user"),
        pk=request_id,
    )
    if request.method == "POST":
        form = ManualVerificationReviewForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data["action"]
            with transaction.atomic():
                locked = ManualVerificationRequest.objects.select_for_update().get(
                    pk=verification_request.pk
                )
                locked.reviewer_message = form.cleaned_data["reviewer_message"].strip()
                locked.reviewed_by = request.user
                locked.reviewed_at = timezone.now()
                if action == "approve":
                    locked.status = ManualVerificationRequest.Status.APPROVED
                    profile = locked.member
                    name_parts = locked.full_name.split(maxsplit=1)
                    profile.display_name = locked.full_name
                    profile.home_country = locked.country
                    profile.callsign_verified = True
                    profile.verification_method = MemberProfile.VerificationMethod.MANUAL
                    profile.verification_at = locked.reviewed_at
                    profile.qrz_verified_at = None
                    profile.verified_by = request.user
                    profile.save(
                        update_fields=[
                            "callsign_verified",
                            "display_name",
                            "home_country",
                            "verification_method",
                            "verification_at",
                            "qrz_verified_at",
                            "verified_by",
                            "updated_at",
                        ]
                    )
                    profile.user.first_name = name_parts[0]
                    profile.user.last_name = name_parts[1] if len(name_parts) > 1 else ""
                    profile.user.save(update_fields=["first_name", "last_name"])
                elif action == "more_info":
                    locked.status = ManualVerificationRequest.Status.MORE_INFO
                else:
                    locked.status = ManualVerificationRequest.Status.REJECTED
                if action != "approve":
                    profile = locked.member
                    profile.callsign_verified = False
                    profile.verification_method = MemberProfile.VerificationMethod.NONE
                    profile.verification_at = None
                    profile.qrz_verified_at = None
                    profile.verified_by = None
                    profile.save(
                        update_fields=[
                            "callsign_verified",
                            "verification_method",
                            "verification_at",
                            "qrz_verified_at",
                            "verified_by",
                            "updated_at",
                        ]
                    )
                locked.save()
            messages.success(
                request,
                f"{verification_request.member.callsign} review updated to {locked.get_status_display()}.",
            )
            return redirect("manual_verification_queue")
    else:
        form = ManualVerificationReviewForm()
    return render(
        request,
        "members/manual_verification_review.html",
        {"verification_request": verification_request, "form": form},
    )
