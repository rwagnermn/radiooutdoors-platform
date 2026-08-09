"""Versioned Radio Outdoors policy metadata used by pages and acceptance records."""
from datetime import datetime, timezone


POLICY_EFFECTIVE_DATE = "August 9, 2026"
POLICY_LAUNCH_AT = datetime(2026, 8, 9, 0, 0, tzinfo=timezone.utc)

TERMS_VERSION = "alpha-2026-08-09"
PRIVACY_VERSION = "alpha-2026-08-09"
COMMUNITY_VERSION = "alpha-2026-08-09"
COPYRIGHT_VERSION = "alpha-2026-08-09"

CURRENT_ACCEPTANCE_VERSIONS = {
    "terms_version": TERMS_VERSION,
    "privacy_version": PRIVACY_VERSION,
    "community_version": COMMUNITY_VERSION,
}


def policy_page_context(title, version):
    return {
        "policy_title": title,
        "policy_version": version,
        "policy_effective_date": POLICY_EFFECTIVE_DATE,
        "policy_alpha": True,
    }
