from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django import forms
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .policies import (
    COMMUNITY_VERSION, COPYRIGHT_VERSION, PRIVACY_VERSION, TERMS_VERSION,
    policy_page_context,
)
from .policy_acceptance import has_current_policy_acceptance, record_policy_acceptance


class ExistingAccountPolicyForm(forms.Form):
    policy_accepted = forms.BooleanField(
        required=True,
        error_messages={"required": "You must agree to the required policies to continue using Member features."},
        widget=forms.CheckboxInput(attrs={"data-policy-required": "true"}),
    )
    age_confirmed = forms.BooleanField(
        required=True,
        error_messages={"required": "You must confirm the age requirement to continue."},
        widget=forms.CheckboxInput(attrs={"data-policy-required": "true"}),
    )


def terms_of_use(request):
    return render(request, "policies/terms.html", policy_page_context("Terms of Use", TERMS_VERSION))


def privacy_policy(request):
    return render(request, "policies/privacy.html", policy_page_context("Privacy Policy", PRIVACY_VERSION))


def community_standards(request):
    return render(request, "policies/community.html", policy_page_context("Community and Photo Standards", COMMUNITY_VERSION))


def copyright_policy(request):
    return render(request, "policies/copyright.html", policy_page_context("Copyright/DMCA Policy", COPYRIGHT_VERSION))


def _safe_next(request):
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse("account_home")


@login_required
@require_http_methods(["GET", "POST"])
def policy_acceptance_required(request):
    if has_current_policy_acceptance(request.user):
        return redirect(_safe_next(request))
    previous = request.user.policy_acceptances.first()
    if request.method == "POST" and request.POST.get("action") == "decline":
        logout(request)
        return redirect("policy_acceptance_declined")
    form = ExistingAccountPolicyForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        record_policy_acceptance(
            request.user,
            registration_path="existing_account_reacceptance" if previous else "existing_account",
        )
        return redirect(_safe_next(request))
    return render(request, "policies/acceptance_required.html", {
        "form": form,
        "next": _safe_next(request),
        "previous_acceptance": previous,
        "current_versions": {
            "terms": TERMS_VERSION,
            "privacy": PRIVACY_VERSION,
            "community": COMMUNITY_VERSION,
        },
    })


def policy_acceptance_declined(request):
    return render(request, "policies/acceptance_declined.html")
