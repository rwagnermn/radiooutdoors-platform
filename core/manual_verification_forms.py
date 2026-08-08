from django import forms

from .models import ManualVerificationRequest


class ManualVerificationRequestForm(forms.ModelForm):
    class Meta:
        model = ManualVerificationRequest
        fields = (
            "full_name",
            "country",
            "authority_url",
            "explanation",
        )
        widgets = {
            "explanation": forms.Textarea(attrs={"rows": 5}),
        }

    def clean_full_name(self):
        return self.cleaned_data["full_name"].strip()

    def clean_country(self):
        return self.cleaned_data["country"].strip()


class ManualVerificationReviewForm(forms.Form):
    action = forms.ChoiceField(
        choices=(
            ("approve", "Approve"),
            ("more_info", "Request More Information"),
            ("reject", "Reject"),
        )
    )
    reviewer_message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("action") in {"more_info", "reject"} and not (
            cleaned.get("reviewer_message") or ""
        ).strip():
            self.add_error(
                "reviewer_message",
                "Enter a message explaining what the applicant should do next.",
            )
        return cleaned
