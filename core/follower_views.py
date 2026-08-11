from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .auth import verified_member_required
from .email_notifications import public_email_footer
from .follower_forms import FollowerInvitationForm
from .models import (
    FollowerInvitation,
    FollowRelationship,
    MemberProfile,
)


def _absolute_url(request, route_name, **kwargs):
    return request.build_absolute_uri(
        reverse(route_name, kwargs=kwargs)
    )


def _public_message(message):
    return message + public_email_footer()


@login_required
@require_POST
def request_follow(request, callsign):
    member = get_object_or_404(
        MemberProfile.objects.select_related("user"),
        callsign__iexact=callsign,
        profile_is_public=True,
        user__is_active=True,
    )

    if member.user == request.user:
        messages.info(request, "You cannot follow yourself.")
        return redirect("member_detail", callsign=member.callsign)

    relationship, _ = FollowRelationship.objects.get_or_create(
        member=member,
        follower=request.user,
        defaults={"status": FollowRelationship.Status.PENDING},
    )

    if relationship.status == FollowRelationship.Status.BLOCKED:
        raise Http404("Member not found.")

    if relationship.status == FollowRelationship.Status.APPROVED:
        messages.info(request, f"You already follow {member.callsign}.")
    else:
        relationship.status = FollowRelationship.Status.PENDING
        relationship.responded_at = None
        relationship.save(
            update_fields=["status", "responded_at", "updated_at"]
        )
        messages.success(request, "Follow request sent.")

        # Confirmation to the requester.
        if request.user.email:
            send_mail(
                subject=f"Your request to follow {member.callsign} was sent",
                message=_public_message(
                    f"Your request to follow {member.callsign} on "
                    "Radio Outdoors has been sent. You will receive "
                    "another email if the Member approves it."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[request.user.email],
                fail_silently=True,
            )

        # Notice to the publishing Member.
        if member.user.email:
            follower_name = (
                request.user.get_full_name() or request.user.username
            )
            manage_url = request.build_absolute_uri(
                reverse("follower_management")
            )
            send_mail(
                subject=(
                    "New Radio Outdoors follow request from "
                    f"{follower_name}"
                ),
                message=_public_message(
                    f"{follower_name} "
                    f"({request.user.email or 'no email supplied'}) "
                    f"requested to follow {member.callsign}.\n\n"
                    f"Review the request:\n{manage_url}"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[member.user.email],
                fail_silently=True,
            )

    return redirect("member_detail", callsign=member.callsign)


@verified_member_required
def follower_management(request):
    profile = get_object_or_404(MemberProfile, user=request.user)
    relationships = (
        profile.followers.select_related("follower")
        .order_by("status", "-created_at")
    )
    invitations = profile.follower_invitations.order_by(
        "status", "-created_at"
    )

    invitation_form = FollowerInvitationForm()

    return render(
        request,
        "members/follower_management.html",
        {
            "profile": profile,
            "relationships": relationships,
            "invitations": invitations,
            "invitation_form": invitation_form,
        },
    )


@verified_member_required
@require_POST
def invite_follower(request):
    profile = get_object_or_404(MemberProfile, user=request.user)
    form = FollowerInvitationForm(request.POST)

    if not form.is_valid():
        relationships = (
            profile.followers.select_related("follower")
            .order_by("status", "-created_at")
        )
        invitations = profile.follower_invitations.order_by(
            "status", "-created_at"
        )
        return render(
            request,
            "members/follower_management.html",
            {
                "profile": profile,
                "relationships": relationships,
                "invitations": invitations,
                "invitation_form": form,
            },
            status=400,
        )

    name = form.cleaned_data["name"].strip()
    email = form.cleaned_data["email"].strip().lower()

    if email == request.user.email.lower():
        messages.error(request, "You cannot invite yourself.")
        return redirect("follower_management")

    existing_user = User.objects.filter(email__iexact=email).first()

    if existing_user:
        if not existing_user.is_active:
            messages.error(
                request,
                "That account is inactive and was not added as a Follower.",
            )
            return redirect("follower_management")

        relationship, _ = FollowRelationship.objects.get_or_create(
            member=profile,
            follower=existing_user,
        )

        if relationship.status == FollowRelationship.Status.BLOCKED:
            messages.error(
                request,
                "That account is blocked. Unblock it before adding it.",
            )
            return redirect("follower_management")

        relationship.status = FollowRelationship.Status.APPROVED
        relationship.responded_at = timezone.now()
        relationship.save(
            update_fields=["status", "responded_at", "updated_at"]
        )

        member_url = _absolute_url(
            request,
            "member_detail",
            callsign=profile.callsign,
        )
        send_mail(
            subject=f"{profile.callsign} added you as a Radio Outdoors Follower",
            message=_public_message(
                f"{profile.public_name} ({profile.callsign}) added you "
                "as an approved Follower on Radio Outdoors.\n\n"
                f"View the Member and Adventures:\n{member_url}\n\n"
                "You can stop following from your Radio Outdoors account."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[existing_user.email],
            fail_silently=True,
        )
        messages.success(
            request,
            f"{existing_user.get_full_name() or existing_user.username} "
            "was added as an approved Follower.",
        )
        return redirect("follower_management")

    invitation, created = FollowerInvitation.objects.get_or_create(
        member=profile,
        email=email,
        defaults={"name": name},
    )

    if not created:
        invitation.name = name
        invitation.status = FollowerInvitation.Status.PENDING
        invitation.accepted_by = None
        invitation.accepted_at = None
        invitation.ensure_token()
        invitation.save()

    invite_url = request.build_absolute_uri(
        reverse("follower_register", kwargs={"token": invitation.token})
    )

    send_mail(
        subject=f"{profile.callsign} invited you to follow Radio Outdoors Adventures",
        message=_public_message(
            f"{profile.public_name} ({profile.callsign}) invited you "
            "to follow their Radio Outdoors Adventures.\n\n"
            "Create a free Radio Outdoors Follower account:\n"
            f"{invite_url}\n\n"
            "After registration, you will be connected automatically."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=True,
    )

    messages.success(
        request,
        f"Invitation sent to {name} at {email}.",
    )
    return redirect("follower_management")


@verified_member_required
@require_POST
def invitation_action(request, invitation_id, action):
    invitation = get_object_or_404(
        FollowerInvitation,
        pk=invitation_id,
        member__user=request.user,
    )

    if action == "cancel":
        invitation.status = FollowerInvitation.Status.CANCELLED
        invitation.save(update_fields=["status", "updated_at"])
        messages.success(request, "Invitation cancelled.")
        return redirect("follower_management")

    if action == "resend":
        invitation.status = FollowerInvitation.Status.PENDING
        invitation.ensure_token()
        invitation.save()

        invite_url = request.build_absolute_uri(
            reverse("follower_register", kwargs={"token": invitation.token})
        )
        send_mail(
            subject=(
                f"Reminder: {invitation.member.callsign} invited you "
                "to Radio Outdoors"
            ),
            message=_public_message(
                f"{invitation.member.public_name} "
                f"({invitation.member.callsign}) invited you to follow "
                "their Radio Outdoors Adventures.\n\n"
                f"Create your Follower account:\n{invite_url}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
            fail_silently=True,
        )
        messages.success(request, "Invitation resent.")
        return redirect("follower_management")

    return HttpResponseForbidden("Unknown invitation action.")


@login_required
def following_list(request):
    relationships = (
        FollowRelationship.objects.filter(follower=request.user)
        .filter(member__user__is_active=True)
        .exclude(status=FollowRelationship.Status.BLOCKED)
        .select_related("member", "member__user")
        .order_by("member__callsign")
    )
    return render(
        request,
        "members/following_list.html",
        {"relationships": relationships},
    )


@verified_member_required
@require_POST
def respond_to_follow(request, relationship_id, action):
    relationship = get_object_or_404(
        FollowRelationship.objects.select_related(
            "member", "member__user", "follower"
        ),
        pk=relationship_id,
        member__user=request.user,
    )

    actions = {
        "approve": FollowRelationship.Status.APPROVED,
        "decline": FollowRelationship.Status.DECLINED,
        "block": FollowRelationship.Status.BLOCKED,
        "remove": FollowRelationship.Status.DECLINED,
        "unblock": FollowRelationship.Status.DECLINED,
    }

    if action not in actions:
        return HttpResponseForbidden("Unknown follower action.")

    relationship.status = actions[action]
    relationship.responded_at = timezone.now()
    relationship.save(
        update_fields=["status", "responded_at", "updated_at"]
    )

    # Approval email takes the Follower directly back to the Member page,
    # where public Adventures are listed.
    if (
        action == "approve"
        and relationship.follower.email
    ):
        member_url = _absolute_url(
            request,
            "member_detail",
            callsign=relationship.member.callsign,
        )
        send_mail(
            subject=(
                f"{relationship.member.callsign} approved your "
                "Radio Outdoors follow request"
            ),
            message=_public_message(
                f"{relationship.member.public_name} "
                f"({relationship.member.callsign}) approved your "
                "follow request.\n\n"
                f"View the Member and Adventures:\n{member_url}"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[relationship.follower.email],
            fail_silently=True,
        )

    messages.success(request, "Follower status updated.")
    return redirect("follower_management")


@login_required
@require_POST
def unfollow_member(request, relationship_id):
    relationship = get_object_or_404(
        FollowRelationship,
        pk=relationship_id,
        follower=request.user,
    )
    relationship.delete()
    messages.success(request, "You stopped following that Member.")
    return redirect("following_list")
