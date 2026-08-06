from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .member_forms import MemberDeleteForm, MemberProfileForm
from .models import MemberCallsignAudit, MemberProfile
from .qrz_service import QRZError, lookup_callsign


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


def member_list(request):
    members = _members().filter(
        profile_is_public=True,
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
    profile = get_object_or_404(_members(), callsign__iexact=callsign)
    owner = request.user.is_authenticated and request.user == profile.user

    if (
        not profile.profile_is_public
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
            "adventures": adventures,
            "is_owner": owner,
        },
    )


@login_required
def my_member_profile(request):
    profile, _ = MemberProfile.objects.get_or_create(user=request.user)
    qrz_preview = None

    if request.method == "POST":
        form = MemberProfileForm(
            request.POST,
            instance=profile,
            user=request.user,
        )
        action = request.POST.get("action", "save")

        if action == "verify":
            callsign = request.POST.get("callsign", "").strip().upper()
            try:
                result = lookup_callsign(callsign)
                qrz_preview = result
                form.data = form.data.copy()
                form.data["callsign"] = result.callsign

                if not form.data.get("first_name"):
                    form.data["first_name"] = result.first_name
                if not form.data.get("last_name"):
                    form.data["last_name"] = result.last_name
                if not form.data.get("display_name"):
                    form.data["display_name"] = " ".join(
                        x for x in [result.first_name, result.last_name] if x
                    )
                if not form.data.get("home_city"):
                    form.data["home_city"] = result.city
                if not form.data.get("home_state"):
                    form.data["home_state"] = result.state
                if not form.data.get("home_country"):
                    form.data["home_country"] = result.country

                messages.success(
                    request,
                    f"{result.callsign} was found in QRZ. Review and save.",
                )
            except QRZError as exc:
                messages.error(request, str(exc))

        elif form.is_valid():
            entered_call = form.cleaned_data["callsign"]
            old_call = profile.callsign

            try:
                result = lookup_callsign(entered_call)
            except QRZError as exc:
                messages.error(
                    request,
                    f"Profile not saved. QRZ verification failed: {exc}",
                )
            else:
                with transaction.atomic():
                    if old_call and old_call.upper() != result.callsign:
                        MemberCallsignAudit.objects.create(
                            member=profile,
                            old_callsign=old_call,
                            new_callsign=result.callsign,
                            changed_by=request.user,
                        )

                    saved = form.save(commit=False)
                    saved.callsign = result.callsign
                    saved.callsign_verified = True
                    saved.qrz_verified_at = timezone.now()
                    saved.qrz_first_name = result.first_name
                    saved.qrz_last_name = result.last_name
                    saved.qrz_city = result.city
                    saved.qrz_state = result.state
                    saved.qrz_country = result.country
                    saved.qrz_grid = result.grid
                    saved.qrz_license_class = result.license_class
                    saved.qrz_expiration = result.expires
                    saved.save()

                    request.user.first_name = form.cleaned_data[
                        "first_name"
                    ].strip()
                    request.user.last_name = form.cleaned_data[
                        "last_name"
                    ].strip()
                    request.user.email = form.cleaned_data["email"].strip()
                    request.user.save(
                        update_fields=["first_name", "last_name", "email"]
                    )

                messages.success(
                    request,
                    f"Member profile saved and {result.callsign} verified.",
                )
                return redirect("member_detail", callsign=saved.callsign)
    else:
        form = MemberProfileForm(instance=profile, user=request.user)

    return render(
        request,
        "members/member_form.html",
        {
            "form": form,
            "profile": profile,
            "qrz_preview": qrz_preview,
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
        {"members": members},
    )


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
