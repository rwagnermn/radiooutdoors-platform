from django.contrib import admin
from django.utils import formats, timezone

from .models import Location, MemberProfile, PolicyAcceptance

@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    list_display = ("callsign", "user", "display_name", "verification_method", "callsign_verified", "profile_is_public")
    list_filter = ("verification_method", "callsign_verified", "profile_is_public", "user__is_active")
    search_fields = ("callsign", "display_name", "user__username", "user__email")

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "visibility", "created_by", "state", "updated_at")
    list_filter = ("visibility", "state", "location_type_record")
    search_fields = ("name", "city", "state", "created_by__username")


from .models import BlockedDomain

try:
    admin.site.register(BlockedDomain)
except admin.sites.AlreadyRegistered:
    pass


@admin.register(PolicyAcceptance)
class PolicyAcceptanceAdmin(admin.ModelAdmin):
    """Read-only audit history; acceptance events are never administered manually."""

    change_form_template = "admin/core/policyacceptance/change_form.html"
    actions = None
    list_display = (
        "user_account",
        "callsign",
        "account_status",
        "terms_version",
        "privacy_version",
        "community_version",
        "age_attestation",
        "registration_path",
        "accepted_at_local",
    )
    list_filter = (
        "accepted_at",
        "terms_version",
        "privacy_version",
        "community_version",
        "registration_path",
        "account_status",
        "age_attested",
    )
    search_fields = (
        "account_identifier",
        "user__username",
        "user__first_name",
        "user__last_name",
        "user__email",
        "user__member_profile__callsign",
        "terms_version",
        "privacy_version",
        "community_version",
    )
    readonly_fields = (
        "record_identifier",
        "user_account",
        "callsign",
        "account_status",
        "terms_version",
        "privacy_version",
        "community_version",
        "age_attestation",
        "registration_path",
        "accepted_at_local",
    )
    fields = readonly_fields
    list_select_related = ("user", "user__member_profile")
    ordering = ("-accepted_at",)

    @admin.display(description="Record")
    def record_identifier(self, obj):
        return f"Policy acceptance #{obj.pk}"

    @admin.display(description="User", ordering="user__username")
    def user_account(self, obj):
        if obj.user_id:
            name = obj.user.get_full_name().strip()
            return f"{obj.user.username} — {name}" if name else obj.user.username
        return f"Deleted account — {obj.account_identifier}"

    @admin.display(description="Callsign", ordering="account_identifier")
    def callsign(self, obj):
        profile = getattr(obj.user, "member_profile", None) if obj.user_id else None
        return profile.callsign if profile and profile.callsign else obj.account_identifier

    @admin.display(description="Age attestation", boolean=True, ordering="age_attested")
    def age_attestation(self, obj):
        return obj.age_attested

    @admin.display(description="Accepted date and time", ordering="accepted_at")
    def accepted_at_local(self, obj):
        if not obj or not obj.accepted_at:
            return "—"
        return formats.date_format(
            timezone.localtime(obj.accepted_at), "DATETIME_FORMAT"
        )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "user__member_profile")

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_staff and super().has_view_permission(request, obj))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
