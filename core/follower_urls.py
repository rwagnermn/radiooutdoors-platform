from django.urls import path

from .follower_views import (
    follower_management,
    following_list,
    request_follow,
    respond_to_follow,
    unfollow_member,
)

urlpatterns = [
    path("followers/", follower_management, name="follower_management"),
    path("following/", following_list, name="following_list"),
    path("follow/<str:callsign>/", request_follow, name="request_follow"),
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
]
