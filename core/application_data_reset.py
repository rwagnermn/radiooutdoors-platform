from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

from .models import (
    Adventure,
    AdventureCoverSelectionAudit,
    Comment,
    CoordinateChangeAudit,
    FollowRelationship,
    FollowerInvitation,
    JournalContact,
    JournalEntry,
    Location,
    ManualVerificationRequest,
    MemberCallsignAudit,
    MemberProfile,
    OperatingLocation,
    Photo,
    PhotoModerationActionAudit,
    PolicyAcceptance,
    PotaActivationImport,
    PotaCallsignAttestation,
    PotaImportBatch,
    PotaTestResetAudit,
    QuarantinedPhoto,
)


CONFIRMATION_PHRASE = "DELETE ALL DATA"
UPLOAD_DIRECTORIES = (
    "adventure_photos",
    "location_photos",
    "member_profiles",
    "photo_derivatives",
    "photo_quarantine",
)


@dataclass
class ApplicationDataResetResult:
    deleted: dict
    media_files_deleted: int
    media_failures: list[str]
    preserved_admins: list[dict]


def _delete_queryset(queryset):
    count = queryset.count()
    queryset.delete()
    return count


def _safe_upload_files(*, preserved_names=()):
    """Return files only from application-owned upload directories."""
    media_root = Path(settings.MEDIA_ROOT).resolve()
    files = set()
    for directory in UPLOAD_DIRECTORIES:
        root = (media_root / directory).resolve()
        if root != media_root and media_root in root.parents and root.exists():
            files.update(path for path in root.rglob("*") if path.is_file())
    preserved = {(media_root / name).resolve() for name in preserved_names if name}
    return files - preserved


def _remove_upload_files(files):
    deleted = 0
    failures = []
    media_root = Path(settings.MEDIA_ROOT).resolve()
    for path in sorted(files):
        try:
            resolved = path.resolve()
            if media_root not in resolved.parents:
                failures.append(f"Refused path outside MEDIA_ROOT: {path}")
                continue
            resolved.unlink(missing_ok=True)
            deleted += 1
        except OSError as exc:
            failures.append(f"{path}: {exc}")

    for directory in UPLOAD_DIRECTORIES:
        root = media_root / directory
        if not root.exists():
            continue
        for child in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
            try:
                child.rmdir()
            except OSError:
                pass
    return deleted, failures


def reset_all_application_data():
    user_model = get_user_model()
    admins = list(
        user_model.objects.filter(Q(is_staff=True) | Q(is_superuser=True)).order_by("username").values(
            "id", "username", "email", "is_superuser"
        )
    )
    admin_ids = [admin["id"] for admin in admins]
    preserved_media_names = MemberProfile.objects.filter(user_id__in=admin_ids).exclude(
        profile_photo=""
    ).values_list("profile_photo", flat=True)
    upload_files = _safe_upload_files(preserved_names=preserved_media_names)

    deleted = {}
    with transaction.atomic():
        # Audits with protected administrator foreign keys must be removed first.
        deleted["photo moderation audits"] = _delete_queryset(PhotoModerationActionAudit.objects.all())
        deleted["coordinate audits"] = _delete_queryset(CoordinateChangeAudit.objects.all())
        deleted["quarantined photos"] = _delete_queryset(QuarantinedPhoto.objects.all())
        deleted["cover selection audits"] = _delete_queryset(AdventureCoverSelectionAudit.objects.all())
        deleted["POTA test reset audits"] = _delete_queryset(PotaTestResetAudit.objects.all())
        deleted["Django admin history"] = _delete_queryset(LogEntry.objects.all())

        deleted["POTA activation imports"] = _delete_queryset(PotaActivationImport.objects.all())
        deleted["POTA callsign attestations"] = _delete_queryset(PotaCallsignAttestation.objects.all())
        deleted["POTA import batches"] = _delete_queryset(PotaImportBatch.objects.all())
        deleted["photos"] = _delete_queryset(Photo.objects.all())
        deleted["journal contacts"] = _delete_queryset(JournalContact.objects.all())
        deleted["journals"] = _delete_queryset(JournalEntry.objects.all())
        deleted["comments"] = _delete_queryset(Comment.objects.all())
        deleted["adventures"] = _delete_queryset(Adventure.objects.all())
        deleted["operating locations"] = _delete_queryset(OperatingLocation.objects.all())
        deleted["locations"] = _delete_queryset(Location.objects.all())
        deleted["manual verification requests"] = _delete_queryset(ManualVerificationRequest.objects.all())
        deleted["callsign audits"] = _delete_queryset(MemberCallsignAudit.objects.all())
        deleted["follow relationships"] = _delete_queryset(FollowRelationship.objects.all())
        deleted["follower invitations"] = _delete_queryset(FollowerInvitation.objects.all())

        deleted["policy acceptances"] = _delete_queryset(
            PolicyAcceptance.objects.filter(Q(user__isnull=True) | ~Q(user_id__in=admin_ids))
        )
        deleted["member profiles"] = _delete_queryset(MemberProfile.objects.exclude(user_id__in=admin_ids))
        deleted["members"] = _delete_queryset(user_model.objects.exclude(id__in=admin_ids))

        # Verify rather than assuming cascades handled the operational graph.
        remaining = {
            model.__name__: model.objects.count()
            for model in (
                Adventure, AdventureCoverSelectionAudit, Comment, CoordinateChangeAudit,
                FollowRelationship, FollowerInvitation, JournalContact, JournalEntry,
                Location, ManualVerificationRequest, MemberCallsignAudit, OperatingLocation,
                Photo, PhotoModerationActionAudit, PotaActivationImport,
                PotaCallsignAttestation, PotaImportBatch, PotaTestResetAudit,
                QuarantinedPhoto,
            )
            if model.objects.exists()
        }
        if remaining:
            raise RuntimeError(f"Application reset left operational records: {remaining}")

    media_deleted, media_failures = _remove_upload_files(upload_files)
    return ApplicationDataResetResult(deleted, media_deleted, media_failures, admins)
