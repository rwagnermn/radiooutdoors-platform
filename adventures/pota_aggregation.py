from django.db.models import CharField, Count, F, IntegerField, Max, Sum, Value
from django.db.models.functions import Coalesce, NullIf, Upper

from core.models import PotaActivationImport, PotaImportBatch


POTA_TOTAL_FIELDS = {
    "cw": "cw_contacts",
    "data": "data_contacts",
    "phone": "phone_contacts",
}


def eligible_pota_journal_imports():
    """Return the authoritative activation rows represented by POTA Journals."""
    return PotaActivationImport.objects.filter(
        source=PotaImportBatch.Source.ACTIVATION_HISTORY,
        journal_entry__isnull=False,
        journal_entry__pota=True,
    )


def aggregate_pota_totals(imports):
    totals = imports.aggregate(
        **{name: Sum(field) for name, field in POTA_TOTAL_FIELDS.items()},
        total=Sum(
            F("cw_contacts") + F("data_contacts") + F("phone_contacts"),
            output_field=IntegerField(),
        ),
    )
    return {name: totals[name] or 0 for name in (*POTA_TOTAL_FIELDS, "total")}


def aggregate_pota_journals(journals):
    return aggregate_pota_totals(
        eligible_pota_journal_imports().filter(
            journal_entry_id__in=journals.values("pk")
        )
    )


def public_pota_leaders(*, activation_year=None):
    """Aggregate eligible public Journals, optionally for one activation year."""
    imports = eligible_pota_journal_imports().filter(
        journal_entry__is_public=True,
        journal_entry__adventure__is_public=True,
    )
    if activation_year is not None:
        imports = imports.filter(activation_date__year=activation_year)

    return (
        imports
        .annotate(
            member_id=F("journal_entry__adventure__owner_id"),
            member=Coalesce(
                NullIf(
                    Upper("journal_entry__adventure__owner__member_profile__callsign"),
                    Value(""),
                ),
                Upper("journal_entry__adventure__owner__username"),
                output_field=CharField(),
            ),
        )
        .values("member_id", "member")
        .annotate(
            activation_count=Count("pk"),
            cw=Sum("cw_contacts"),
            data=Sum("data_contacts"),
            phone=Sum("phone_contacts"),
            total=Sum(
                F("cw_contacts") + F("data_contacts") + F("phone_contacts"),
                output_field=IntegerField(),
            ),
            latest_activation=Max("activation_date"),
        )
        .order_by("-total", "-activation_count", "member", "member_id")[:100]
    )
