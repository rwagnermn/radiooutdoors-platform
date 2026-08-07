from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .account_forms import FollowerRegistrationForm, MemberRegistrationForm
from .models import FollowerInvitation, FollowRelationship, MemberProfile
from .qrz_service import QRZError, QRZNotFoundError, QRZUnavailableError, lookup_callsign


def register(request):
    """Public registration for QRZ-verified Radio Outdoors Members."""
    if request.user.is_authenticated:
        return redirect("account_home")

    invite_token = (request.GET.get("invite") or "").strip()
    if invite_token:
        return redirect("follower_register", token=invite_token)

    if request.method == "POST":
        form = MemberRegistrationForm(request.POST)
        if form.is_valid():
            callsign = form.cleaned_data["callsign"]
            try:
                result = lookup_callsign(callsign)
            except QRZNotFoundError:
                form.add_error(
                    "callsign",
                    "That callsign was not found in QRZ. Check it and try again.",
                )
            except QRZUnavailableError:
                form.add_error(
                    None,
                    "QRZ is temporarily unavailable. No account was created; please try again later.",
                )
            except QRZError as exc:
                form.add_error(
                    None,
                    f"QRZ verification could not be completed. No account was created. {exc}",
                )
            else:
                if MemberProfile.objects.filter(
                    callsign__iexact=result.callsign
                ).exists():
                    form.add_error(
                        "callsign", "That callsign is already registered."
                    )
                else:
                    with transaction.atomic():
                        user = form.save(commit=False)
                        user.username = result.callsign
                        user.first_name = result.first_name
                        user.last_name = result.last_name
                        user.save()
                        profile = MemberProfile.objects.create(
                            user=user,
                            callsign=result.callsign,
                            display_name=" ".join(
                                value
                                for value in [result.first_name, result.last_name]
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
                            qrz_first_name=result.first_name,
                            qrz_last_name=result.last_name,
                            qrz_city=result.city,
                            qrz_state=result.state,
                            qrz_country=result.country,
                            qrz_grid=result.grid,
                            qrz_license_class=result.license_class,
                            qrz_expiration=result.expires,
                        )

                    login(request, user)
                    messages.success(
                        request,
                        f"Welcome to Radio Outdoors, {profile.callsign}. Your callsign was verified through QRZ.",
                    )
                    return redirect("member_welcome")
    else:
        form = MemberRegistrationForm()

    return render(request, "accounts/register.html", {"form": form})


@login_required
def member_welcome(request):
    profile = getattr(request.user, "member_profile", None)
    if not profile or not profile.has_valid_verification(
        allow_development=settings.DEBUG
    ):
        return redirect("account_home")
    return render(request, "accounts/member_welcome.html")


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
        .select_related("member", "member__user")
        .order_by("status", "member__callsign")
    )
    return render(
        request,
        "accounts/account_home.html",
        {"profile": profile, "following": following},
    )
