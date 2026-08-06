from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core.views import about, home, learn, location_detail, location_list, map_explorer

urlpatterns = [
    path("", include("core.identity_urls")),
    path("", home, name="home"),

    path("locations/", location_list, name="locations"),
    path("locations/<int:location_id>/", location_detail, name="location_detail"),
    path("map/", map_explorer, name="map_explorer"),

    path("adventures/", include("adventures.urls")),
    path("accounts/", include("core.account_urls")),
    path("accounts/", include("django.contrib.auth.urls")),

    path("members/", include("core.member_urls")),
    path("learn/", learn, name="learn"),
    path("about/", about, name="about"),

    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

