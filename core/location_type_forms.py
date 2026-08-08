from django import forms

from .models import LocationType


class LocationTypeForm(forms.ModelForm):
    class Meta:
        model = LocationType
        fields = ["name", "is_active"]
        labels = {
            "name": "Name",
            "is_active": "Active",
        }

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Enter a Location Type name.")
        duplicate = LocationType.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("A Location Type with this name already exists.")
        return name
