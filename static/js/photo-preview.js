(function () {
    "use strict";

    document.querySelectorAll("[data-photo-preview]").forEach(function (control) {
        const input = control.querySelector('input[type="file"]');
        const stage = control.querySelector("[data-photo-preview-stage]");
        const status = control.querySelector("[data-photo-preview-status]");
        const loadButton = control.querySelector("[data-photo-preview-load]");
        const changeButton = control.querySelector("[data-photo-preview-change]");
        const clearButton = control.querySelector("[data-photo-preview-clear]");
        const removeButton = control.querySelector("[data-photo-preview-remove]");
        const removeFieldName = control.dataset.photoPreviewRemoveField ||
            "remove_profile_photo";
        const removeField = control.querySelector(
            'input[name$="' + removeFieldName + '"]'
        );
        const saveLabel = control.dataset.photoPreviewSaveLabel || "Profile";
        const mode = control.dataset.photoPreviewMode || "single";
        const objectUrls = [];

        if (!input || !stage || !status || !loadButton) {
            return;
        }

        const image = stage.querySelector("[data-photo-preview-image]");
        const originalSource = stage.dataset.originalSrc || "";
        const placeholderSource = stage.dataset.placeholderSrc || "";
        const originalWasPlaceholder = Boolean(
            image && image.classList.contains("member-profile-photo-placeholder")
        );

        function revokeObjectUrls() {
            while (objectUrls.length) {
                URL.revokeObjectURL(objectUrls.pop());
            }
        }

        function selectedFiles() {
            return Array.from(input.files || []);
        }

        function setRemoveValue(value) {
            if (removeField) {
                removeField.value = value ? "on" : "";
            }
        }

        function restoreOriginalPreview() {
            revokeObjectUrls();
            if (mode === "single" && image) {
                image.src = originalSource;
                image.classList.toggle(
                    "member-profile-photo-placeholder",
                    originalWasPlaceholder
                );
            } else {
                stage.replaceChildren();
            }
        }

        input.addEventListener("change", function () {
            const count = selectedFiles().length;
            setRemoveValue(false);
            status.textContent = count
                ? count + " photo" + (count === 1 ? "" : "s") +
                    " selected. Select " +
                    (mode === "single" ? "Load Photo" : "Load Photos") +
                    " to preview."
                : "No new photo selected.";
        });

        loadButton.addEventListener("click", function () {
            const files = selectedFiles();
            if (!files.length) {
                status.textContent = "Choose a photo file first.";
                input.focus();
                return;
            }

            revokeObjectUrls();
            setRemoveValue(false);

            if (mode === "single" && image) {
                const objectUrl = URL.createObjectURL(files[0]);
                objectUrls.push(objectUrl);
                image.src = objectUrl;
                image.classList.remove("member-profile-photo-placeholder");
                status.textContent =
                    "Preview loaded. Save " + saveLabel + " to keep this photo.";
                return;
            }

            stage.replaceChildren();
            files.forEach(function (file) {
                const objectUrl = URL.createObjectURL(file);
                objectUrls.push(objectUrl);
                const figure = document.createElement("figure");
                const previewImage = document.createElement("img");
                const caption = document.createElement("figcaption");
                previewImage.src = objectUrl;
                previewImage.alt = "Selected Journal photo preview";
                caption.textContent = file.name;
                figure.append(previewImage, caption);
                stage.append(figure);
            });
            status.textContent =
                files.length + " photo" + (files.length === 1 ? "" : "s") +
                " previewed. Save the Journal Entry to upload " +
                (files.length === 1 ? "it." : "them.");
        });

        if (changeButton) {
            changeButton.addEventListener("click", function () {
                input.click();
            });
        }

        if (clearButton) {
            clearButton.addEventListener("click", function () {
                input.value = "";
                setRemoveValue(false);
                restoreOriginalPreview();
                status.textContent = mode === "single"
                    ? "New selection cleared. The saved photo is unchanged."
                    : "Photo selection cleared. Nothing will be uploaded.";
            });
        }

        if (removeButton && image) {
            removeButton.addEventListener("click", function () {
                input.value = "";
                revokeObjectUrls();
                setRemoveValue(true);
                image.src = placeholderSource;
                image.classList.add("member-profile-photo-placeholder");
                status.textContent =
                    "The saved photo will be removed only when Save " +
                    saveLabel + " is selected.";
            });
        }

        window.addEventListener("beforeunload", revokeObjectUrls);
    });
}());
