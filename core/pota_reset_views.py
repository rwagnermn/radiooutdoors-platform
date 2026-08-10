from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .pota_test_reset import CONFIRMATION_PHRASE, build_reset_preview, execute_reset


def _require_development_staff(request):
    if not settings.DEBUG:
        raise Http404
    if not request.user.is_staff:
        raise PermissionDenied


@login_required
@require_http_methods(["GET", "POST"])
def pota_test_reset(request):
    _require_development_staff(request)
    preview = build_reset_preview()
    if request.method == "POST":
        if request.POST.get("confirmation_phrase", "") != CONFIRMATION_PHRASE:
            return render(request, "admin_tools/pota_test_reset.html", {
                "preview": preview,
                "confirmation_phrase": CONFIRMATION_PHRASE,
                "error": "The confirmation phrase did not match. Nothing was deleted.",
            }, status=400)
        request.session["pota_reset_second_confirmation"] = True
        return render(request, "admin_tools/pota_test_reset_confirm.html", {
            "preview": preview,
            "confirmation_phrase": CONFIRMATION_PHRASE,
        })
    request.session.pop("pota_reset_second_confirmation", None)
    return render(request, "admin_tools/pota_test_reset.html", {
        "preview": preview,
        "confirmation_phrase": CONFIRMATION_PHRASE,
    })


@login_required
@require_http_methods(["POST"])
def pota_test_reset_execute(request):
    _require_development_staff(request)
    if not request.session.pop("pota_reset_second_confirmation", False):
        raise PermissionDenied
    try:
        result = execute_reset(actor=request.user)
    except Exception as exc:
        return render(request, "admin_tools/pota_test_reset_result.html", {
            "failed": True,
            "error_category": type(exc).__name__,
        }, status=500)
    return render(request, "admin_tools/pota_test_reset_result.html", {"result": result})
