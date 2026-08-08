from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .default_image_forms import DefaultLocationImageForm
from .models import DefaultLocationImage
from .photo_moderation import moderate_default_location_image


@staff_member_required
def default_location_image_list(request):
    return render(
        request,
        "admin_tools/default_location_image_list.html",
        {"default_images": DefaultLocationImage.objects.all()},
    )


@staff_member_required
def default_location_image_detail(request, image_id):
    return render(
        request,
        "admin_tools/default_location_image_detail.html",
        {"default_image": get_object_or_404(DefaultLocationImage, pk=image_id)},
    )


@staff_member_required
def default_location_image_edit(request, image_id):
    default_image = get_object_or_404(DefaultLocationImage, pk=image_id)
    if request.method == "POST":
        form = DefaultLocationImageForm(
            request.POST,
            request.FILES,
            instance=default_image,
        )
        if form.is_valid():
            saved = form.save()
            if request.FILES.get("image"):
                moderate_default_location_image(saved)
            messages.success(request, "Default Location Image saved.")
            return redirect("default_location_image_detail", image_id=default_image.pk)
    else:
        form = DefaultLocationImageForm(instance=default_image)
    return render(
        request,
        "admin_tools/default_location_image_form.html",
        {"default_image": default_image, "form": form},
    )


@staff_member_required
@require_POST
def default_location_image_toggle(request, image_id):
    default_image = get_object_or_404(DefaultLocationImage, pk=image_id)
    default_image.active = not default_image.active
    default_image.save(update_fields=["active", "updated_at"])
    messages.success(
        request,
        f"{default_image.get_key_display()} default "
        f"{'enabled' if default_image.active else 'disabled'}.",
    )
    return redirect("default_location_image_list")
