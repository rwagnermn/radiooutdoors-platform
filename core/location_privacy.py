from django.db.models import Q

from .models import Location


def location_access_q(user, prefix=""):
    public = Q(**{f"{prefix}visibility": Location.Visibility.PUBLIC})
    if not getattr(user, "is_authenticated", False):
        return public
    if user.is_staff:
        return Q()
    return public | Q(**{f"{prefix}created_by": user})


def visible_locations(user):
    return Location.objects.filter(location_access_q(user))


def can_view_location(user, location):
    if location is None:
        return False
    if location.visibility == Location.Visibility.PUBLIC:
        return True
    return bool(
        getattr(user, "is_authenticated", False)
        and (user.is_staff or location.created_by_id == user.pk)
    )


def can_manage_location(user, location):
    return bool(
        getattr(user, "is_authenticated", False)
        and user.is_active
        and (user.is_staff or location.created_by_id == user.pk)
    )


def mark_adventure_location_visibility(adventures, user):
    adventures = list(adventures)
    for adventure in adventures:
        adventure.can_view_location = can_view_location(user, adventure.location)
    return adventures
