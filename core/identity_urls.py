from django.urls import path
from .identity_views import help_center, stewardship_dashboard, stewardship_security, support_radio_outdoors, why_radio_outdoors
urlpatterns=[
 path("why/",why_radio_outdoors,name="why_radio_outdoors"),
 path("support/",support_radio_outdoors,name="support_radio_outdoors"),
 path("help/",help_center,name="help_center"),
 path("stewardship/",stewardship_dashboard,name="stewardship_dashboard"),
 path("stewardship/security/",stewardship_security,name="stewardship_security"),
]
