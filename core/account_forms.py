from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import BlockedDomain, MemberProfile


User = get_user_model()


def validate_registration_email(email):
    email = email.strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        raise forms.ValidationError(
            "An account already uses that email address."
        )
    domain = email.rsplit("@", 1)[-1]
    if BlockedDomain.objects.filter(
        domain__iexact=domain,
        is_active=True,
    ).exists():
        raise forms.ValidationError(
            "Accounts using that email domain are not accepted."
        )
    return email


class MemberRegistrationForm(UserCreationForm):
    callsign = forms.CharField(
        label="Callsign",
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "characters",
                "placeholder": "W5RIK",
            }
        ),
    )
    email = forms.EmailField(
        label="Email address",
        help_text="Private by default and not displayed publicly.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("callsign", "email", "password1", "password2")

    def clean_callsign(self):
        callsign = self.cleaned_data["callsign"].strip().upper()
        if not callsign:
            raise forms.ValidationError("Enter a callsign.")
        if MemberProfile.objects.filter(callsign__iexact=callsign).exists():
            raise forms.ValidationError("That callsign is already registered.")
        if User.objects.filter(username__iexact=callsign).exists():
            raise forms.ValidationError("That callsign is already registered.")
        return callsign

    def clean_email(self):
        return validate_registration_email(self.cleaned_data["email"])

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["callsign"]
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class FollowerRegistrationForm(UserCreationForm):
    email = forms.EmailField(
        label="Email address",
        disabled=True,
        help_text="This must match the address on your invitation.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "password1", "password2")

    def __init__(self, *args, invitation, **kwargs):
        self.invitation = invitation
        initial = kwargs.setdefault("initial", {})
        initial["email"] = invitation.email
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = validate_registration_email(self.cleaned_data["email"])
        submitted_email = (self.data.get("email") or "").strip().lower()
        if submitted_email and submitted_email != self.invitation.email.strip().lower():
            raise forms.ValidationError(
                "The email address must match the invitation."
            )
        if email != self.invitation.email.strip().lower():
            raise forms.ValidationError(
                "The email address must match the invitation."
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"]
        user.email = self.cleaned_data["email"]
        name_parts = self.invitation.name.strip().split(maxsplit=1)
        user.first_name = name_parts[0] if name_parts else ""
        user.last_name = name_parts[1] if len(name_parts) > 1 else ""
        if commit:
            user.save()
        return user


# Transitional import compatibility for code outside this project.
RadioOutdoorsRegistrationForm = MemberRegistrationForm
