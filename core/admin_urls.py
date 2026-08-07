from django.urls import path

from .default_image_views import (
    default_location_image_detail,
    default_location_image_edit,
    default_location_image_list,
    default_location_image_toggle,
)


urlpatterns = [
    path(
        "default-location-images/",
        default_location_image_list,
        name="default_location_image_list",
    ),
    path(
        "default-location-images/<int:image_id>/",
        default_location_image_detail,
        name="default_location_image_detail",
    ),
    path(
        "default-location-images/<int:image_id>/edit/",
        default_location_image_edit,
        name="default_location_image_edit",
    ),
    path(
        "default-location-images/<int:image_id>/toggle/",
        default_location_image_toggle,
        name="default_location_image_toggle",
    ),
]
