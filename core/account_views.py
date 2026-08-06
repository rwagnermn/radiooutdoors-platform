from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from .account_forms import RadioOutdoorsRegistrationForm
from .models import (
    FollowerInvitation,
    FollowRelationship,
    MemberProfile,
)


def register(request):
    if request.user.is_authenticated:
        return redirect("account_home")

    follow_callsign = (
        request.POST.get("follow")
        or request.GET.get("follow")
        or ""
    ).strip().upper()

    invite_token = (
        request.POST.get("invite")
        or request.GET.get("invite")
        or ""
    ).strip()

    invitation = None
    if invite_token:
        invitation = (
            FollowerInvitation.objects.select_related(
                "member", "member__user"
            )
            .filter(
                token=invite_token,
                status=FollowerInvitation.Status.PENDING,
            )
            .first()
        )

    next_url = (
        request.POST.get("next")
        or request.GET.get("next")
        or ""
    ).strip()

    if request.method == "POST":
        form = RadioOutdoorsRegistrationForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)

            if invitation:
                relationship, _ = FollowRelationship.objects.get_or_create(
                    member=invitation.member,
                    follower=user,
                )
                relationship.status = FollowRelationship.Status.APPROVED
                relationship.responded_at = timezone.now()
                relationship.save(
                    update_fields=[
                        "status",
                        "responded_at",
                        "updated_at",
                    ]
                )

                invitation.status = FollowerInvitation.Status.ACCEPTED
                invitation.accepted_by = user
                invitation.accepted_at = timezone.now()
                invitation.save(
                    update_fields=[
                        "status",
                        "accepted_by",
                        "accepted_at",
                        "updated_at",
                    ]
                )

                messages.success(
                    request,
                    f"Account created. You now follow "
                    f"{invitation.member.callsign}.",
                )
                return redirect(
                    "member_detail",
                    callsign=invitation.member.callsign,
                )

            if follow_callsign:
                member = MemberProfile.objects.filter(
                    callsign__iexact=follow_callsign,
                    profile_is_public=True,
                    user__is_active=True,
                ).first()

                if member and member.user != user:
                    FollowRelationship.objects.get_or_create(
                        member=member,
                        follower=user,
                        defaults={
                            "status": FollowRelationship.Status.PENDING
                        },
                    )
                    messages.success(
                        request,
                        f"Account created. Your request to follow "
                        f"{member.callsign} was sent.",
                    )
                    return redirect(
                        "member_detail",
                        callsign=member.callsign,
                    )

            messages.success(
                request,
                "Your Radio Outdoors account was created.",
            )

            if next_url.startswith("/"):
                return redirect(next_url)

            return redirect("account_home")
    else:
        initial = {}
        if invitation:
            name_parts = invitation.name.split(maxsplit=1)
            initial["first_name"] = name_parts[0] if name_parts else ""
            initial["last_name"] = (
                name_parts[1] if len(name_parts) > 1 else ""
            )
            initial["email"] = invitation.email

        form = RadioOutdoorsRegistrationForm(initial=initial)

    return render(
        request,
        "accounts/register.html",
        {
            "form": form,
            "follow_callsign": follow_callsign,
            "invite_token": invite_token,
            "invitation": invitation,
            "next_url": next_url,
        },
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
        {
            "profile": profile,
            "following": following,
        },
    )
