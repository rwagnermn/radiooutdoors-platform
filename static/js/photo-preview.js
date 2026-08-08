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
        const pasteZone = control.querySelector("[data-photo-paste-zone]");
        const removeFieldName = control.dataset.photoPreviewRemoveField ||
            "remove_profile_photo";
        const removeField = control.querySelector(
            'input[name$="' + removeFieldName + '"]'
        );
        const saveLabel = control.dataset.photoPreviewSaveLabel || "Profile";
        const mode = control.dataset.photoPreviewMode || "single";
        const objectUrls = [];
        let previousSingleFiles = [];

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

        function setSelectedFiles(files) {
            const transfer = new DataTransfer();
            files.forEach(function (file) {
                transfer.items.add(file);
            });
            input.files = transfer.files;
        }

        function acceptImages(files, source) {
            const images = files.filter(function (file) {
                return file.type && file.type.indexOf("image/") === 0;
            });
            if (!images.length) {
                status.textContent = "The clipboard does not contain an image.";
                return;
            }
            let combined;
            if (mode === "single") {
                if (selectedFiles().length && !window.confirm("Replace the currently selected Location photo?")) {
                    return;
                }
                combined = [images[0]];
            } else {
                combined = selectedFiles().concat(images);
            }
            setSelectedFiles(combined);
            if (mode === "single") previousSingleFiles = combined.slice();
            setRemoveValue(false);
            if (mode === "single" && image) {
                revokeObjectUrls();
                const objectUrl = URL.createObjectURL(combined[0]);
                objectUrls.push(objectUrl);
                image.src = objectUrl;
                image.classList.remove("member-profile-photo-placeholder");
            } else {
                renderMultiplePreview(combined);
            }
            status.textContent = combined.length + " photo" + (combined.length === 1 ? "" : "s") +
                " selected from " + source + ". Nothing is saved until the form is saved.";
        }

        function renderMultiplePreview(files) {
            revokeObjectUrls();
            stage.replaceChildren();
            files.forEach(function (file, index) {
                const objectUrl = URL.createObjectURL(file);
                objectUrls.push(objectUrl);
                const figure = document.createElement("figure");
                const previewImage = document.createElement("img");
                const caption = document.createElement("figcaption");
                const removeSelection = document.createElement("button");
                previewImage.src = objectUrl;
                previewImage.alt = "Selected Journal photo preview";
                caption.textContent = file.name;
                removeSelection.type = "button";
                removeSelection.className = "photo-preview-remove-selection";
                removeSelection.textContent = "Remove";
                removeSelection.setAttribute(
                    "aria-label",
                    "Remove " + file.name + " from this upload"
                );
                removeSelection.addEventListener("click", function () {
                    const remaining = selectedFiles().filter(function (_, itemIndex) {
                        return itemIndex !== index;
                    });
                    setSelectedFiles(remaining);
                    renderMultiplePreview(remaining);
                    status.textContent = remaining.length
                        ? remaining.length + " photo" +
                            (remaining.length === 1 ? " remains" : "s remain") +
                            " selected."
                        : "Photo selection cleared. Nothing will be uploaded.";
                });
                figure.append(previewImage, caption, removeSelection);
                stage.append(figure);
            });
        }

        input.addEventListener("change", function () {
            let files = selectedFiles();
            if (mode === "single" && files.length > 1) {
                files = [files[files.length - 1]];
                setSelectedFiles(files);
            }
            if (mode === "single" && previousSingleFiles.length && files.length &&
                    previousSingleFiles[0] !== files[0] &&
                    !window.confirm("Replace the currently selected Location photo?")) {
                setSelectedFiles(previousSingleFiles);
                files = previousSingleFiles;
            } else if (mode === "single") {
                previousSingleFiles = files.slice();
            }
            const count = files.length;
            setRemoveValue(false);
            status.textContent = count
                ? count + " photo" + (count === 1 ? "" : "s") +
                    " selected. Select " +
                    (mode === "single" ? "Load Photo" : "Load Photos") +
                    " to preview."
                : "No new photo selected.";
        });

        if (pasteZone) {
            pasteZone.addEventListener("click", function () { pasteZone.focus(); });
            pasteZone.addEventListener("paste", function (event) {
                const files = Array.from((event.clipboardData && event.clipboardData.files) || []);
                if (files.length) event.preventDefault();
                acceptImages(files, "the clipboard");
            });
        }

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

            renderMultiplePreview(files);
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
                previousSingleFiles = [];
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
