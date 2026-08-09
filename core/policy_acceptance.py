from .models import PolicyAcceptance
from .policies import CURRENT_ACCEPTANCE_VERSIONS, POLICY_LAUNCH_AT


def account_status_for(user):
    profile = getattr(user, "member_profile", None)
    if profile and profile.callsign_verified:
        return "verified"
    if profile and profile.callsign:
        return "pending"
    return "follower"


def has_current_policy_acceptance(user):
    if not user.is_authenticated:
        return False
    return user.policy_acceptances.filter(**CURRENT_ACCEPTANCE_VERSIONS).exists()


def requires_policy_acceptance(user):
    if not user.is_authenticated or not user.is_active:
        return False
    profile = getattr(user, "member_profile", None)
    if not profile or not profile.callsign:
        return False
    if has_current_policy_acceptance(user):
        return False
    # Existing accounts are gated once. A previous acceptance also makes a
    # later version change material for this account.
    return bool(
        user.policy_acceptances.exists()
        or user.date_joined <= POLICY_LAUNCH_AT
    )


def record_policy_acceptance(user, *, registration_path, account_status=None):
    return PolicyAcceptance.objects.create(
        user=user,
        account_identifier=(
            getattr(getattr(user, "member_profile", None), "callsign", "")
            or user.email
            or user.username
        )[:254],
        registration_path=registration_path,
        age_attested=True,
        account_status=account_status or account_status_for(user),
        **CURRENT_ACCEPTANCE_VERSIONS,
    )
