from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import BlockedDomain, MemberProfile


User = get_user_model()


class PolicyAcceptanceFormMixin(forms.Form):
    policy_accepted = forms.BooleanField(
        required=True,
        label="Policy acceptance",
        error_messages={
            "required": "You must read and agree to the required policies before creating an account."
        },
        widget=forms.CheckboxInput(attrs={"data-policy-required": "true"}),
    )
    age_confirmed = forms.BooleanField(
        required=True,
        label="Age confirmation",
        error_messages={
            "required": "You must confirm the age requirement before creating an account."
        },
        widget=forms.CheckboxInput(attrs={"data-policy-required": "true"}),
    )


def validate_registration_email(email):
    email = email.strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        raise forms.ValidationError(
            "That email address is already connected to a Radio Outdoors account. Log in or use Forgot callsign or password.",
            code="duplicate_email",
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


class MemberRegistrationForm(PolicyAcceptanceFormMixin, UserCreationForm):
    callsign = forms.CharField(
        label="Callsign",
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "characters",
                "placeholder": "W5RIK or DL1ABC",
            }
        ),
    )
    email = forms.EmailField(
        label="Email address",
        help_text="Private by default and not displayed publicly.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "callsign", "email", "password1", "password2",
            "policy_accepted", "age_confirmed",
        )

    def clean_callsign(self):
        callsign = self.cleaned_data["callsign"].strip().upper()
        if not callsign:
            raise forms.ValidationError("Enter a callsign.")
        existing_profile = MemberProfile.objects.select_related("user").filter(
            callsign__iexact=callsign
        ).first()
        existing_user = User.objects.filter(username__iexact=callsign).first()
        existing_account = existing_profile.user if existing_profile else existing_user
        if existing_account and not existing_account.is_active:
            raise forms.ValidationError(
                "This callsign belongs to a deactivated Radio Outdoors account. Request reactivation instead of creating a second account.",
                code="inactive_account",
            )
        if existing_profile:
            raise forms.ValidationError("That callsign is already registered.")
        if existing_user:
            raise forms.ValidationError("That callsign is already registered.")
        return callsign

    @property
    def has_inactive_account_error(self):
        return any(
            error.code == "inactive_account"
            for error in self.errors.as_data().get("callsign", [])
        )

    def clean_email(self):
        return validate_registration_email(self.cleaned_data["email"])

    @property
    def has_duplicate_email_error(self):
        return any(
            error.code == "duplicate_email"
            for error in self.errors.as_data().get("email", [])
        )

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["callsign"]
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class FollowerRegistrationForm(PolicyAcceptanceFormMixin, UserCreationForm):
    email = forms.EmailField(
        label="Email address",
        disabled=True,
        help_text="This must match the address on your invitation.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "email", "password1", "password2",
            "policy_accepted", "age_confirmed",
        )

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
