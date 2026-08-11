from django.urls import path

from .account_views import (
    account_home,
    deactivate_account,
    follower_register,
    member_welcome,
    register,
)
from .password_views import password_requirement_status
from .manual_verification_views import (
    manual_verification_request,
    manual_verification_status,
)


urlpatterns = [
    path("register/", register, name="register"),
    path(
        "password-requirements/",
        password_requirement_status,
        name="password_requirement_status",
    ),
    path("welcome/", member_welcome, name="member_welcome"),
    path("deactivate/", deactivate_account, name="deactivate_account"),
    path("verification/", manual_verification_status, name="manual_verification_status"),
    path("verification/request/", manual_verification_request, name="manual_verification_request"),
    path(
        "follower/register/<str:token>/",
        follower_register,
        name="follower_register",
    ),
    path("", account_home, name="account_home"),
]
