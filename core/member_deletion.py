from collections import Counter

from django.db import transaction
from django.db.models import Q

from .models import (
    Adventure,
    Comment,
    CoordinateChangeAudit,
    JournalContact,
    JournalEntry,
    Photo,
    PhotoModerationActionAudit,
    PolicyAcceptance,
    PotaActivationImport,
    PotaCallsignAttestation,
    PotaImportBatch,
    PotaTestResetAudit,
    QuarantinedPhoto,
)


def member_deletion_preview(user):
    """Return account-owned operational data counts shown before deletion."""
    return {
        "adventures": Adventure.objects.filter(owner=user).count(),
        "journals": JournalEntry.objects.filter(adventure__owner=user).count(),
        "contacts": JournalContact.objects.filter(
            journal_entry__adventure__owner=user
        ).count(),
        "photos": Photo.objects.filter(journal_entry__adventure__owner=user).count(),
        "comments": Comment.objects.filter(
            Q(operator=user) | Q(adventure__owner=user)
        ).distinct().count(),
        "pota_batches": PotaImportBatch.objects.filter(owner=user).count(),
        "pota_activations": PotaActivationImport.objects.filter(
            Q(batch__owner=user) | Q(adventure__owner=user)
        ).distinct().count(),
        "pota_attestations": PotaCallsignAttestation.objects.filter(
            Q(member=user) | Q(batch__owner=user)
        ).distinct().count(),
        "operational_audits": (
            PhotoModerationActionAudit.objects.filter(actor=user).count()
            + CoordinateChangeAudit.objects.filter(actor=user).count()
            + QuarantinedPhoto.objects.filter(removed_by=user).count()
        ),
        "preserved_policy_acceptances": PolicyAcceptance.objects.filter(
            user=user
        ).count(),
        "preserved_reset_audits": PotaTestResetAudit.objects.filter(
            staff_user=user
        ).count(),
    }


def _merge_deleted_counts(total, deleted):
    _, model_counts = deleted
    total.update(model_counts)


def _delete_protected_operational_records(user, deleted_counts):
    """Resolve intentional PROTECT relationships before deleting an account."""
    activations = PotaActivationImport.objects.filter(
        Q(batch__owner=user) | Q(adventure__owner=user)
    ).distinct()
    _merge_deleted_counts(deleted_counts, activations.delete())

    # These actor-owned records cannot be anonymized because their actor fields are
    # non-nullable PROTECT relationships. They are account operational history, not
    # shared system/reference data, so they leave with the account.
    for queryset in (
        PhotoModerationActionAudit.objects.filter(actor=user),
        CoordinateChangeAudit.objects.filter(actor=user),
        QuarantinedPhoto.objects.filter(removed_by=user),
    ):
        _merge_deleted_counts(deleted_counts, queryset.delete())

    # Once activation imports are gone, batches can be deleted without PROTECT
    # blocking their CASCADE from User. Batch attestations cascade here.
    _merge_deleted_counts(
        deleted_counts,
        PotaImportBatch.objects.filter(owner=user).delete(),
    )


@transaction.atomic
def delete_member_account(user):
    """Delete a normal member and account-owned operational data atomically."""
    if user.is_staff or user.is_superuser:
        raise ValueError("Staff and superuser accounts are protected from member deletion.")

    deleted_counts = Counter()
    _delete_protected_operational_records(user, deleted_counts)
    _merge_deleted_counts(deleted_counts, user.delete())
    return dict(deleted_counts)


def summarize_member_deletion(deleted_counts):
    """Group Django's per-model deletion counts for administrator feedback."""
    categories = {
        "member": deleted_counts.get("auth.User", 0),
        "adventures": deleted_counts.get("core.Adventure", 0),
        "journals": deleted_counts.get("core.JournalEntry", 0),
        "contacts": deleted_counts.get("core.JournalContact", 0),
        "photos": deleted_counts.get("core.Photo", 0),
        "pota_batches": deleted_counts.get("core.PotaImportBatch", 0),
        "pota_imports": deleted_counts.get("core.PotaActivationImport", 0),
    }
    categorized_models = {
        "auth.User",
        "core.Adventure",
        "core.JournalEntry",
        "core.JournalContact",
        "core.Photo",
        "core.PotaImportBatch",
        "core.PotaActivationImport",
    }
    categories["other_history"] = sum(
        count
        for model, count in deleted_counts.items()
        if model not in categorized_models
    )
    return categories
