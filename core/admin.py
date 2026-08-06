from django.contrib import admin
from .models import Location, MemberProfile

@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    list_display = ("callsign", "user", "display_name", "callsign_verified", "profile_is_public")
    list_filter = ("callsign_verified", "profile_is_public", "user__is_active")
    search_fields = ("callsign", "display_name", "user__username", "user__email")

admin.site.register(Location)


from .models import BlockedDomain

try:
    admin.site.register(BlockedDomain)
except admin.sites.AlreadyRegistered:
    pass
