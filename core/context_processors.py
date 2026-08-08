from django.conf import settings


from .auth import is_verified_member


def account_roles(request):
    user = request.user
    verified_member = is_verified_member(user)
    pending_member = False
    header_identity = {
        "full": "Visitor",
        "compact": "Visitor",
    }

    if user.is_authenticated:
        profile = getattr(user, "member_profile", None)
        if verified_member and profile:
            first_name = user.first_name.strip() or profile.qrz_first_name.strip()
            header_identity = {
                "full": (
                    f"{profile.callsign} - {first_name}"
                    if first_name
                    else profile.callsign
                ),
                "compact": profile.callsign,
            }
        elif profile and profile.callsign and not user.is_staff:
            pending_member = True
            name = profile.display_name.strip() or user.get_full_name().strip() or profile.callsign
            header_identity = {
                "full": f"Pending — {name}",
                "compact": f"Pending — {profile.callsign}",
            }
        else:
            name = (
                user.first_name.strip()
                or user.get_full_name().strip()
                or user.email.strip()
                or user.username
            )
            role = "Staff" if user.is_staff else "Follower"
            compact_name = user.first_name.strip() or user.username
            header_identity = {
                "full": f"{name} - {role}",
                "compact": f"{compact_name} · {role}",
            }

    return {
        "is_verified_member": verified_member,
        "is_pending_member": pending_member,
        "header_identity": header_identity,
    }


def google_maps(request):
    return {
        "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
    }
