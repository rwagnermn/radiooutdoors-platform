from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import BlockedDomain


class RadioOutdoorsRegistrationForm(UserCreationForm):
    first_name = forms.CharField(label="First name", max_length=150)
    last_name = forms.CharField(label="Last name", max_length=150)
    email = forms.EmailField(
        label="Email address",
        help_text=(
            "Used for follow requests and Adventure notifications. "
            "It is not displayed publicly."
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "first_name",
            "last_name",
            "email",
            "username",
            "password1",
            "password2",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
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

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.email = self.cleaned_data["email"].strip().lower()
        if commit:
            user.save()
        return user
