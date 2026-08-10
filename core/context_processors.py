from django.conf import settings


from .auth import is_verified_member
from .policies import (
    COMMUNITY_VERSION,
    POLICY_EFFECTIVE_DATE,
    PRIVACY_VERSION,
    TERMS_VERSION,
)


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
        "is_development": settings.DEBUG,
    }


def google_maps(request):
    return {
        "google_maps_api_key": settings.GOOGLE_MAPS_API_KEY,
    }


def organizational_emails(request):
    """Expose only the public organizational address to templates."""
    return {
        "radio_outdoors_contact_email": settings.RADIO_OUTDOORS_CONTACT_EMAIL,
    }


def current_policy_metadata(request):
    """Expose authoritative display metadata; submitted versions are never trusted."""
    return {
        "policy_effective_date": POLICY_EFFECTIVE_DATE,
        "terms_version": TERMS_VERSION,
        "privacy_version": PRIVACY_VERSION,
        "community_version": COMMUNITY_VERSION,
    }
