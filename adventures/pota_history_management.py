from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from core.auth import is_verified_member
from core.models import JournalEntry

from .pota_aggregation import (
    aggregate_pota_journals,
    eligible_pota_journal_imports,
    public_pota_leaders,
)


def _can_manage_history(user, entry):
    return bool(
        user.is_authenticated
        and user.is_active
        and (
            user.is_staff
            or (
                entry.adventure.owner_id == user.pk
                and is_verified_member(user)
            )
        )
    )


def recalculate_pota_rollups(entry):
    """Evaluate every dynamic roll-up affected by an activation deletion."""
    journal_totals = aggregate_pota_journals(
        JournalEntry.objects.filter(pk=entry.pk)
    )
    adventure_totals = aggregate_pota_journals(
        JournalEntry.objects.filter(adventure_id=entry.adventure_id)
    )
    list(public_pota_leaders())
    return journal_totals, adventure_totals


def _positive_integers(values):
    return [int(value) for value in values if value.isdigit() and int(value) > 0]


@login_required
def imported_pota_history(request, entry_id):
    entry = get_object_or_404(
        JournalEntry.objects.select_related("adventure", "adventure__owner"),
        pk=entry_id,
    )
    if not _can_manage_history(request.user, entry):
        return HttpResponseForbidden(
            "Only the Adventure owner or authorized staff can manage imported POTA History."
        )

    scoped_imports = eligible_pota_journal_imports().filter(
        journal_entry_id=entry.pk
    )

    if request.method == "POST":
        action = request.POST.get("delete_scope", "selected")
        with transaction.atomic():
            locked_entry = get_object_or_404(
                JournalEntry.objects.select_for_update().select_related(
                    "adventure", "adventure__owner"
                ),
                pk=entry_id,
            )
            if not _can_manage_history(request.user, locked_entry):
                return HttpResponseForbidden(
                    "Only the Adventure owner or authorized staff can manage imported POTA History."
                )
            candidates = eligible_pota_journal_imports().select_for_update().filter(
                journal_entry_id=locked_entry.pk
            )
            if action == "selected":
                candidates = candidates.filter(
                    pk__in=_positive_integers(
                        request.POST.getlist("selected_records")
                    )
                )
            elif action == "batch":
                if request.POST.get("confirm_bulk") != "yes":
                    messages.error(request, "Confirm the batch deletion before saving.")
                    return redirect("imported_pota_history", entry_id=entry.pk)
                batch_ids = _positive_integers([request.POST.get("batch_id", "")])
                candidates = candidates.filter(batch_id__in=batch_ids)
            elif action == "all":
                if request.POST.get("confirm_bulk") != "yes":
                    messages.error(request, "Confirm Delete All before saving.")
                    return redirect("imported_pota_history", entry_id=entry.pk)
            else:
                messages.error(request, "Choose a valid deletion option.")
                return redirect("imported_pota_history", entry_id=entry.pk)

            deleted_count = candidates.count()
            candidates.delete()
            recalculate_pota_rollups(locked_entry)

        messages.success(
            request,
            f"Deleted {deleted_count} imported POTA History record"
            f"{'s' if deleted_count != 1 else ''}.",
        )
        return redirect("imported_pota_history", entry_id=entry.pk)

    imports = list(scoped_imports.select_related("batch").order_by("-activation_date", "pk"))
    batches = sorted({item.batch_id for item in imports})
    return render(
        request,
        "adventures/imported_pota_history.html",
        {
            "entry": entry,
            "adventure": entry.adventure,
            "imports": imports,
            "batch_ids": batches,
        },
    )
