from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count

from .models import (
    Adventure,
    Comment,
    JournalContact,
    JournalEntry,
    Location,
    Photo,
    PotaActivationImport,
    PotaImportBatch,
    PotaTestResetAudit,
)

CONFIRMATION_PHRASE = "DELETE POTA TEST DATA"
IMPORT_LOCATION_PREFIX = "Created from POTA historical import."


class PotaResetSafetyError(RuntimeError):
    pass


@dataclass
class PotaResetResult:
    backup_path: str
    deleted: dict
    retained: dict
    blocked: list
    integrity: str


def database_identifier():
    return str(Path(str(connection.settings_dict["NAME"])).resolve())


def assert_development_database(*, allow_test_database=False):
    if not settings.DEBUG:
        raise PotaResetSafetyError("POTA test reset is disabled unless DEBUG=True.")
    if connection.vendor != "sqlite":
        raise PotaResetSafetyError("POTA test reset requires the positively identified SQLite development database.")
    name = str(connection.settings_dict["NAME"])
    is_test = name.startswith("file:memorydb_") or "test_" in Path(name).name
    expected = (Path(settings.BASE_DIR) / "db.sqlite3").resolve()
    if is_test and allow_test_database:
        return
    if Path(name).resolve() != expected:
        raise PotaResetSafetyError(f"Refusing database other than the development database: {expected}")


def build_reset_preview():
    audits = PotaActivationImport.objects.select_related("adventure", "batch").order_by("pk")
    adventure_ids = list(audits.values_list("adventure_id", flat=True))
    batch_ids = list(audits.order_by().values_list("batch_id", flat=True).distinct())
    journals = JournalEntry.objects.filter(adventure_id__in=adventure_ids)
    contacts = JournalContact.objects.filter(journal_entry__adventure_id__in=adventure_ids)
    photos = Photo.objects.filter(journal_entry__adventure_id__in=adventure_ids)
    comments = Comment.objects.filter(adventure_id__in=adventure_ids)

    blocked = []
    blocked_adventure_ids = set()
    for adventure in Adventure.objects.filter(pk__in=adventure_ids).annotate(
        journal_total=Count("journal_entries", distinct=True),
        comment_total=Count("comments", distinct=True),
    ).order_by("pk"):
        contact_total = contacts.filter(journal_entry__adventure=adventure).count()
        photo_total = photos.filter(journal_entry__adventure=adventure).count()
        if adventure.journal_total or contact_total or photo_total or adventure.comment_total:
            blocked_adventure_ids.add(adventure.pk)
            blocked.append({
                "type": "Adventure",
                "id": adventure.pk,
                "label": adventure.title,
                "reason": "Attached content is not importer-provenanced.",
                "journals": adventure.journal_total,
                "contacts": contact_total,
                "photos": photo_total,
                "comments": adventure.comment_total,
            })

    location_ids = list(
        Adventure.objects.filter(pk__in=adventure_ids)
        .exclude(location_id=None)
        .values_list("location_id", flat=True)
        .distinct()
    )
    imported_locations = Location.objects.filter(
        description__startswith=IMPORT_LOCATION_PREFIX,
    ).order_by("pk")
    deletable_location_ids = []
    retained_locations = []
    for location in imported_locations:
        non_pota_uses = location.adventures.filter(pota_import__isnull=True).count()
        has_manual_location_content = location.operating_locations.exists() or bool(location.photo)
        blocked_uses = location.adventures.filter(pk__in=blocked_adventure_ids).count()
        if non_pota_uses or has_manual_location_content or blocked_uses:
            retained_locations.append({
                "id": location.pk,
                "name": location.name,
                "reason": "Still used or contains non-importer-provenanced content.",
            })
        else:
            deletable_location_ids.append(location.pk)

    safe_adventure_ids = [pk for pk in adventure_ids if pk not in blocked_adventure_ids]
    return {
        "adventure_ids": adventure_ids,
        "safe_adventure_ids": safe_adventure_ids,
        "blocked_adventure_ids": sorted(blocked_adventure_ids),
        "location_ids": location_ids,
        "deletable_location_ids": deletable_location_ids,
        "retained_locations": retained_locations,
        "batch_ids": batch_ids,
        "blocked": blocked,
        "counts": {
            "adventures": len(adventure_ids),
            "locations": imported_locations.count(),
            "journals": journals.count(),
            "contacts": contacts.count(),
            "photos": photos.count(),
            "batches": len(batch_ids),
            "audits": audits.count(),
            "fingerprints": audits.exclude(fingerprint="").count(),
            "attestations": sum(batch.callsign_attestations.count() for batch in PotaImportBatch.objects.filter(pk__in=batch_ids)),
        },
    }


def create_database_backup():
    source = Path(str(connection.settings_dict["NAME"])).resolve()
    backup_dir = Path(settings.MEDIA_ROOT) / "database_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"db-before-pota-test-reset-{stamp}.sqlite3"
    source_connection = sqlite3.connect(str(source))
    target_connection = sqlite3.connect(str(target))
    try:
        source_connection.backup(target_connection)
        if target_connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PotaResetSafetyError("The database backup failed its integrity check.")
    finally:
        target_connection.close()
        source_connection.close()
    return str(target)


def execute_reset(*, actor=None, allow_test_database=False, backup_factory=None):
    assert_development_database(allow_test_database=allow_test_database)
    preview = build_reset_preview()
    backup_path = ""
    try:
        backup_path = (backup_factory or create_database_backup)()
        deleted = {key: 0 for key in ("adventures", "locations", "journals", "contacts", "photos", "batches", "audits", "fingerprints", "attestations")}
        with transaction.atomic():
            safe_ids = preview["safe_adventure_ids"]
            deleted["journals"] = JournalEntry.objects.filter(adventure_id__in=safe_ids).count()
            deleted["contacts"] = JournalContact.objects.filter(journal_entry__adventure_id__in=safe_ids).count()
            deleted["photos"] = Photo.objects.filter(journal_entry__adventure_id__in=safe_ids).count()
            deleted["audits"] = PotaActivationImport.objects.filter(adventure_id__in=safe_ids).count()
            deleted["fingerprints"] = PotaActivationImport.objects.filter(adventure_id__in=safe_ids).exclude(fingerprint="").count()
            deleted["adventures"] = len(safe_ids)
            Adventure.objects.filter(pk__in=safe_ids).delete()
            deletable_locations = Location.objects.filter(pk__in=preview["deletable_location_ids"])
            deleted["locations"] = deletable_locations.count()
            deletable_locations.delete()
            empty_batches = PotaImportBatch.objects.filter(pk__in=preview["batch_ids"], activations__isnull=True)
            deleted["attestations"] = sum(batch.callsign_attestations.count() for batch in empty_batches)
            deleted["batches"] = empty_batches.count()
            empty_batches.delete()
            PotaTestResetAudit.objects.create(
                staff_user=actor,
                database_identifier=database_identifier(),
                deleted_counts=deleted,
                blocked_counts={"records": len(preview["blocked"])},
                backup_path=backup_path,
                succeeded=True,
            )
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA foreign_key_check")
            violations = cursor.fetchall()
            cursor.execute("PRAGMA integrity_check")
            integrity = cursor.fetchone()[0]
        if violations or integrity != "ok":
            raise PotaResetSafetyError("Post-reset database integrity verification failed.")
        return PotaResetResult(
            backup_path=backup_path,
            deleted=deleted,
            retained={
                "adventures": len(preview["blocked_adventure_ids"]),
                "locations": len(preview["retained_locations"]),
            },
            blocked=preview["blocked"],
            integrity=integrity,
        )
    except Exception as exc:
        try:
            PotaTestResetAudit.objects.create(
                staff_user=actor,
                database_identifier=database_identifier(),
                blocked_counts={"records": len(preview["blocked"])},
                backup_path=backup_path,
                succeeded=False,
                error_category=type(exc).__name__,
            )
        except Exception:
            pass
        raise
