from django.urls import path

from .account_views import account_home, follower_register, member_welcome, register


urlpatterns = [
    path("register/", register, name="register"),
    path("welcome/", member_welcome, name="member_welcome"),
    path(
        "follower/register/<str:token>/",
        follower_register,
        name="follower_register",
    ),
    path("", account_home, name="account_home"),
]
