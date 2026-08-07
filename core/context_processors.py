from django.conf import settings


from .auth import is_verified_member


def account_roles(request):
    user = request.user
    verified_member = is_verified_member(user)
    header_identity = None

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
        else:
            name = (
                user.first_name.strip()
                or user.get_full_name().strip()
                or user.email.strip()
                or user.username
            )
            role = "Staff" if user.is_staff else "Follower"
            header_identity = {
                "full": f"{name} - {role}",
                "compact": f"{name} · {role}",
            }

    return {
        "is_verified_member": verified_member,
        "header_identity": header_identity,
    }


def google_maps(request):
    return {
        "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
    }
