from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from .models import Adventure, BlockedDomain, FollowRelationship, Location, MemberProfile, OperatingLocation

def why_radio_outdoors(request):
    return render(request, "core/why_radio_outdoors.html")

def support_radio_outdoors(request):
    return render(request, "core/support.html")

def help_center(request):
    return render(request, "help/index.html")

@staff_member_required
def stewardship_dashboard(request):
    return render(request, "stewardship/dashboard.html", {
        "member_count": MemberProfile.objects.exclude(callsign="").count(),
        "follower_count": FollowRelationship.objects.filter(status=FollowRelationship.Status.APPROVED).count(),
        "public_adventure_count": Adventure.objects.filter(is_public=True).count(),
        "location_count": Location.objects.count(),
        "position_count": OperatingLocation.objects.count(),
        "advisory_count": Location.objects.filter(has_operating_advisory=True).count(),
        "blocked_domain_count": BlockedDomain.objects.filter(is_active=True).count(),
        "recent_adventures": Adventure.objects.select_related("owner", "location").order_by("-updated_at")[:10],
    })

@staff_member_required
def stewardship_security(request):
    return render(request, "stewardship/security.html", {"domains": BlockedDomain.objects.order_by("domain")})
