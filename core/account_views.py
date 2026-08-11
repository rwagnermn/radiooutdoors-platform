import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .account_forms import FollowerRegistrationForm, MemberRegistrationForm
from .member_forms import AccountDeactivateForm
from .models import FollowerInvitation, FollowRelationship, MemberProfile
from .policy_acceptance import record_policy_acceptance
from .qrz_service import (
    QRZConfigurationError,
    QRZError,
    QRZNotFoundError,
    QRZUnavailableError,
    lookup_callsign,
)


logger = logging.getLogger(__name__)


def register(request):
    """Public registration for QRZ-verified Radio Outdoors Members."""
    if request.user.is_authenticated:
        return redirect("account_home")

    invite_token = (request.GET.get("invite") or "").strip()
    if invite_token:
        return redirect("follower_register", token=invite_token)

    manual_available = False
    support_contact_needed = False
    if request.method == "POST":
        form = MemberRegistrationForm(request.POST)
        if form.is_valid():
            callsign = form.cleaned_data["callsign"]
            registration_action = request.POST.get("registration_action", "qrz")
            try:
                result = lookup_callsign(callsign)
            except QRZNotFoundError as exc:
                logger.warning(
                    "Registration QRZ verification failed category=not_found exception_type=%s",
                    type(exc).__name__,
                )
                if registration_action == "manual":
                    with transaction.atomic():
                        user = form.save()
                        profile = MemberProfile.objects.create(
                            user=user,
                            callsign=callsign,
                            email_visible_to_members=False,
                            profile_is_public=False,
                            callsign_verified=False,
                            verification_method=MemberProfile.VerificationMethod.NONE,
                            home_country="",
                        )
                        record_policy_acceptance(
                            user,
                            registration_path="pending_manual",
                            account_status="pending",
                        )
                    login(request, user)
                    messages.info(
                        request,
                        "Your restricted Pending Member account was created. Complete your manual verification request next.",
                    )
                    return redirect("manual_verification_request")
                manual_available = True
                form.add_error("callsign", "QRZ could not verify this callsign.")
                form.add_error(
                    None,
                    "Callsign not found: QRZ successfully responded, but this callsign was not found. If you are a licensed amateur-radio operator, you may request manual verification.",
                )
            except QRZUnavailableError as exc:
                logger.warning(
                    "Registration QRZ verification failed category=temporarily_unavailable exception_type=%s",
                    type(exc).__name__,
                )
                form.add_error(
                    None,
                    "QRZ is temporarily unavailable. No account was created; please try again later.",
                )
            except QRZConfigurationError as exc:
                support_contact_needed = True
                logger.warning(
                    "Registration QRZ verification failed category=configuration exception_type=%s configuration_key=%s",
                    type(exc).__name__,
                    exc.configuration_key or "unknown",
                )
                form.add_error(
                    None,
                    "QRZ configuration or connection failure. No account was created; please contact Radio Outdoors support.",
                )
            except QRZError as exc:
                support_contact_needed = True
                logger.warning(
                    "Registration QRZ verification failed category=qrz_rejected exception_type=%s",
                    type(exc).__name__,
                )
                form.add_error(
                    None,
                    "QRZ configuration or connection failure. No account was created; please try again or contact Radio Outdoors support.",
                )
            else:
                if MemberProfile.objects.filter(
                    callsign__iexact=result.callsign
                ).exists():
                    form.add_error(
                        "callsign", "That callsign is already registered."
                    )
                else:
                    person_identity = result.is_person_identity
                    first_name = result.first_name if person_identity else ""
                    last_name = result.last_name if person_identity else ""
                    with transaction.atomic():
                        user = form.save(commit=False)
                        user.username = result.callsign
                        user.first_name = first_name
                        user.last_name = last_name
                        user.save()
                        profile = MemberProfile.objects.create(
                            user=user,
                            callsign=result.callsign,
                            display_name=" ".join(
                                value
                                for value in [first_name, last_name]
                                if value
                            ),
                            home_city=result.city,
                            home_state=result.state,
                            home_country=result.country or "USA",
                            email_visible_to_members=False,
                            callsign_verified=True,
                            verification_method=MemberProfile.VerificationMethod.QRZ,
                            verification_at=timezone.now(),
                            qrz_verified_at=timezone.now(),
                            qrz_first_name=first_name,
                            qrz_last_name=last_name,
                            qrz_city=result.city,
                            qrz_state=result.state,
                            qrz_country=result.country,
                            qrz_grid=result.grid,
                            qrz_license_class=result.license_class,
                            qrz_expiration=result.expires,
                        )
                        record_policy_acceptance(
                            user,
                            registration_path="qrz_member",
                            account_status="verified",
                        )

                    login(request, user)
                    messages.success(
                        request,
                        f"Welcome to Radio Outdoors, {profile.callsign}. Your callsign was verified through QRZ.",
                    )
                    return redirect("member_welcome")
    else:
        form = MemberRegistrationForm()

    return render(
        request,
        "accounts/register.html",
        {
            "form": form,
            "manual_available": manual_available,
            "support_contact_needed": support_contact_needed,
        },
    )


@login_required
def member_welcome(request):
    profile = getattr(request.user, "member_profile", None)
    if not profile or not profile.has_valid_verification(
        allow_development=settings.DEBUG
    ):
        return redirect("account_home")
    welcome_name = request.user.first_name.strip() or profile.callsign
    return render(
        request,
        "accounts/member_welcome.html",
        {"profile": profile, "welcome_name": welcome_name},
    )


def follower_register(request, token):
    """Create a callsign-free Follower from a valid pending invitation."""
    if request.user.is_authenticated:
        return redirect("account_home")

    invitation = get_object_or_404(
        FollowerInvitation.objects.select_related("member", "member__user"),
        token=token,
        status=FollowerInvitation.Status.PENDING,
    )

    if request.method == "POST":
        form = FollowerRegistrationForm(request.POST, invitation=invitation)
        if form.is_valid():
            with transaction.atomic():
                locked_invitation = get_object_or_404(
                    FollowerInvitation.objects.select_for_update(),
                    pk=invitation.pk,
                    status=FollowerInvitation.Status.PENDING,
                )
                user = form.save()
                record_policy_acceptance(
                    user,
                    registration_path="follower_invitation",
                    account_status="follower",
                )
                relationship, _ = FollowRelationship.objects.get_or_create(
                    member=locked_invitation.member,
                    follower=user,
                )
                relationship.status = FollowRelationship.Status.APPROVED
                relationship.responded_at = timezone.now()
                relationship.save(
                    update_fields=["status", "responded_at", "updated_at"]
                )
                locked_invitation.status = FollowerInvitation.Status.ACCEPTED
                locked_invitation.accepted_by = user
                locked_invitation.accepted_at = timezone.now()
                locked_invitation.save(
                    update_fields=[
                        "status",
                        "accepted_by",
                        "accepted_at",
                        "updated_at",
                    ]
                )

            login(request, user)
            messages.success(
                request,
                f"Your Follower account was created. You now follow {invitation.member.callsign}.",
            )
            return redirect(
                "member_detail", callsign=invitation.member.callsign
            )
    else:
        form = FollowerRegistrationForm(invitation=invitation)

    return render(
        request,
        "accounts/follower_register.html",
        {"form": form, "invitation": invitation},
    )


@login_required
def account_home(request):
    profile = getattr(request.user, "member_profile", None)
    following = (
        FollowRelationship.objects.filter(follower=request.user)
        .filter(member__user__is_active=True)
        .select_related("member", "member__user")
        .order_by("status", "member__callsign")
    )
    return render(
        request,
        "accounts/account_home.html",
        {"profile": profile, "following": following},
    )


@login_required
def deactivate_account(request):
    profile = getattr(request.user, "member_profile", None)
    if not profile:
        messages.error(request, "Only Member accounts can use this deactivation workflow.")
        return redirect("account_home")
    if request.user.is_staff or request.user.is_superuser:
        messages.error(
            request,
            "Staff and administrator accounts cannot be deactivated here.",
        )
        return redirect("account_home")

    if request.method == "POST":
        form = AccountDeactivateForm(
            request.POST,
            expected_callsign=profile.callsign,
        )
        if form.is_valid():
            callsign = profile.callsign
            user_id = request.user.pk
            request.user.is_active = False
            request.user.save(update_fields=["is_active"])
            logout(request)
            logger.info(
                "Member self-deactivated user_id=%s callsign=%s",
                user_id,
                callsign,
            )
            return render(
                request,
                "accounts/account_deactivated.html",
                {"callsign": callsign},
            )
    else:
        form = AccountDeactivateForm(expected_callsign=profile.callsign)

    return render(
        request,
        "accounts/deactivate_account.html",
        {"profile": profile, "form": form},
    )
