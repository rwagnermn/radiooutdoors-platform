import mimetypes

from django.db import models
from django.http import FileResponse, Http404

from .models import DefaultLocationImage, Location, MemberProfile, Photo
from .photo_moderation_views import SEVERE_CATEGORIES
from .location_privacy import can_view_location


def _can_view(request, status, categories, owner=None):
    if status == "approved":
        return True
    if status == "rejected":
        return False
    if request.user.is_authenticated and owner is not None and request.user == owner:
        return True
    # Staff use the controlled, non-indexable moderation preview endpoints.
    return False


def serve_moderated_media(request, path):
    """Deliver uploaded public images only when their moderation state permits it."""
    photo = (
        Photo.objects.filter(models.Q(image=path) | models.Q(web_image=path) | models.Q(thumbnail_image=path))
        .select_related("journal_entry__adventure__owner")
        .first()
    )
    if photo:
        allowed = _can_view(
            request, photo.moderation_status, photo.moderation_categories,
            owner=photo.journal_entry.adventure.owner,
        )
        if photo.web_image.name == path:
            image = photo.web_image
        elif photo.thumbnail_image.name == path:
            image = photo.thumbnail_image
        else:
            image = photo.image
    else:
        location = Location.objects.filter(photo=path).first()
        if location:
            allowed = can_view_location(request.user, location) and _can_view(
                request,
                location.photo_moderation_status,
                location.photo_moderation_categories,
                owner=location.created_by,
            )
            image = location.photo
        else:
            profile = MemberProfile.objects.filter(profile_photo=path).select_related("user").first()
            if profile:
                allowed = _can_view(
                    request, profile.profile_photo_moderation_status,
                    profile.profile_photo_moderation_categories, owner=profile.user,
                )
                image = profile.profile_photo
            else:
                default_image = DefaultLocationImage.objects.filter(image=path).first()
                if not default_image:
                    raise Http404
                allowed = _can_view(
                    request, default_image.moderation_status,
                    default_image.moderation_categories,
                )
                image = default_image.image
    if not allowed:
        raise Http404
    try:
        image.open("rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404 from exc
    content_type = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
    return FileResponse(image, content_type=content_type)
