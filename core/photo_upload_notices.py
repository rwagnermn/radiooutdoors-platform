from django.contrib import messages


def add_photo_upload_notice(request, statuses):
    statuses = list(statuses)
    if not statuses:
        return
    approved = sum(status == "approved" for status in statuses)
    awaiting = len(statuses) - approved
    if awaiting == 0:
        return
    if len(statuses) == 1:
        text = (
            "Photo uploaded successfully. "
            "This photo is awaiting review and will not be publicly visible until it is approved."
        )
    else:
        text = (
            f"{len(statuses)} photos were uploaded. "
            f"{awaiting} are awaiting review and {approved} "
            f"{'was' if approved == 1 else 'were'} approved."
        )
    messages.info(request, text, extra_tags="persistent photo-upload-notice")
