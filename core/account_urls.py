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
from .sms_views import mobile_phone_send, mobile_phone_settings, mobile_phone_verify


urlpatterns = [
    path("register/", register, name="register"),
    path(
        "password-requirements/",
        password_requirement_status,
        name="password_requirement_status",
    ),
    path("welcome/", member_welcome, name="member_welcome"),
    path("deactivate/", deactivate_account, name="deactivate_account"),
    path("mobile/", mobile_phone_settings, name="mobile_phone_settings"),
    path("mobile/send/", mobile_phone_send, name="mobile_phone_send"),
    path("mobile/verify/", mobile_phone_verify, name="mobile_phone_verify"),
    path("verification/", manual_verification_status, name="manual_verification_status"),
    path("verification/request/", manual_verification_request, name="manual_verification_request"),
    path(
        "follower/register/<str:token>/",
        follower_register,
        name="follower_register",
    ),
    path("", account_home, name="account_home"),
]
