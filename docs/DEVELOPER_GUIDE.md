# Developer Guide

Read the Charter and DNA before changing workflows. Preserve data. Run syntax, Django, migration, and template checks.

When starting or restarting Django, preserve outbound network access for QRZ. Before handoff, verify the live server reaches QRZ authentication and callsign lookup using the sanitized procedure in `DEVELOPMENT_STANDARD.md`; never expose credentials or session keys.
# Photo moderation

Public image uploads are fail-closed. The default provider uses OpenAI's
`omni-moderation-latest` image-capable Moderations endpoint. Supply
`OPENAI_API_KEY` in the environment. For local DEBUG use only, a key may be put
in the gitignored project-root `openai_api_key.txt`. Optional settings are
`OPENAI_MODERATION_MODEL` and `OPENAI_MODERATION_TIMEOUT`. If the key, network,
or provider is unavailable, uploads remain **Pending Scan** and are not rendered
on public pages. Never describe automatic moderation as operational until a
real provider request has passed in the deployment environment.

Run `python manage.py backfill_photo_moderation --limit 25` to scan existing unapproved
Adventure/Journal, Location, and Member-profile images. Provider errors are
sanitized in server logs and leave the image pending for a safe retry.

In the current implementation, moderation runs synchronously during upload;
there is no separate development or production moderation worker. A provider
failure is recorded as **Scan failed**, the image remains private, and staff can
use **Retry Moderation** from the Photo Moderation queue. An untouched Pending
Scan older than 15 minutes is labelled **Pending scan — stuck** so it is not
silently stranded. If moderation is later moved to a background queue, deployment
must include a monitored worker and retry policy before that queue is enabled.

Provider credentials belong in environment variables, never source control.
Common replaceable provider choices include a cloud image-moderation API or a
self-hosted classifier; each must map its response to Approved, Needs
Administrator Review, or Rejected and must treat uncertain/service-failure
results as non-public.

Production web-server/CDN configuration must not bypass Django for the
`adventure_photos/`, `location_photos/`, `member_profiles/`, or
`location_defaults/` media prefixes. Those requests must use the moderated
media route (or an equivalent signed/private-object-storage policy), otherwise
a guessed pending-file URL could bypass the publication check.
