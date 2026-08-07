from django.urls import path

from .adif_views import (
    cancel_adif_import,
    confirm_adif_import,
    import_adif,
    preview_adif_import,
)

from .views import (
    add_adventure,
    add_comment,
    add_journal_entry,
    add_operating_position,
    adventure_detail,
    all_adventures,
    cancel_adif_import,
    confirm_adif_import,
    create_location,
    create_operating_position_inline,
    delete_comment,
    toggle_journal_visibility,
    toggle_adventure_visibility,
    delete_selected_contacts,
    delete_adventure,
    delete_journal_entry,
    delete_photo,
    edit_adventure,
    edit_journal_entry,
    edit_location,
    import_adif,
    journal_entry_detail,
    make_cover_photo,
    mark_adventure_done,
    mark_adventure_in_progress,
    my_adventures,
    start_adventure_here,
    preview_adif_import,
)

urlpatterns = [
    path("", my_adventures, name="my_adventures"),
    path("all/", all_adventures, name="all_adventures"),
    path("add/", add_adventure, name="add_adventure"),
    path(
        "locations/<int:location_id>/start/",
        start_adventure_here,
        name="start_adventure_here",
    ),
    path("locations/create/", create_location, name="create_location"),
    path(
        "locations/<int:location_id>/positions/add/",
        add_operating_position,
        name="add_operating_position",
    ),
    path(
        "locations/<int:location_id>/positions/inline/",
        create_operating_position_inline,
        name="create_operating_position_inline",
    ),
    path(
        "locations/<int:location_id>/edit/",
        edit_location,
        name="edit_location",
    ),
    path("<slug:slug>/comments/add/", add_comment, name="add_comment"),
    path(
        "<slug:slug>/visibility/",
        toggle_adventure_visibility,
        name="toggle_adventure_visibility",
    ),
    path(
        "<slug:slug>/delete/",
        delete_adventure,
        name="delete_adventure",
    ),
    path("comments/<int:comment_id>/delete/", delete_comment, name="delete_comment"),
    path("journal/<int:entry_id>/", journal_entry_detail, name="journal_entry_detail"),
    path("journal/<int:entry_id>/edit/", edit_journal_entry, name="edit_journal_entry"),
    path(
        "journal/<int:entry_id>/visibility/",
        toggle_journal_visibility,
        name="toggle_journal_visibility",
    ),
    path(
        "journal/<int:entry_id>/contacts/delete-selected/",
        delete_selected_contacts,
        name="delete_selected_contacts",
    ),
    path(
        "journal/<int:entry_id>/contacts/import/",
        import_adif,
        name="import_adif",
    ),
    path(
        "journal/<int:entry_id>/contacts/preview/<str:token>/",
        preview_adif_import,
        name="preview_adif_import",
    ),
    path(
        "journal/<int:entry_id>/contacts/confirm/<str:token>/",
        confirm_adif_import,
        name="confirm_adif_import",
    ),
    path(
        "journal/<int:entry_id>/contacts/cancel/<str:token>/",
        cancel_adif_import,
        name="cancel_adif_import",
    ),
    path("journal/<int:entry_id>/delete/", delete_journal_entry, name="delete_journal_entry"),
    path("photos/<int:photo_id>/cover/", make_cover_photo, name="make_cover_photo"),
    path("photos/<int:photo_id>/delete/", delete_photo, name="delete_photo"),
    path("<slug:slug>/edit/", edit_adventure, name="edit_adventure"),
    path("<slug:slug>/done/", mark_adventure_done, name="mark_adventure_done"),
    path(
        "<slug:slug>/in-progress/",
        mark_adventure_in_progress,
        name="mark_adventure_in_progress",
    ),
    path(
        "<slug:slug>/journal/add/",
        add_journal_entry,
        name="add_journal_entry",
    ),
    path("<slug:slug>/", adventure_detail, name="adventure_detail"),
]

