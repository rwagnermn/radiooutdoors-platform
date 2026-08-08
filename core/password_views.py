from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import get_default_password_validators
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST


VALIDATOR_REQUIREMENTS = {
    "MinimumLengthValidator": "minimum_length",
    "UserAttributeSimilarityValidator": "not_similar",
    "CommonPasswordValidator": "not_common",
    "NumericPasswordValidator": "not_numeric",
}


def _candidate_user(request):
    if request.user.is_authenticated:
        return request.user
    User = get_user_model()
    return User(
        username=(request.POST.get("username") or "").strip(),
        email=(request.POST.get("email") or "").strip(),
        first_name=(request.POST.get("first_name") or "").strip(),
        last_name=(request.POST.get("last_name") or "").strip(),
    )


@sensitive_post_parameters("password")
@never_cache
@require_POST
def password_requirement_status(request):
    password = request.POST.get("password") or ""
    statuses = {requirement: False for requirement in VALIDATOR_REQUIREMENTS.values()}
    if password:
        user = _candidate_user(request)
        for validator in get_default_password_validators():
            requirement = VALIDATOR_REQUIREMENTS.get(type(validator).__name__)
            if not requirement:
                continue
            try:
                validator.validate(password, user)
            except ValidationError:
                statuses[requirement] = False
            else:
                statuses[requirement] = True
    return JsonResponse({"requirements": statuses})
