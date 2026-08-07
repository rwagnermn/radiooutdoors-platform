import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .auth import verified_member_required
from .member_forms import MemberDeleteForm, MemberProfileForm
from .models import MemberProfile
from .qrz_service import (
    QRZConfigurationError,
    QRZError,
    QRZNotFoundError,
    QRZUnavailableError,
    lookup_callsign,
)


logger = logging.getLogger(__name__)


def _members():
    return MemberProfile.objects.select_related("user").annotate(
        adventure_count=Count(
            "user__adventures",
            filter=Q(user__adventures__is_public=True),
            distinct=True,
        ),
        journal_count=Count(
            "user__adventures__journal_entries",
            filter=Q(
                user__adventures__is_public=True,
                user__adventures__journal_entries__is_public=True,
            ),
            distinct=True,
        ),
        photo_count=Count(
            "user__adventures__journal_entries__photos",
            filter=Q(
                user__adventures__is_public=True,
                user__adventures__journal_entries__is_public=True,
            ),
            distinct=True,
        ),
    )


def _public_verification_methods():
    methods = [
        MemberProfile.VerificationMethod.QRZ,
        MemberProfile.VerificationMethod.ADMIN,
    ]
    if settings.DEBUG:
        methods.append(MemberProfile.VerificationMethod.DEVELOPMENT)
    return methods


def member_list(request):
    members = _members().filter(
        profile_is_public=True,
        callsign_verified=True,
        verification_method__in=_public_verification_methods(),
        user__is_active=True,
    ).exclude(callsign="")

    search = request.GET.get("q", "").strip()
    if search:
        members = members.filter(
            Q(callsign__icontains=search)
            | Q(display_name__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(home_city__icontains=search)
            | Q(home_state__icontains=search)
            | Q(home_country__icontains=search)
        )

    return render(
        request,
        "members/member_list.html",
        {
            "members": members.order_by("callsign"),
            "search": search,
        },
    )


def member_detail(request, callsign):
    profile = get_object_or_404(
        _members(), callsign__iexact=callsign
    )
    owner = request.user.is_authenticated and request.user == profile.user

    if (
        (
            not profile.profile_is_public
            or not profile.has_valid_verification(
                allow_development=settings.DEBUG
            )
        )
        and not owner
        and not request.user.is_staff
    ):
        raise Http404("Member not found.")

    adventures = (
        profile.user.adventures.select_related(
            "location",
            "cover_photo",
        )
        .annotate(
            journal_count=Count("journal_entries", distinct=True),
            photo_count=Count("journal_entries__photos", distinct=True),
        )
        .order_by("-updated_at")
    )

    if not owner and not request.user.is_staff:
        adventures = adventures.filter(is_public=True)

    return render(
        request,
        "members/member_detail.html",
        {
            "profile": profile,
            "adventures": adventures[:6],
            "is_owner": owner,
        },
    )


@verified_member_required
def my_member_profile(request):
    profile, _ = MemberProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        form = MemberProfileForm(
            request.POST,
            request.FILES,
            instance=profile,
            user=request.user,
        )
        if form.is_valid():
            saved = form.save()
            messages.success(request, "Member profile saved.")
            return redirect("member_detail", callsign=saved.callsign)
    else:
        form = MemberProfileForm(instance=profile, user=request.user)

    return render(
        request,
        "members/member_form.html",
        {
            "form": form,
            "profile": profile,
        },
    )


@staff_member_required
def member_admin_list(request):
    members = (
        MemberProfile.objects.select_related("user")
        .annotate(
            total_adventures=Count("user__adventures", distinct=True),
            total_journals=Count(
                "user__adventures__journal_entries",
                distinct=True,
            ),
            total_photos=Count(
                "user__adventures__journal_entries__photos",
                distinct=True,
            ),
        )
        .order_by("callsign")
    )
    return render(
        request,
        "members/member_admin_list.html",
        {
            "members": members,
            "development_verification_available": settings.DEBUG,
        },
    )


@staff_member_required
@require_POST
def member_verify_qrz(request, member_id):
    profile = get_object_or_404(MemberProfile, pk=member_id)
    callsign = profile.callsign.strip().upper()
    if not callsign:
        messages.error(request, "QRZ verification requires a callsign.")
        return redirect("member_admin_list")

    try:
        result = lookup_callsign(callsign)
    except QRZNotFoundError as exc:
        logger.warning(
            "QRZ verification not found member_id=%s callsign=%s staff_id=%s",
            profile.pk,
            callsign,
            request.user.pk,
        )
        messages.error(request, f"{callsign} was not found in QRZ: {exc}")
    except QRZConfigurationError as exc:
        logger.error(
            "QRZ configuration failure member_id=%s callsign=%s staff_id=%s",
            profile.pk,
            callsign,
            request.user.pk,
        )
        messages.error(request, f"QRZ credentials or configuration problem: {exc}")
    except QRZUnavailableError as exc:
        logger.warning(
            "QRZ unavailable member_id=%s callsign=%s staff_id=%s",
            profile.pk,
            callsign,
            request.user.pk,
        )
        messages.error(request, f"QRZ is temporarily unavailable: {exc}")
    except QRZError as exc:
        logger.warning(
            "QRZ verification failure member_id=%s callsign=%s staff_id=%s",
            profile.pk,
            callsign,
            request.user.pk,
        )
        messages.error(request, f"QRZ verification failed: {exc}")
    else:
        profile.callsign = callsign
        profile.callsign_verified = True
        profile.verification_method = MemberProfile.VerificationMethod.QRZ
        profile.verification_at = timezone.now()
        profile.qrz_verified_at = profile.verification_at
        profile.qrz_first_name = result.first_name
        profile.qrz_last_name = result.last_name
        profile.qrz_city = result.city
        profile.qrz_state = result.state
        profile.qrz_country = result.country
        profile.qrz_grid = result.grid
        profile.qrz_license_class = result.license_class
        profile.qrz_expiration = result.expires
        profile.verified_by = request.user
        profile.save(
            update_fields=[
                "callsign",
                "callsign_verified",
                "verification_method",
                "verification_at",
                "qrz_verified_at",
                "qrz_first_name",
                "qrz_last_name",
                "qrz_city",
                "qrz_state",
                "qrz_country",
                "qrz_grid",
                "qrz_license_class",
                "qrz_expiration",
                "verified_by",
                "updated_at",
            ]
        )
        logger.info(
            "QRZ verification succeeded member_id=%s callsign=%s staff_id=%s",
            profile.pk,
            callsign,
            request.user.pk,
        )
        messages.success(request, f"{callsign} was verified with QRZ.")

    return redirect("member_admin_list")


@staff_member_required
@require_POST
def member_mark_verified_for_development(request, member_id):
    if not settings.DEBUG:
        raise Http404("Development verification is unavailable.")

    profile = get_object_or_404(MemberProfile, pk=member_id)
    callsign = profile.callsign.strip().upper()
    if not callsign:
        messages.error(request, "Development verification requires a callsign.")
        return redirect("member_admin_list")

    profile.callsign = callsign
    profile.callsign_verified = True
    profile.verification_method = MemberProfile.VerificationMethod.DEVELOPMENT
    profile.verification_at = timezone.now()
    profile.qrz_verified_at = None
    profile.verified_by = request.user
    profile.save(
        update_fields=[
            "callsign",
            "callsign_verified",
            "verification_method",
            "verification_at",
            "qrz_verified_at",
            "verified_by",
            "updated_at",
        ]
    )
    logger.warning(
        "Development-only verification override member_id=%s callsign=%s staff_id=%s",
        profile.pk,
        callsign,
        request.user.pk,
    )
    messages.warning(
        request,
        f"{callsign} was marked verified for local development only; QRZ was not used.",
    )
    return redirect("member_admin_list")


@staff_member_required
@require_POST
def member_admin_verify(request, member_id):
    profile = get_object_or_404(MemberProfile, pk=member_id)
    callsign = profile.callsign.strip().upper()
    if not callsign:
        messages.error(request, "Admin verification requires a callsign.")
        return redirect("member_admin_list")

    profile.callsign = callsign
    profile.callsign_verified = True
    profile.verification_method = MemberProfile.VerificationMethod.ADMIN
    profile.verification_at = timezone.now()
    profile.qrz_verified_at = None
    profile.verified_by = request.user
    profile.save(
        update_fields=[
            "callsign",
            "callsign_verified",
            "verification_method",
            "verification_at",
            "qrz_verified_at",
            "verified_by",
            "updated_at",
        ]
    )
    logger.warning(
        "Admin verification applied member_id=%s callsign=%s staff_id=%s",
        profile.pk,
        callsign,
        request.user.pk,
    )
    messages.success(
        request,
        f"{callsign} is now Admin Verified by {request.user.get_username()}.",
    )
    return redirect("member_admin_list")


@staff_member_required
@require_POST
def member_toggle_active(request, member_id):
    profile = get_object_or_404(
        MemberProfile.objects.select_related("user"),
        pk=member_id,
    )
    if profile.user == request.user:
        messages.error(request, "You cannot deactivate your own account.")
    else:
        profile.user.is_active = not profile.user.is_active
        profile.user.save(update_fields=["is_active"])
    return redirect("member_admin_list")


@staff_member_required
def member_delete(request, member_id):
    profile = get_object_or_404(
        MemberProfile.objects.select_related("user"),
        pk=member_id,
    )

    if profile.user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect("member_admin_list")

    if request.method == "POST":
        form = MemberDeleteForm(
            request.POST,
            expected_callsign=profile.callsign,
        )
        if form.is_valid():
            callsign = profile.callsign
            profile.user.delete()
            messages.success(
                request,
                f"{callsign} and all associated data were deleted.",
            )
            return redirect("member_admin_list")
    else:
        form = MemberDeleteForm(expected_callsign=profile.callsign)

    return render(
        request,
        "members/member_delete.html",
        {
            "profile": profile,
            "form": form,
        },
    )
