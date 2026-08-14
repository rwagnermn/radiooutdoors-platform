import json
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.models import Photo
from core.photo_normalization import read_and_normalize


DERIVATIVE_FIELDS = {
    "moderation_image": "moderation_bytes",
    "web_image": "web_bytes",
    "thumbnail_image": "thumbnail_bytes",
}


def _safe_member_name(name):
    normalized = name.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or path.is_absolute()
        or ".." in path.parts
        or (path.parts and path.parts[0].endswith(":"))
    ):
        raise CommandError(f"Unsafe ZIP member path: {name!r}")
    return path.as_posix()


def _safe_target(media_root, relative_name):
    root = media_root.resolve()
    target = (root / Path(*PurePosixPath(relative_name).parts)).resolve()
    if target == root or root not in target.parents:
        raise CommandError(f"Recovery target escapes MEDIA_ROOT: {relative_name!r}")
    return target


class Command(BaseCommand):
    help = "Restore only missing files referenced by current Photo records; dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Perform the reported missing-files-only recovery.")
        parser.add_argument("--backup-dir", default=str(Path(settings.BASE_DIR) / "local-backups"))

    def handle(self, *args, **options):
        apply = options["apply"]
        media_root = Path(settings.MEDIA_ROOT).resolve()
        backup_dir = Path(options["backup_dir"]).resolve()
        archives = sorted(backup_dir.glob("media-*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not archives:
            raise CommandError(f"No media backup archives found in {backup_dir}")

        photos = list(Photo.objects.order_by("pk"))
        records = {}
        required = set()
        originals = set()
        derivatives = set()
        for photo in photos:
            original = photo.image.name.replace("\\", "/") if photo.image else ""
            derivative_names = {
                field: getattr(photo, field).name.replace("\\", "/")
                for field in DERIVATIVE_FIELDS
                if getattr(photo, field)
            }
            records[photo.pk] = {"original": original, "derivatives": derivative_names}
            if original:
                originals.add(original)
                required.add(original)
            derivatives.update(derivative_names.values())
            required.update(derivative_names.values())

        active = {name for name in required if _safe_target(media_root, name).is_file()}
        archive_members = {}
        inspected = []
        for archive in archives:
            member_map = {}
            with zipfile.ZipFile(archive) as source:
                for info in source.infolist():
                    if info.is_dir():
                        continue
                    safe_name = _safe_member_name(info.filename)
                    member_map.setdefault(safe_name, info)
                    if safe_name in required and safe_name not in archive_members:
                        archive_members[safe_name] = (archive, info)
            inspected.append({"path": str(archive), "files": len(member_map)})

        missing_originals = originals - active
        missing_derivatives = derivatives - active
        recoverable_originals = missing_originals & archive_members.keys()
        recoverable_derivatives = missing_derivatives & archive_members.keys()
        recoverable_after_restore = active | recoverable_originals
        regenerate = set()
        unrecoverable = []
        for photo in photos:
            record = records[photo.pk]
            original = record["original"]
            if original and original not in recoverable_after_restore:
                unrecoverable.append({"photo_id": photo.pk, "original": original})
                continue
            for field, name in record["derivatives"].items():
                if name in missing_derivatives and name not in recoverable_derivatives:
                    regenerate.add((photo.pk, field, name))

        restore_order = sorted(recoverable_originals) + sorted(recoverable_derivatives)
        report = {
            "mode": "apply" if apply else "dry-run",
            "archives_inspected": inspected,
            "photo_records": len(photos),
            "missing_originals_recoverable": len(recoverable_originals),
            "missing_derivatives_recoverable": len(recoverable_derivatives),
            "derivatives_requiring_regeneration": len(regenerate),
            "photos_with_no_recoverable_original": unrecoverable,
            "files_to_restore": [
                {"path": name, "archive": str(archive_members[name][0])}
                for name in restore_order
            ],
            "derivatives_to_regenerate": [
                {"photo_id": photo_id, "field": field, "path": name}
                for photo_id, field, name in sorted(regenerate)
            ],
            "existing_files_overwritten": 0,
        }
        self.stdout.write(json.dumps(report, indent=2))
        if not apply:
            return

        restored = []
        for name in restore_order:
            target = _safe_target(media_root, name)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            archive, info = archive_members[name]
            try:
                with zipfile.ZipFile(archive) as source, source.open(info) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
            except Exception:
                if target.exists():
                    target.unlink()
                raise
            restored.append(name)

        regenerated = []
        normalized_by_photo = {}
        for photo_id, field, name in sorted(regenerate):
            target = _safe_target(media_root, name)
            if target.exists():
                continue
            photo = next(item for item in photos if item.pk == photo_id)
            if photo_id not in normalized_by_photo:
                normalized_by_photo[photo_id] = read_and_normalize(photo.image)
            payload = getattr(normalized_by_photo[photo_id], DERIVATIVE_FIELDS[field])
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with target.open("xb") as outgoing:
                    outgoing.write(payload)
            except Exception:
                if target.exists():
                    target.unlink()
                raise
            regenerated.append(name)

        self.stdout.write(json.dumps({
            "restored": restored,
            "regenerated": regenerated,
            "existing_files_overwritten": 0,
            "database_writes": 0,
        }, indent=2))
