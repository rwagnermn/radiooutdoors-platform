from django import forms


class FollowerInvitationForm(forms.Form):
    name = forms.CharField(
        label="Name",
        max_length=150,
        widget=forms.TextInput(
            attrs={"placeholder": "Jane Wagner"}
        ),
    )
    email = forms.EmailField(
        label="Email address",
        widget=forms.EmailInput(
            attrs={"placeholder": "jane@example.com"}
        ),
    )
