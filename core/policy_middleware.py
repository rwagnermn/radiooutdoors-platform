from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse
from urllib.parse import urlencode

from .policy_acceptance import requires_policy_acceptance


class PolicyAcceptanceMiddleware:
    """Gate existing Member activity until the current material bundle is accepted."""

    EXEMPT_NAMES = {
        "terms_of_use", "privacy_policy", "community_standards", "copyright_policy",
        "policy_acceptance_required", "policy_acceptance_declined",
        "login", "logout", "password_change", "password_change_done",
        "account_recovery", "account_recovery_done", "account_recovery_confirm",
        "account_recovery_complete", "moderated_media",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            name = resolve(request.path_info).url_name
        except Resolver404:
            name = ""
        if (
            request.user.is_authenticated
            and name not in self.EXEMPT_NAMES
            and requires_policy_acceptance(request.user)
        ):
            target = reverse("policy_acceptance_required")
            return redirect(f"{target}?{urlencode({'next': request.get_full_path()})}")
        return self.get_response(request)
