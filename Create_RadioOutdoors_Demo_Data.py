import sys
from datetime import timedelta

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django
django.setup()

from django.contrib.auth.models import User
from django.utils import timezone

from core.models import FollowRelationship, MemberProfile


DEMO_USERS = [
    {
        "username": "demo_anna",
        "first_name": "Anna",
        "last_name": "Nelson",
        "email": "anna.demo@example.test",
        "callsign": "N0ANA",
        "display_name": "Anna Nelson",
        "city": "Duluth",
        "state": "MN",
        "country": "USA",
    },
    {
        "username": "demo_bob",
        "first_name": "Bob",
        "last_name": "Miller",
        "email": "bob.demo@example.test",
        "callsign": "K0BOB",
        "display_name": "Bob Miller",
        "city": "Cambridge",
        "state": "MN",
        "country": "USA",
    },
    {
        "username": "demo_carla",
        "first_name": "Carla",
        "last_name": "Reed",
        "email": "carla.demo@example.test",
        "callsign": "W0CAR",
        "display_name": "Carla Reed",
        "city": "St. Cloud",
        "state": "MN",
        "country": "USA",
    },
    {
        "username": "demo_dieter",
        "first_name": "Dieter",
        "last_name": "Koch",
        "email": "dieter.demo@example.test",
        "callsign": "DL7DEMO",
        "display_name": "Dieter Koch",
        "city": "Hamburg",
        "state": "",
        "country": "Germany",
    },
    {
        "username": "demo_emily",
        "first_name": "Emily",
        "last_name": "Hart",
        "email": "emily.demo@example.test",
        "callsign": "VE3EMI",
        "display_name": "Emily Hart",
        "city": "Thunder Bay",
        "state": "ON",
        "country": "Canada",
    },
    {
        "username": "demo_frank",
        "first_name": "Frank",
        "last_name": "Wilson",
        "email": "frank.demo@example.test",
        "callsign": "VK2FRK",
        "display_name": "Frank Wilson",
        "city": "Sydney",
        "state": "NSW",
        "country": "Australia",
    },
]


def ensure_demo_user(data):
    user, created = User.objects.get_or_create(
        username=data["username"],
        defaults={
            "first_name": data["first_name"],
            "last_name": data["last_name"],
            "email": data["email"],
            "is_active": True,
        },
    )

    user.first_name = data["first_name"]
    user.last_name = data["last_name"]
    user.email = data["email"]
    user.is_active = True
    user.set_password("RadioDemo123!")
    user.save()

    profile, _ = MemberProfile.objects.get_or_create(user=user)
    profile.callsign = data["callsign"]
    profile.display_name = data["display_name"]
    profile.home_city = data["city"]
    profile.home_state = data["state"]
    profile.home_country = data["country"]
    profile.profile_is_public = True
    profile.callsign_verified = False
    profile.bio = (
        "Demonstration profile created for Radio Outdoors alpha testing. "
        "This is not a real member account."
    )
    profile.save()

    return user, profile


def main():
    if len(sys.argv) < 2:
        print("Usage: python Create_RadioOutdoors_Demo_Data.py TARGET_CALLSIGN")
        print("Example: python Create_RadioOutdoors_Demo_Data.py W5RIK")
        raise SystemExit(2)

    target_call = sys.argv[1].strip().upper()

    try:
        target = MemberProfile.objects.select_related("user").get(
            callsign__iexact=target_call
        )
    except MemberProfile.DoesNotExist:
        print(f"No MemberProfile found for {target_call}.")
        raise SystemExit(1)

    created_profiles = []
    for item in DEMO_USERS:
        created_profiles.append(ensure_demo_user(item))

    statuses = [
        FollowRelationship.Status.APPROVED,
        FollowRelationship.Status.APPROVED,
        FollowRelationship.Status.PENDING,
        FollowRelationship.Status.PENDING,
        FollowRelationship.Status.DECLINED,
        FollowRelationship.Status.BLOCKED,
    ]

    now = timezone.now()

    for index, ((user, profile), status) in enumerate(
        zip(created_profiles, statuses)
    ):
        relationship, _ = FollowRelationship.objects.get_or_create(
            member=target,
            follower=user,
        )
        relationship.status = status
        relationship.responded_at = (
            now - timedelta(days=index)
            if status != FollowRelationship.Status.PENDING
            else None
        )
        relationship.save()

    # Give the target account examples of following other members.
    if target.user:
        for index, (_, profile) in enumerate(created_profiles[:3]):
            relationship, _ = FollowRelationship.objects.get_or_create(
                member=profile,
                follower=target.user,
            )
            relationship.status = (
                FollowRelationship.Status.APPROVED
                if index < 2
                else FollowRelationship.Status.PENDING
            )
            relationship.responded_at = (
                now if index < 2 else None
            )
            relationship.save()

    print("")
    print("Demo data created successfully.")
    print(f"Target member: {target.callsign}")
    print("Demo password for all demo accounts: RadioDemo123!")
    print("")
    print("Follower examples:")
    print("  2 Approved")
    print("  2 Pending")
    print("  1 Declined")
    print("  1 Blocked")
    print("")
    print("Open:")
    print("  http://127.0.0.1:8000/members/followers/")
    print("  http://127.0.0.1:8000/members/following/")


if __name__ == "__main__":
    main()
