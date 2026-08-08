import logging
from datetime import timedelta
from io import BytesIO

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import (
    DefaultLocationImage, Location, MemberProfile, Photo,
    PhotoModerationActionAudit,
)
from .photo_moderation import (
    moderate_default_location_image, moderate_location_photo,
    moderate_photo, moderate_profile_photo,
)


logger = logging.getLogger(__name__)
RESTRICTED_CATEGORIES = {"sexual/minors", "suspected-csam"}
SEVERE_CATEGORIES = RESTRICTED_CATEGORIES
STATUS_FILTERS = {"all", "pending", "review", "rejected", "safe", "failed"}
REJECTION_REASONS = (
    ("community_standards", "Does not meet community standards"),
    ("sexual", "Nudity or sexual content"),
    ("minor_safety", "Suspected minor-safety concern"),
    ("graphic_violence", "Graphic violence or gore"),
    ("hate_extremist", "Hate or extremist content"),
    ("self_harm", "Self-harm content"),
    ("illegal_activity", "Illegal activity or drug promotion"),
    ("harassment", "Harassment or threatening content"),
    ("spam", "Unrelated image or spam"),
    ("privacy", "Personal information or privacy concern"),
    ("copyright", "Copyright or ownership concern"),
    ("invalid", "Invalid, corrupt, or unsupported image"),
    ("duplicate", "Duplicate photo"),
    ("scan_failed", "Moderation could not be completed"),
    ("other", "Other"),
)
REJECTION_REASON_LABELS = dict(REJECTION_REASONS)


TARGETS = {
    "photo": {
        "model": Photo, "image": "image", "status": "moderation_status",
        "reason": "moderation_reason", "categories": "moderation_categories",
        "provider": "moderation_provider", "model_field": "moderation_provider_model",
        "decision": "automated_decision", "reviewer": "reviewed_by",
        "reviewed_at": "reviewed_at", "reject_code": "rejection_reason_code",
        "reject_explanation": "rejection_explanation", "scanner": moderate_photo,
    },
    "location": {
        "model": Location, "image": "photo", "status": "photo_moderation_status",
        "reason": "photo_moderation_reason", "categories": "photo_moderation_categories",
        "provider": "photo_moderation_provider", "model_field": "photo_moderation_provider_model",
        "decision": "photo_automated_decision", "reviewer": "photo_reviewed_by",
        "reviewed_at": "photo_reviewed_at", "reject_code": "photo_rejection_reason_code",
        "reject_explanation": "photo_rejection_explanation", "scanner": moderate_location_photo,
    },
    "profile": {
        "model": MemberProfile, "image": "profile_photo", "status": "profile_photo_moderation_status",
        "reason": "profile_photo_moderation_reason", "categories": "profile_photo_moderation_categories",
        "provider": "profile_photo_moderation_provider", "model_field": "profile_photo_moderation_provider_model",
        "decision": "profile_photo_automated_decision", "reviewer": "profile_photo_reviewed_by",
        "reviewed_at": "profile_photo_reviewed_at", "reject_code": "profile_photo_rejection_reason_code",
        "reject_explanation": "profile_photo_rejection_explanation", "scanner": moderate_profile_photo,
    },
    "default": {
        "model": DefaultLocationImage, "image": "image", "status": "moderation_status",
        "reason": "moderation_reason", "categories": "moderation_categories",
        "provider": "moderation_provider", "model_field": "moderation_provider_model",
        "decision": "automated_decision", "reviewer": "reviewed_by",
        "reviewed_at": "reviewed_at", "reject_code": "rejection_reason_code",
        "reject_explanation": "rejection_explanation", "scanner": moderate_default_location_image,
    },
}


def _parse_token(token):
    try:
        kind, raw_pk = token.split(":", 1)
        if kind not in TARGETS:
            raise ValueError
        return kind, int(raw_pk)
    except (AttributeError, TypeError, ValueError):
        raise Http404 from None


def _target(kind, pk):
    if kind not in TARGETS:
        raise Http404
    return get_object_or_404(TARGETS[kind]["model"], pk=pk)


def _value(kind, obj, key):
    return getattr(obj, TARGETS[kind][key])


def _association(kind, obj):
    if kind == "photo":
        adventure = obj.journal_entry.adventure
        return (
            f"{adventure.title} / {obj.journal_entry.title}",
            reverse("journal_entry_detail", args=[obj.journal_entry_id]),
            adventure.owner,
            getattr(getattr(adventure.owner, "member_profile", None), "callsign", ""),
            obj.created_at,
        )
    if kind == "location":
        return obj.name, reverse("location_detail", args=[obj.pk]), "Location contributor", "", obj.updated_at
    if kind == "profile":
        return "Member profile", reverse("member_detail", args=[obj.callsign]), obj.user, obj.callsign, obj.updated_at
    return obj.get_key_display(), reverse("default_location_image_detail", args=[obj.pk]), "Staff", "", obj.updated_at


def _status_label(kind, obj):
    status = _value(kind, obj, "status")
    decision = _value(kind, obj, "decision")
    if decision == "scan_failed":
        return "Scan failed"
    if status == "pending":
        return "Pending scan"
    if status == "review":
        return "Needs review"
    if status == "rejected":
        return "Rejected"
    return "Approved automatically" if decision == "safe" else "Approved"


def _row(kind, obj):
    association, association_url, uploader, callsign, uploaded = _association(kind, obj)
    categories = list(_value(kind, obj, "categories") or [])
    restricted = bool(set(categories).intersection(RESTRICTED_CATEGORIES))
    status_label = _status_label(kind, obj)
    if (
        status_label == "Pending scan"
        and uploaded
        and uploaded <= timezone.now() - timedelta(minutes=15)
    ):
        status_label = "Pending scan — stuck"
    return {
        "kind": kind, "object": obj, "token": f"{kind}:{obj.pk}",
        "status": status_label, "association": association,
        "association_url": association_url, "uploader": uploader, "callsign": callsign,
        "uploaded": uploaded, "categories": ", ".join(categories),
        "category_list": categories, "restricted": restricted,
        "provider": _value(kind, obj, "provider"),
        "provider_model": _value(kind, obj, "model_field"),
        "automated_decision": _value(kind, obj, "decision"),
        "thumbnail_url": reverse("photo_moderation_thumbnail", args=[kind, obj.pk]),
        "detail_url": reverse("photo_moderation_detail", args=[kind, obj.pk]),
    }


def _queue_rows(status_filter="all"):
    querysets = (
        ("photo", Photo.objects.exclude(moderation_status="approved").select_related("journal_entry__adventure__owner__member_profile")),
        ("location", Location.objects.exclude(photo="").exclude(photo_moderation_status="approved")),
        ("profile", MemberProfile.objects.exclude(profile_photo="").exclude(profile_photo_moderation_status="approved").select_related("user")),
        ("default", DefaultLocationImage.objects.exclude(image="").exclude(moderation_status="approved")),
    )
    rows = [_row(kind, obj) for kind, queryset in querysets for obj in queryset]
    rows.sort(key=lambda row: row["uploaded"], reverse=True)
    if status_filter == "safe":
        return [row for row in rows if _is_safe_recommendation(row)]
    if status_filter == "failed":
        return [row for row in rows if row["automated_decision"] == "scan_failed"]
    if status_filter != "all":
        return [row for row in rows if _value(row["kind"], row["object"], "status") == status_filter]
    return rows


def _rows_for_tokens(tokens, status_filter="all"):
    wanted = set(tokens)
    return [row for row in _queue_rows(status_filter) if row["token"] in wanted]


def _is_safe_recommendation(row):
    return bool(
        row["automated_decision"] == "safe" and row["provider"]
        and row["provider_model"] and not row["category_list"]
        and _value(row["kind"], row["object"], "status") not in {"approved", "rejected"}
    )


def _valid_rejection(request):
    code = request.POST.get("rejection_reason", "")
    explanation = request.POST.get("rejection_explanation", "").strip()
    if code not in REJECTION_REASON_LABELS:
        return None, None, "Choose a reason for rejection."
    if code == "other" and not explanation:
        return None, None, "Explain the Other rejection reason."
    return code, explanation, ""


def _record_audit(request, *, action, source, scope, requested, succeeded, failed):
    return PhotoModerationActionAudit.objects.create(
        actor=request.user, action=action, decision_source=source, scope=scope,
        requested_target_ids=requested, successful_target_ids=succeeded,
        failed_targets=failed,
    )


def _apply_decision(request, token, action, code="", explanation=""):
    kind, pk = _parse_token(token)
    obj, config = _target(kind, pk), TARGETS[kind]
    setattr(obj, config["status"], "approved" if action == "approve" else "rejected")
    setattr(obj, config["reviewer"], request.user)
    setattr(obj, config["reviewed_at"], timezone.now())
    fields = [config["status"], config["reviewer"], config["reviewed_at"]]
    if action == "reject":
        setattr(obj, config["reject_code"], code)
        setattr(obj, config["reject_explanation"], explanation[:240])
        setattr(obj, config["reason"], REJECTION_REASON_LABELS[code])
        fields += [config["reject_code"], config["reject_explanation"], config["reason"]]
    obj.save(update_fields=fields)


def _image_response(kind, obj, *, thumbnail=False):
    if set(_value(kind, obj, "categories") or []).intersection(RESTRICTED_CATEGORIES):
        raise Http404
    image_field = getattr(obj, TARGETS[kind]["image"])
    try:
        image_field.open("rb")
        with Image.open(image_field) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((220, 160) if thumbnail else (900, 700))
            output = BytesIO()
            image.save(output, "JPEG", quality=78)
    except (FileNotFoundError, OSError, UnidentifiedImageError) as exc:
        raise Http404 from exc
    finally:
        try:
            image_field.close()
        except Exception:
            pass
    output.seek(0)
    response = FileResponse(output, content_type="image/jpeg")
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@staff_member_required
def photo_moderation_thumbnail(request, kind, pk):
    return _image_response(kind, _target(kind, pk), thumbnail=True)


@staff_member_required
def photo_moderation_preview_file(request, kind, pk):
    obj = _target(kind, pk)
    categories = set(_value(kind, obj, "categories") or [])
    if categories.intersection(RESTRICTED_CATEGORIES):
        raise Http404
    return _image_response(kind, obj)


@staff_member_required
def photo_moderation_detail(request, kind, pk):
    obj = _target(kind, pk)
    row = _row(kind, obj)
    return render(request, "admin_tools/photo_moderation_detail.html", {
        "row": row, "rejection_reasons": REJECTION_REASONS,
        "preview_url": reverse("photo_moderation_preview_file", args=[kind, pk]),
    })


@staff_member_required
def photo_moderation_queue(request):
    status_filter = request.GET.get("status", "all")
    if status_filter not in STATUS_FILTERS:
        status_filter = "all"
    all_rows = _queue_rows(status_filter)
    page_obj = Paginator(all_rows, 50).get_page(request.GET.get("page"))
    return render(request, "admin_tools/photo_moderation_queue.html", {
        "rows": page_obj.object_list, "page_obj": page_obj,
        "status_filter": status_filter, "rejection_reasons": REJECTION_REASONS,
        "safe_count_on_page": sum(_is_safe_recommendation(row) for row in page_obj.object_list),
    })


@staff_member_required
@require_POST
def photo_moderation_bulk_preview(request):
    action = request.POST.get("bulk_action", "")
    status_filter = request.POST.get("status_filter", "all")
    if action not in {"approve", "reject", "retry", "approve_safe"}:
        raise Http404
    if status_filter not in STATUS_FILTERS:
        status_filter = "all"
    if action == "approve_safe":
        page_rows = Paginator(_queue_rows(status_filter), 50).get_page(request.POST.get("page")).object_list
        rows = [row for row in page_rows if _is_safe_recommendation(row)]
    else:
        tokens = list(dict.fromkeys(request.POST.getlist("selected")))
        rows = _rows_for_tokens(tokens, status_filter)
    if not rows:
        messages.warning(request, "No eligible photos were selected.")
        return redirect("photo_moderation_queue")
    if action == "retry":
        return _bulk_retry(request, rows)
    return render(request, "admin_tools/photo_moderation_bulk_confirm.html", {
        "rows": rows, "count": len(rows), "bulk_action": action,
        "status_filter": status_filter, "approve_action": action in {"approve", "approve_safe"},
        "safe_action": action == "approve_safe", "rejection_reasons": REJECTION_REASONS,
    })


def _bulk_retry(request, rows):
    succeeded, failed = [], []
    for row in rows:
        try:
            TARGETS[row["kind"]]["scanner"](row["object"])
            succeeded.append(row["token"])
        except Exception as exc:
            logger.warning("Moderation retry failed actor_id=%s target=%s exception=%s", request.user.pk, row["token"], type(exc).__name__)
            failed.append({"target": row["token"], "error": "Retry could not be started."})
    _record_audit(request, action="retry", source="bulk-manual", scope="page", requested=[r["token"] for r in rows], succeeded=succeeded, failed=failed)
    messages.info(request, f"Moderation retry completed for {len(succeeded)} photo(s).")
    return redirect("photo_moderation_queue")


@staff_member_required
@require_POST
def photo_moderation_bulk_apply(request):
    action_name = request.POST.get("bulk_action", "")
    if action_name not in {"approve", "reject", "approve_safe"}:
        raise Http404
    action = "approve" if action_name in {"approve", "approve_safe"} else "reject"
    requested = list(dict.fromkeys(request.POST.getlist("selected")))
    if not requested:
        messages.warning(request, "No photos remain in this batch.")
        return redirect("photo_moderation_queue")
    code = explanation = ""
    if action == "reject":
        code, explanation, error = _valid_rejection(request)
        if error:
            messages.error(request, error)
            rows = _rows_for_tokens(requested)
            return render(request, "admin_tools/photo_moderation_bulk_confirm.html", {
                "rows": rows, "count": len(rows), "bulk_action": action_name,
                "status_filter": request.POST.get("status_filter", "all"),
                "approve_action": False, "safe_action": False,
                "rejection_reasons": REJECTION_REASONS, "form_error": error,
            })
    safe_rows = {row["token"]: row for row in _queue_rows("all")}
    succeeded, failed = [], []
    for token in requested:
        try:
            if action_name == "approve_safe" and not _is_safe_recommendation(safe_rows.get(token, {})):
                raise ValueError("No longer safe-eligible")
            _apply_decision(request, token, action, code, explanation)
            succeeded.append(token)
        except Exception as exc:
            logger.warning("Bulk photo moderation target failed actor_id=%s target=%s exception=%s", request.user.pk, token, type(exc).__name__)
            failed.append({"target": token, "error": "Could not process this photo."})
    _record_audit(request, action=action, source="bulk-safe-recommendation" if action_name == "approve_safe" else "bulk-manual", scope="page", requested=requested, succeeded=succeeded, failed=failed)
    messages.success(request, f"{len(succeeded)} photo(s) marked {action}d.")
    if failed:
        messages.error(request, "Could not process: " + ", ".join(item["target"] for item in failed))
    return redirect("photo_moderation_queue")


@staff_member_required
@require_POST
def photo_moderation_action(request, kind, pk, action):
    obj, config, token = _target(kind, pk), TARGETS[kind], f"{kind}:{pk}"
    if action not in {"approve", "reject", "remove", "retry"}:
        raise Http404
    if action == "retry":
        config["scanner"](obj)
        _record_audit(request, action="retry", source="individual-manual", scope="individual", requested=[token], succeeded=[token], failed=[])
        messages.info(request, "Moderation retry completed.")
        return redirect("photo_moderation_queue")
    if action == "reject":
        code, explanation, error = _valid_rejection(request)
        if error:
            messages.error(request, error)
            return redirect("photo_moderation_detail", kind=kind, pk=pk)
        _apply_decision(request, token, "reject", code, explanation)
    elif action == "approve":
        _apply_decision(request, token, "approve")
    else:
        image = getattr(obj, config["image"])
        if image:
            image.delete(save=False)
        if kind == "photo":
            obj.delete()
        else:
            setattr(obj, config["image"], "")
            setattr(obj, config["status"], "rejected")
            obj.save(update_fields=[config["image"], config["status"]])
    _record_audit(request, action=action, source="individual-manual", scope="individual", requested=[token], succeeded=[token], failed=[])
    messages.success(request, f"Photo action completed: {action}.")
    return redirect("photo_moderation_queue")
