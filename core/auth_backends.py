from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .models import MemberProfile


class UsernameOrCallsignBackend(ModelBackend):
    """Authenticate with an exact username or a uniquely matching callsign."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        login_name = username or kwargs.get(UserModel.USERNAME_FIELD)
        if login_name is None or password is None:
            return None

        try:
            user = UserModel._default_manager.get(
                **{UserModel.USERNAME_FIELD: login_name}
            )
        except UserModel.DoesNotExist:
            matching_user_ids = list(
                MemberProfile.objects.filter(callsign__iexact=login_name)
                .values_list("user_id", flat=True)[:2]
            )
            if len(matching_user_ids) != 1:
                return super().authenticate(
                    request, username=login_name, password=password, **kwargs
                )
            try:
                user = UserModel._default_manager.get(pk=matching_user_ids[0])
            except UserModel.DoesNotExist:
                return super().authenticate(
                    request, username=login_name, password=password, **kwargs
                )

        return super().authenticate(
            request,
            username=user.get_username(),
            password=password,
            **kwargs,
        )
