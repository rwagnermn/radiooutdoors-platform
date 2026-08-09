from django.urls import path

from .policy_views import (
    community_standards, copyright_policy, policy_acceptance_declined,
    policy_acceptance_required, privacy_policy, terms_of_use,
)


urlpatterns = [
    path("terms/", terms_of_use, name="terms_of_use"),
    path("privacy/", privacy_policy, name="privacy_policy"),
    path("community-standards/", community_standards, name="community_standards"),
    path("copyright/", copyright_policy, name="copyright_policy"),
    path("accounts/policy-acceptance/", policy_acceptance_required, name="policy_acceptance_required"),
    path("accounts/policy-acceptance/declined/", policy_acceptance_declined, name="policy_acceptance_declined"),
]
