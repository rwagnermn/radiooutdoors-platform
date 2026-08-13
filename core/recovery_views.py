from django.conf import settings
from django.contrib.auth.views import (
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.crypto import salted_hmac


def _rate_limit_key(prefix, value):
    digest = salted_hmac(
        "radio-outdoors-account-recovery",
        value,
        secret=settings.SECRET_KEY,
    ).hexdigest()
    return f"account-recovery:{prefix}:{digest}"


def _within_rate_limit(key, *, limit=None, timeout=None):
    timeout = settings.PASSWORD_RESET_RATE_LIMIT_WINDOW if timeout is None else timeout
    limit = settings.PASSWORD_RESET_RATE_LIMIT if limit is None else limit
    if cache.add(key, 1, timeout=timeout):
        return True
    try:
        attempts = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        attempts = 1
    return attempts <= limit


class RadioOutdoorsPasswordResetView(PasswordResetView):
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.txt"
    html_email_template_name = "registration/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"
    success_url = reverse_lazy("account_recovery_done")
    from_email = settings.DEFAULT_FROM_EMAIL
    extra_email_context = {
        "contact_email": settings.RADIO_OUTDOORS_CONTACT_EMAIL,
    }

    def post(self, request, *args, **kwargs):
        email = (request.POST.get("email") or "").strip().casefold()
        remote_address = request.META.get("REMOTE_ADDR", "unknown")
        allowed = _within_rate_limit(_rate_limit_key("ip", remote_address))
        if email:
            allowed = (
                _within_rate_limit(_rate_limit_key("email", email)) and allowed
            )
        if not allowed:
            return redirect(self.success_url)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        opts = {
            "use_https": (
                settings.PASSWORD_RESET_USE_HTTPS or self.request.is_secure()
            ),
            "token_generator": self.token_generator,
            "from_email": self.from_email,
            "email_template_name": self.email_template_name,
            "subject_template_name": self.subject_template_name,
            "request": self.request,
            "html_email_template_name": self.html_email_template_name,
            "extra_email_context": self.extra_email_context,
        }
        if settings.PASSWORD_RESET_DOMAIN:
            opts["domain_override"] = settings.PASSWORD_RESET_DOMAIN
        form.save(**opts)
        return HttpResponseRedirect(self.get_success_url())


class RadioOutdoorsPasswordResetDoneView(PasswordResetDoneView):
    template_name = "registration/password_reset_done.html"


class RadioOutdoorsPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("account_recovery_complete")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.validlink and self.user:
            context["password_identity"] = {
                "username": self.user.get_username(),
                "email": self.user.email,
                "first_name": self.user.first_name,
                "last_name": self.user.last_name,
            }
        return context


class RadioOutdoorsPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "registration/password_reset_complete.html"
