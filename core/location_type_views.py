from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count
from django.db.models.functions import Lower
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .location_type_forms import LocationTypeForm
from .models import LocationType


@staff_member_required
def location_type_list(request):
    location_types = LocationType.objects.annotate(
        location_count=Count("locations")
    ).order_by(Lower("name"))
    return render(
        request,
        "admin_tools/location_type_list.html",
        {"location_types": location_types},
    )


@staff_member_required
def location_type_add(request):
    form = LocationTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        location_type = form.save()
        messages.success(request, f"Location Type “{location_type.name}” added.")
        return redirect("location_type_list")
    return render(request, "admin_tools/location_type_form.html", {"form": form, "location_type": None})


@staff_member_required
def location_type_edit(request, pk):
    location_type = get_object_or_404(LocationType, pk=pk)
    form = LocationTypeForm(request.POST or None, instance=location_type)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Location Type updated.")
        return redirect("location_type_list")
    return render(request, "admin_tools/location_type_form.html", {"form": form, "location_type": location_type})


@staff_member_required
@require_POST
def location_type_toggle(request, pk):
    location_type = get_object_or_404(LocationType, pk=pk)
    location_type.is_active = not location_type.is_active
    location_type.save(update_fields=["is_active"])
    messages.success(request, f"{location_type.name} is now {'Active' if location_type.is_active else 'Inactive'}.")
    return redirect("location_type_list")


@staff_member_required
@require_POST
def location_type_delete(request, pk):
    location_type = get_object_or_404(LocationType, pk=pk)
    usage_count = location_type.locations.count()
    if usage_count:
        messages.error(
            request,
            f"{location_type.name} cannot be deleted because {usage_count} Location{'s use' if usage_count != 1 else ' uses'} it. Deactivate it instead.",
        )
        return redirect("location_type_list")
    name = location_type.name
    try:
        location_type.delete()
    except ProtectedError:
        messages.error(request, f"{name} is in use and cannot be deleted. Deactivate it instead.")
    else:
        messages.success(request, f"Unused Location Type “{name}” deleted.")
    return redirect("location_type_list")
