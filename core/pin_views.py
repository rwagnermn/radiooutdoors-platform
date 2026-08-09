from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .auth import verified_member_or_staff_required
from .models import CoordinateChangeAudit, Location, OperatingLocation
from .pin_permissions import can_edit_location_pin, can_edit_operating_position_pin


def _coordinate(value, minimum, maximum):
    if value in (None, ""):
        return None
    try:
        result = Decimal(value).quantize(Decimal("0.000001"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError from exc
    if result < minimum or result > maximum:
        raise ValueError
    return result


def _safe_return(request, default):
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default


def _shared_location_warning(location, user):
    return location.adventures.exclude(owner=user).exists()


@verified_member_or_staff_required
@require_http_methods(["GET", "POST"])
def edit_owned_pin_position(request, record_type, record_id):
    if record_type == "location":
        record = get_object_or_404(Location, pk=record_id)
        allowed = can_edit_location_pin(request.user, record)
        required = False
        parent = None
        default_return = reverse("location_detail", args=[record.pk])
        title = f"Editing Location position: {record.name}"
    elif record_type == "operating_position":
        record = get_object_or_404(
            OperatingLocation.objects.select_related("location"), pk=record_id
        )
        allowed = can_edit_operating_position_pin(request.user, record)
        required = True
        parent = record.location
        default_return = reverse("location_detail", args=[record.location_id])
        title = f"Editing Operating Position: {record.name}"
    else:
        return HttpResponseBadRequest("Unknown map record type.")

    if not allowed:
        raise PermissionDenied("You are not authorized to reposition this pin.")

    return_url = _safe_return(request, default_return)
    form_error = ""
    if request.method == "POST":
        try:
            latitude = _coordinate(request.POST.get("latitude"), Decimal("-90"), Decimal("90"))
            longitude = _coordinate(request.POST.get("longitude"), Decimal("-180"), Decimal("180"))
        except ValueError:
            form_error = "Enter valid latitude and longitude coordinates."
        else:
            if (latitude is None) != (longitude is None):
                form_error = "Place both latitude and longitude coordinates."
            elif required and latitude is None:
                form_error = "Place a new pin before saving."

        if not form_error:
            with transaction.atomic():
                model = Location if record_type == "location" else OperatingLocation
                locked = model.objects.select_for_update().get(pk=record.pk)
                previous_latitude = locked.latitude
                previous_longitude = locked.longitude
                locked.latitude = latitude
                locked.longitude = longitude
                update_fields = ["latitude", "longitude", "updated_at"]
                locked.save(update_fields=update_fields)
                CoordinateChangeAudit.objects.create(
                    actor=request.user,
                    record_type=record_type,
                    record_id=locked.pk,
                    previous_latitude=previous_latitude,
                    previous_longitude=previous_longitude,
                    new_latitude=latitude,
                    new_longitude=longitude,
                    address_updated=False,
                )
            messages.success(request, "Pin position updated successfully.")
            return redirect(return_url)

    return render(request, "core/edit_pin_position.html", {
        "record": record,
        "record_type": record_type,
        "page_title": title,
        "required_coordinates": required,
        "parent_location": parent,
        "shared_use_warning": (
            record_type == "location"
            and _shared_location_warning(record, request.user)
        ),
        "return_url": return_url,
        "form_error": form_error,
    })
