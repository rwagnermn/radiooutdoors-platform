from django import forms, template
from django.forms.formsets import BaseFormSet
from django.utils.html import format_html, format_html_join

from core.form_validation import GENERAL_SAVE_MESSAGE, REQUIRED_SAVE_MESSAGE

register = template.Library()


def _forms_in_context(context):
    seen = set()
    for value in context.flatten().values():
        candidates = value.forms if isinstance(value, BaseFormSet) else [value]
        for candidate in candidates:
            if isinstance(candidate, forms.BaseForm) and id(candidate) not in seen:
                seen.add(id(candidate))
                yield candidate


@register.simple_tag(takes_context=True)
def save_error_summary(context):
    forms_with_errors = []
    required_missing = bool(context.get("save_validation_required", False))
    items = []

    for form in _forms_in_context(context):
        if not form.is_bound or not form.errors:
            continue
        forms_with_errors.append(form)
        for field_name, errors in form.errors.as_data().items():
            if field_name == forms.forms.NON_FIELD_ERRORS:
                items.extend((None, str(message)) for error in errors for message in error.messages)
                required_missing = required_missing or any(error.code == "required" for error in errors)
                continue
            field = form.fields.get(field_name)
            if not field:
                continue
            bound_field = form[field_name]
            field.widget.attrs["aria-invalid"] = "true"
            described_by = field.widget.attrs.get("aria-describedby", "").split()
            if "save-error-summary" not in described_by:
                described_by.append("save-error-summary")
            field.widget.attrs["aria-describedby"] = " ".join(described_by)
            required_missing = required_missing or any(error.code == "required" for error in errors)
            items.extend((bound_field.auto_id or None, f"{bound_field.label}: {message}") for error in errors for message in error.messages)

    manual_errors = context.get("save_validation_errors") or []
    items.extend((None, str(message)) for message in manual_errors)
    if not forms_with_errors and not manual_errors:
        return ""

    message = REQUIRED_SAVE_MESSAGE if required_missing else GENERAL_SAVE_MESSAGE
    links = format_html_join(
        "",
        "<li>{}</li>",
        ((format_html('<a href="#{}">{}</a>', field_id, text) if field_id else text,) for field_id, text in items),
    )
    return format_html(
        '<section id="save-error-summary" class="form-error-summary save-error-summary" '
        'role="alert" aria-live="assertive" tabindex="-1" data-save-error-summary>'
        '<h2>{}</h2><ul class="form-error-list">{}</ul></section>',
        message,
        links,
    )
