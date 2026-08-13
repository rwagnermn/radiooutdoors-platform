from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core.views import about, home, learn, location_detail, location_list, map_explorer
from core.recovery_views import (
    RadioOutdoorsPasswordResetCompleteView,
    RadioOutdoorsPasswordResetConfirmView,
    RadioOutdoorsPasswordResetDoneView,
    RadioOutdoorsPasswordResetView,
)
from core.moderated_media import serve_moderated_media
from core.pin_views import edit_owned_pin_position
from core.sms_views import sms_recovery_reset, sms_recovery_send, sms_recovery_start, sms_recovery_verify

urlpatterns = [
    path("", include("core.policy_urls")),
    path("media/<path:path>", serve_moderated_media, name="moderated_media"),
    path("", include("core.identity_urls")),
    path("", home, name="home"),

    path("locations/", location_list, name="locations"),
    path("locations/<int:location_id>/", location_detail, name="location_detail"),
    path("map/", map_explorer, name="map_explorer"),
    path(
        "map/pins/<str:record_type>/<int:record_id>/edit/",
        edit_owned_pin_position,
        name="edit_owned_pin_position",
    ),

    path("adventures/", include("adventures.urls")),
    path("accounts/", include("core.account_urls")),
    path(
        "accounts/recovery/",
        RadioOutdoorsPasswordResetView.as_view(),
        name="account_recovery",
    ),
    path(
        "accounts/recovery/sent/",
        RadioOutdoorsPasswordResetDoneView.as_view(),
        name="account_recovery_done",
    ),
    path("accounts/recovery/sms/", sms_recovery_start, name="sms_recovery_start"),
    path("accounts/recovery/sms/send/", sms_recovery_send, name="sms_recovery_send"),
    path("accounts/recovery/sms/verify/", sms_recovery_verify, name="sms_recovery_verify"),
    path("accounts/recovery/sms/reset/", sms_recovery_reset, name="sms_recovery_reset"),
    path(
        "accounts/recovery/<uidb64>/<token>/",
        RadioOutdoorsPasswordResetConfirmView.as_view(),
        name="account_recovery_confirm",
    ),
    path(
        "accounts/recovery/complete/",
        RadioOutdoorsPasswordResetCompleteView.as_view(),
        name="account_recovery_complete",
    ),
    path("accounts/", include("django.contrib.auth.urls")),

    path("members/", include("core.member_urls")),
    path("staff/", include("core.admin_urls")),
    path("learn/", learn, name="learn"),
    path("about/", about, name="about"),

    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

