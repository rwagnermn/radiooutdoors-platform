from django.urls import path

from .account_views import account_home, register


urlpatterns = [
    path("register/", register, name="register"),
    path("", account_home, name="account_home"),
]
