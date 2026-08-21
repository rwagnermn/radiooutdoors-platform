"""Shared validation responses for save actions."""

REQUIRED_SAVE_MESSAGE = (
    "Save was not completed because required information is missing. "
    "Please complete the highlighted fields."
)
GENERAL_SAVE_MESSAGE = "Save was not completed. Please correct the highlighted information."


def form_has_required_errors(form):
    return any(
        error.code == "required"
        for errors in form.errors.as_data().values()
        for error in errors
    )


def form_error_payload(form):
    required_missing = form_has_required_errors(form)
    return {
        "message": REQUIRED_SAVE_MESSAGE if required_missing else GENERAL_SAVE_MESSAGE,
        "required_missing": required_missing,
        "errors": form.errors.get_json_data(),
    }


def validation_error_payload(errors, *, required_missing=False):
    return {
        "message": REQUIRED_SAVE_MESSAGE if required_missing else GENERAL_SAVE_MESSAGE,
        "required_missing": required_missing,
        "errors": errors,
    }
