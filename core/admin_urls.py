from django.urls import path

from .default_image_views import (
    default_location_image_detail,
    default_location_image_edit,
    default_location_image_list,
    default_location_image_toggle,
)
from .location_type_views import (
    location_type_add,
    location_type_delete,
    location_type_edit,
    location_type_list,
    location_type_toggle,
)
from .photo_moderation_views import (
    photo_moderation_action,
    photo_moderation_bulk_apply,
    photo_moderation_bulk_preview,
    photo_moderation_detail,
    photo_moderation_preview_file,
    photo_moderation_queue,
    photo_moderation_thumbnail,
    photo_quarantine_preview,
    photo_quarantine_restore,
    photo_quarantine_thumbnail,
)


urlpatterns = [
    path("photo-moderation/", photo_moderation_queue, name="photo_moderation_queue"),
    path("photo-moderation/bulk/preview/", photo_moderation_bulk_preview, name="photo_moderation_bulk_preview"),
    path("photo-moderation/bulk/apply/", photo_moderation_bulk_apply, name="photo_moderation_bulk_apply"),
    path("photo-moderation/quarantine/<int:pk>/thumbnail/", photo_quarantine_thumbnail, name="photo_quarantine_thumbnail"),
    path("photo-moderation/quarantine/<int:pk>/preview/", photo_quarantine_preview, name="photo_quarantine_preview"),
    path("photo-moderation/quarantine/<int:pk>/restore/", photo_quarantine_restore, name="photo_quarantine_restore"),
    path("photo-moderation/<str:kind>/<int:pk>/detail/", photo_moderation_detail, name="photo_moderation_detail"),
    path("photo-moderation/<str:kind>/<int:pk>/thumbnail/", photo_moderation_thumbnail, name="photo_moderation_thumbnail"),
    path("photo-moderation/<str:kind>/<int:pk>/preview/", photo_moderation_preview_file, name="photo_moderation_preview_file"),
    path("photo-moderation/<str:kind>/<int:pk>/<str:action>/", photo_moderation_action, name="photo_moderation_action"),
    path("location-types/", location_type_list, name="location_type_list"),
    path("location-types/add/", location_type_add, name="location_type_add"),
    path("location-types/<int:pk>/edit/", location_type_edit, name="location_type_edit"),
    path("location-types/<int:pk>/toggle/", location_type_toggle, name="location_type_toggle"),
    path("location-types/<int:pk>/delete/", location_type_delete, name="location_type_delete"),
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
