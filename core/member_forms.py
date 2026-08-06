from django import forms
from .models import MemberProfile


class MemberProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)

    class Meta:
        model = MemberProfile
        fields = [
            "callsign",
            "display_name",
            "bio",
            "home_city",
            "home_state",
            "home_country",
            "website",
            "profile_is_public",
            "email_visible_to_members",
        ]
        widgets = {
            "callsign": forms.TextInput(
                attrs={
                    "placeholder": "W5RIK, VE3ABC, DL7XYZ...",
                    "autocomplete": "off",
                    "autocapitalize": "characters",
                }
            ),
            "bio": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email

    def clean_callsign(self):
        callsign = self.cleaned_data["callsign"].strip().upper()
        if not callsign:
            raise forms.ValidationError("Enter a callsign.")
        duplicate = MemberProfile.objects.filter(
            callsign__iexact=callsign
        ).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("That callsign is already registered.")
        return callsign

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user:
            self.user.first_name = self.cleaned_data["first_name"].strip()
            self.user.last_name = self.cleaned_data["last_name"].strip()
            self.user.email = self.cleaned_data["email"].strip()
            if commit:
                self.user.save(update_fields=["first_name", "last_name", "email"])
        if commit:
            profile.save()
        return profile


class MemberDeleteForm(forms.Form):
    callsign = forms.CharField(
        label="Type the callsign to confirm deletion",
        max_length=20,
    )

    def __init__(self, *args, expected_callsign="", **kwargs):
        self.expected_callsign = expected_callsign.upper()
        super().__init__(*args, **kwargs)

    def clean_callsign(self):
        value = self.cleaned_data["callsign"].strip().upper()
        if value != self.expected_callsign:
            raise forms.ValidationError("The callsign does not match.")
        return value
