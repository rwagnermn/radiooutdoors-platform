(function () {
    "use strict";
    const gallery = document.querySelector("[data-photo-gallery]");
    if (!gallery) return;
    const boxes = Array.from(gallery.querySelectorAll("[data-photo-checkbox]"));
    const count = gallery.querySelector("[data-photo-selected-count]");
    const deleteSelected = gallery.querySelector("[data-photo-delete-selected]");
    const dialog = gallery.querySelector("[data-photo-delete-dialog]");
    const form = gallery.querySelector("[data-photo-delete-form]");
    const modeInput = gallery.querySelector("[data-photo-delete-mode]");
    const ids = gallery.querySelector("[data-photo-delete-ids]");
    const title = gallery.querySelector("[data-photo-delete-title]");
    const message = gallery.querySelector("[data-photo-delete-message]");
    const confirmButton = gallery.querySelector("[data-photo-delete-confirm]");
    const selected = () => boxes.filter((box) => box.checked);
    function update() { const total = selected().length; count.textContent = total; deleteSelected.disabled = total === 0; }
    function openDelete(mode, selectedBoxes, reference) {
        const total = mode === "all" ? boxes.length : selectedBoxes.length;
        modeInput.value = mode;
        ids.replaceChildren(...selectedBoxes.map((box) => { const input = document.createElement("input"); input.type = "hidden"; input.name = "photo_ids"; input.value = box.value; return input; }));
        const individual = mode === "individual";
        title.textContent = individual ? "Delete Photo?" : mode === "all" ? "Delete All Photos?" : "Delete Selected Photos?";
        message.textContent = individual ? `Delete ${reference} from ${gallery.dataset.journalName}?` : `${mode === "all" ? "Delete All" : "Delete Selected"} will permanently delete ${total} photo${total === 1 ? "" : "s"} from ${gallery.dataset.journalName}.`;
        confirmButton.textContent = individual ? "Delete Photo" : mode === "all" ? "Delete All Photos" : "Delete Selected Photos";
        dialog.showModal();
    }
    boxes.forEach((box) => box.addEventListener("change", update));
    gallery.querySelector("[data-photo-select-all]")?.addEventListener("click", () => { boxes.forEach((box) => { box.checked = true; }); update(); });
    gallery.querySelector("[data-photo-clear]")?.addEventListener("click", () => { boxes.forEach((box) => { box.checked = false; }); update(); });
    deleteSelected?.addEventListener("click", () => openDelete("selected", selected()));
    gallery.querySelector("[data-photo-delete-all]")?.addEventListener("click", () => openDelete("all", []));
    gallery.querySelectorAll("[data-photo-delete-one]").forEach((button) => button.addEventListener("click", () => {
        const box = boxes.find((item) => item.value === button.dataset.photoDeleteOne);
        openDelete("individual", [box], button.closest("[data-photo-id]").dataset.photoReference);
    }));
    gallery.querySelector("[data-photo-delete-cancel]")?.addEventListener("click", () => dialog.close());
    dialog?.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    form?.addEventListener("submit", () => { confirmButton.disabled = true; });
    update();
})();
