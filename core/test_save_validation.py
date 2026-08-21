from django import forms
from django.forms import formset_factory
from django.template import Context, Template
from django.test import SimpleTestCase

from core.form_validation import (
    GENERAL_SAVE_MESSAGE,
    REQUIRED_SAVE_MESSAGE,
    form_error_payload,
)


class ExampleSaveForm(forms.Form):
    title = forms.CharField()
    code = forms.CharField(required=False)

    def clean_code(self):
        value = self.cleaned_data.get("code")
        if value == "bad":
            raise forms.ValidationError("Code is not valid.", code="invalid")
        return value


class SaveValidationSummaryTests(SimpleTestCase):
    template = Template(
        "{% load form_validation %}{% save_error_summary %}"
        "{{ form.title }}{{ form.title.errors }}"
    )

    def test_required_error_uses_required_message_and_accessible_markup(self):
        form = ExampleSaveForm({"title": "", "code": "kept"})
        html = self.template.render(Context({"form": form}))

        self.assertIn(REQUIRED_SAVE_MESSAGE, html)
        self.assertIn('role="alert"', html)
        self.assertIn('tabindex="-1"', html)
        self.assertIn('href="#id_title"', html)
        self.assertIn('aria-invalid="true"', html)
        self.assertIn('aria-describedby="save-error-summary"', html)
        self.assertEqual(form.data["code"], "kept")

    def test_nonrequired_error_uses_general_message(self):
        form = ExampleSaveForm({"title": "kept", "code": "bad"})
        html = self.template.render(Context({"form": form}))
        self.assertIn(GENERAL_SAVE_MESSAGE, html)
        self.assertNotIn(REQUIRED_SAVE_MESSAGE, html)

    def test_unbound_and_valid_forms_do_not_show_summary(self):
        self.assertEqual(self.template.render(Context({"form": ExampleSaveForm()})), '<input type="text" name="title" required id="id_title">')
        self.assertNotIn("save-error-summary", self.template.render(Context({"form": ExampleSaveForm({"title": "ok"})})))

    def test_formset_errors_are_discovered_with_prefixed_unique_ids(self):
        ExampleSet = formset_factory(ExampleSaveForm, extra=2)
        formset = ExampleSet({
            "form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
            "form-0-title": "", "form-0-code": "one",
            "form-1-title": "", "form-1-code": "two",
        })
        html = Template("{% load form_validation %}{% save_error_summary %}{{ formset }}").render(Context({"formset": formset}))
        self.assertIn('href="#id_form-0-title"', html)
        self.assertIn('href="#id_form-1-title"', html)
        self.assertEqual(html.count('aria-invalid="true"'), 2)

    def test_json_payload_uses_same_messages_and_structured_errors(self):
        required = ExampleSaveForm({"title": ""})
        required.is_valid()
        payload = form_error_payload(required)
        self.assertEqual(payload["message"], REQUIRED_SAVE_MESSAGE)
        self.assertTrue(payload["required_missing"])
        self.assertEqual(payload["errors"]["title"][0]["code"], "required")

        invalid = ExampleSaveForm({"title": "kept", "code": "bad"})
        invalid.is_valid()
        self.assertEqual(form_error_payload(invalid)["message"], GENERAL_SAVE_MESSAGE)
