from .auth import is_verified_member


def can_edit_location_pin(user, location):
    return bool(
        user.is_authenticated
        and user.is_active
        and (
            user.is_staff
            or (is_verified_member(user) and location.created_by_id == user.pk)
        )
    )


def can_edit_operating_position_pin(user, position):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_staff:
        return True
    if not is_verified_member(user):
        return False
    if position.location.is_private:
        return position.location.created_by_id == user.pk
    return bool(
        position.created_by_id == user.pk
        or position.adventures.filter(owner=user).exists()
    )
