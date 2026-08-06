from django.urls import path

from .follower_views import (
    follower_management,
    following_list,
    invitation_action,
    invite_follower,
    request_follow,
    respond_to_follow,
    unfollow_member,
)
from .member_views import (
    member_admin_list,
    member_delete,
    member_detail,
    member_list,
    member_toggle_active,
    my_member_profile,
)


urlpatterns = [
    path("", member_list, name="members"),
    path("profile/", my_member_profile, name="my_member_profile"),

    path("followers/", follower_management, name="follower_management"),
    path(
        "followers/invite/",
        invite_follower,
        name="invite_follower",
    ),
    path(
        "followers/invitations/<int:invitation_id>/<str:action>/",
        invitation_action,
        name="invitation_action",
    ),
    path("following/", following_list, name="following_list"),
    path(
        "follow/<str:callsign>/",
        request_follow,
        name="request_follow",
    ),
    path(
        "followers/<int:relationship_id>/<str:action>/",
        respond_to_follow,
        name="respond_to_follow",
    ),
    path(
        "following/<int:relationship_id>/remove/",
        unfollow_member,
        name="unfollow_member",
    ),

    path("manage/", member_admin_list, name="member_admin_list"),
    path(
        "manage/<int:member_id>/active/",
        member_toggle_active,
        name="member_toggle_active",
    ),
    path(
        "manage/<int:member_id>/delete/",
        member_delete,
        name="member_delete",
    ),

    path("<str:callsign>/", member_detail, name="member_detail"),
]
