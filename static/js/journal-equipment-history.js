document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-equipment-history-target]").forEach((select) => {
    select.addEventListener("change", () => {
      if (!select.value) return;
      const input = document.getElementById(select.dataset.equipmentHistoryTarget);
      if (!input) return;
      input.value = select.value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
      select.selectedIndex = 0;
    });
  });
});
