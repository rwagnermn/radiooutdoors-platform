from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden


def is_verified_member(user):
    """Return whether a user has an active, QRZ-verified Member identity."""
    if not user.is_authenticated or not user.is_active:
        return False

    try:
        profile = user.member_profile
    except AttributeError:
        return False

    return profile.has_valid_verification(allow_development=settings.DEBUG)


def verified_member_required(view_func):
    """Require the shared verified-Member rule for a view."""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_verified_member(request.user):
            return HttpResponseForbidden(
                "A verified Radio Outdoors Member account is required."
            )
        return view_func(request, *args, **kwargs)

    return wrapped


def verified_member_or_staff_required(view_func):
    """Allow an active staff user or a verified Member."""
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_active or not (
            request.user.is_staff or is_verified_member(request.user)
        ):
            return HttpResponseForbidden(
                "A verified Radio Outdoors Member or staff account is required."
            )
        return view_func(request, *args, **kwargs)

    return wrapped
