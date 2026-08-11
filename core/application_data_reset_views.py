from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .application_data_reset import CONFIRMATION_PHRASE, reset_all_application_data


@require_http_methods(["GET", "POST"])
def reset_all_application_data_view(request):
    if not request.user.is_authenticated or not request.user.is_superuser:
        raise PermissionDenied

    if request.method == "GET":
        return render(request, "admin_tools/application_data_reset.html", {
            "confirmation_phrase": CONFIRMATION_PHRASE,
        })

    if request.POST.get("confirmation_phrase", "") != CONFIRMATION_PHRASE:
        return render(request, "admin_tools/application_data_reset.html", {
            "confirmation_phrase": CONFIRMATION_PHRASE,
            "error": "The confirmation text did not match. Nothing was deleted.",
        }, status=400)

    result = reset_all_application_data()
    return render(request, "admin_tools/application_data_reset_result.html", {"result": result})
