import re

from django import forms
from django.contrib.auth.forms import SetPasswordForm


def normalize_mobile_phone(value):
    value = value.strip()
    if not re.fullmatch(r"\+[1-9]\d{7,14}", value):
        raise forms.ValidationError("Enter a mobile number in E.164 format, such as +16515551212.")
    return value


class MobilePhoneForm(forms.Form):
    mobile_phone = forms.CharField(label="Mobile phone", max_length=16)

    def clean_mobile_phone(self):
        return normalize_mobile_phone(self.cleaned_data["mobile_phone"])


class VerificationCodeForm(forms.Form):
    code = forms.CharField(label="Verification code", min_length=4, max_length=10)

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code.isdigit():
            raise forms.ValidationError("Enter the numeric verification code.")
        return code


class SmsRecoveryStartForm(forms.Form):
    identity = forms.CharField(label="Callsign or email", max_length=254)


class SmsPasswordResetForm(SetPasswordForm):
    pass
