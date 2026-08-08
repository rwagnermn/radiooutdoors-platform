import html
import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from django.core.files.storage import default_storage
from django.core.management.base import CommandError
from django.core.files.base import ContentFile

from .models import DefaultLocationImage, Location
from .profile_images import optimize_location_photo


COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
DEFAULT_IMAGE_DIRECTORY = "location_defaults"
REUSABLE_LICENSE_PREFIXES = (
    "Public domain",
    "CC0",
    "CC BY ",
    "CC BY-SA ",
)
WIKIMEDIA_USER_AGENT = (
    "RadioOutdoors/1.0 (https://radiooutdoors.org; contact@radiooutdoors.org)"
)

DEFAULT_LOCATION_IMAGES = {
    "park": {
        "filename": "File:LakeWissotaStatePark1.jpg",
        "title": "Picnic Overlook at Lake Wissota State Park",
        "creator": "McGhiever",
        "source_url": "https://commons.wikimedia.org/wiki/File:LakeWissotaStatePark1.jpg",
        "license_name": "Public domain",
        "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
    },
    "campground": {
        "filename": "File:CSP tent camping.jpg",
        "title": "Tent camping at Cleburne State Park",
        "creator": "Stephen Denny",
        "source_url": "https://commons.wikimedia.org/wiki/File:CSP_tent_camping.jpg",
        "license_name": "Public domain",
        "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
    },
    "wildlife": {
        "filename": "File:Grassland .jpg",
        "title": "Grassland",
        "creator": "Kushal P K",
        "source_url": "https://commons.wikimedia.org/wiki/File:Grassland_.jpg",
        "license_name": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    },
    "airport": {
        "filename": "File:Klagenfurt Airport - Hangar, General Aviation, Heliport.jpg",
        "title": "General aviation hangar and heliport",
        "creator": "Zacke82",
        "source_url": "https://commons.wikimedia.org/wiki/File:Klagenfurt_Airport_-_Hangar,_General_Aviation,_Heliport.jpg",
        "license_name": "CC BY-SA 3.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
    },
    "boat_launch": {
        "filename": "File:US-WA-lacamas lake-north boat launch-tar.jpg",
        "title": "Lacamas Lake boat launch",
        "creator": "Triddle",
        "source_url": "https://commons.wikimedia.org/wiki/File:US-WA-lacamas_lake-north_boat_launch-tar.jpg",
        "license_name": "Public domain",
        "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
    },
    "scenic": {
        "filename": "File:San Bernardino National Forest scenic overlook.jpg",
        "title": "San Bernardino National Forest scenic overlook",
        "creator": "APK",
        "source_url": "https://commons.wikimedia.org/wiki/File:San_Bernardino_National_Forest_scenic_overlook.jpg",
        "license_name": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    },
}

LOCATION_TYPE_DEFAULTS = {
    Location.LocationType.PARK: "park",
    Location.LocationType.CAMPGROUND: "campground",
    Location.LocationType.TRAIL: "scenic",
    Location.LocationType.BOAT_LAUNCH: "boat_launch",
    Location.LocationType.SCENIC_OVERLOOK: "scenic",
    Location.LocationType.BEACH: "boat_launch",
    Location.LocationType.CABIN: "campground",
    Location.LocationType.BACKYARD: "park",
    Location.LocationType.SUMMIT: "scenic",
    Location.LocationType.ISLAND: "boat_launch",
    Location.LocationType.REST_AREA: "scenic",
    Location.LocationType.WMA_DNR: "wildlife",
    Location.LocationType.OTHER: "scenic",
}


def default_image_key(location):
    name = location.name.lower()
    if any(word in name for word in ("airport", "airfield", "aviation")):
        return "airport"
    if any(word in name for word in ("campground", "camp site", "campsite")):
        return "campground"
    if any(word in name for word in ("boat launch", "marina")):
        return "boat_launch"
    if "park" in name:
        return "park"
    return LOCATION_TYPE_DEFAULTS.get(location.location_type, "scenic")


def default_image_storage_name(key):
    return f"{DEFAULT_IMAGE_DIRECTORY}/{key}.jpg"


def default_image_for_location(location):
    key = default_image_key(location)
    record = DefaultLocationImage.objects.filter(
        key=key, active=True, moderation_status="approved"
    ).first()
    if record is None or not record.image:
        return None
    storage_name = record.image.name
    if not default_storage.exists(storage_name):
        return None
    return {
        "key": key,
        "url": record.image.url,
        "title": record.source_title,
        "creator": record.creator,
        "source_url": record.source_url,
        "license_name": record.license_name,
        "license_url": record.license_url,
        "credit_text": record.credit_text,
    }


def reusable_license(license_name):
    return any(license_name.startswith(prefix) for prefix in REUSABLE_LICENSE_PREFIXES)


def _plain_text(value):
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def _open_request(request, timeout):
    for attempt in range(4):
        try:
            return urlopen(request, timeout=timeout)
        except HTTPError as error:
            if error.code != 429 or attempt == 3:
                raise
            time.sleep(2 ** attempt)


def commons_image_information(filename):
    query = urlencode(
        {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "titles": filename,
            "iiprop": "url|extmetadata",
            "iiurlwidth": "1600",
        }
    )
    request = Request(
        f"{COMMONS_API_URL}?{query}",
        headers={"User-Agent": WIKIMEDIA_USER_AGENT},
    )
    with _open_request(request, timeout=30) as response:
        payload = json.load(response)
    page = next(iter(payload.get("query", {}).get("pages", {}).values()), {})
    image_info = (page.get("imageinfo") or [{}])[0]
    metadata = image_info.get("extmetadata", {})
    license_name = _plain_text(metadata.get("LicenseShortName", {}).get("value"))
    license_url = metadata.get("LicenseUrl", {}).get("value", "").strip()
    if not reusable_license(license_name):
        raise CommandError(
            f"Wikimedia file has no approved reusable license: {filename} ({license_name or 'missing'})"
        )
    download_url = image_info.get("url")
    if not download_url:
        raise CommandError(f"Wikimedia returned no downloadable image for: {filename}")
    return {
        "download_url": download_url,
        "license_name": license_name,
        "license_url": license_url,
        "creator": _plain_text(metadata.get("Artist", {}).get("value")),
    }


def install_default_location_images(refresh=False):
    installed = []
    for key, expected in DEFAULT_LOCATION_IMAGES.items():
        storage_name = default_image_storage_name(key)
        if default_storage.exists(storage_name) and not refresh:
            DefaultLocationImage.objects.update_or_create(
                key=key,
                defaults={
                    "image": storage_name,
                    "source_title": expected["title"],
                    "source_url": expected["source_url"],
                    "creator": expected["creator"],
                    "license_name": expected["license_name"],
                    "license_url": expected["license_url"],
                    "displayed_credit": f"{expected['title']} by {expected['creator']}",
                    "active": True,
                },
            )
            installed.append({"key": key, "status": "existing", **expected})
            continue
        actual = commons_image_information(expected["filename"])
        if actual["license_name"] != expected["license_name"]:
            raise CommandError(
                f"License changed for {expected['filename']}: expected {expected['license_name']}, got {actual['license_name']}"
            )
        request = Request(
            actual["download_url"],
            headers={"User-Agent": WIKIMEDIA_USER_AGENT},
        )
        with _open_request(request, timeout=60) as response:
            downloaded = response.read(20 * 1024 * 1024 + 1)
        if len(downloaded) > 20 * 1024 * 1024:
            raise CommandError(f"Wikimedia image is unexpectedly large: {expected['filename']}")
        optimized = optimize_location_photo(
            ContentFile(downloaded, name=Path(actual["download_url"]).name or f"{key}.jpg")
        )
        if default_storage.exists(storage_name):
            default_storage.delete(storage_name)
        default_storage.save(storage_name, optimized)
        DefaultLocationImage.objects.update_or_create(
            key=key,
            defaults={
                "image": storage_name,
                "source_title": expected["title"],
                "source_url": expected["source_url"],
                "creator": expected["creator"],
                "license_name": expected["license_name"],
                "license_url": expected["license_url"],
                "displayed_credit": f"{expected['title']} by {expected['creator']}",
                "active": True,
            },
        )
        installed.append({"key": key, "status": "installed", **expected})
    return installed
