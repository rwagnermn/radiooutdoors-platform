(function () {
    "use strict";
    const shell = document.querySelector(".add-contacts-batch-shell");
    if (!shell) return;
    const form = shell.querySelector("[data-batch-form]");
    const tbody = shell.querySelector("[data-contact-rows]");
    const activeRow = shell.querySelector("[data-active-row]");
    const countLabels = shell.querySelectorAll("[data-contact-count]");
    const warning = shell.querySelector("[data-limit-warning]");
    const clientErrors = shell.querySelector("[data-client-errors]");
    const jsonInput = shell.querySelector("[data-contacts-json]");
    const limit = Number(shell.dataset.batchLimit || 50);
    const warningAt = Number(shell.dataset.warningAt || Math.max(1, limit - 5));
    const lookupUrl = shell.dataset.qrzUrl;
    let lookupSequence = 0;
    const fieldNames = ["qso_date", "time_on", "callsign", "band", "frequency", "mode", "signal_report", "state", "country", "comment"];
    const geographyNames = ["grid_square", "latitude", "longitude", "geography_token"];
    const defaultFieldNames = ["qso_date", "time_on", "band", "frequency", "mode"];
    const labels = {qso_date: "Date", time_on: "Time", callsign: "Callsign", band: "Band", frequency: "Frequency", mode: "Mode", signal_report: "Signal", state: "State", country: "Country", comment: "Notes"};
    const rowValues = row => ({
        ...Object.fromEntries(fieldNames.map(name => [name, row.querySelector(`[data-field="${name}"]`).value.trim()])),
        grid_square: row.dataset.gridSquare || "",
        latitude: row.dataset.latitude || "",
        longitude: row.dataset.longitude || "",
        geography_token: row.dataset.geographyToken || "",
    });
    const storedRows = () => Array.from(tbody.querySelectorAll("tr[data-unsaved-row]"));

    function updateStatus() {
        const count = storedRows().length;
        countLabels.forEach(label => { label.textContent = `${count} unsaved contact${count === 1 ? "" : "s"}`; });
        warning.hidden = count < warningAt;
    }
    function showClientErrors(errors, requiredMissing) {
        clientErrors.replaceChildren();
        if (!errors.length) { clientErrors.hidden = true; return; }
        const title = document.createElement("strong");
        title.textContent = requiredMissing
            ? "Save was not completed because required information is missing. Please complete the highlighted fields."
            : "Save was not completed. Please correct the highlighted information.";
        const list = document.createElement("ul");
        errors.forEach(message => { const item = document.createElement("li"); item.textContent = message; list.appendChild(item); });
        clientErrors.append(title, list); clientErrors.hidden = false;
    }
    function validate(values, row) {
        row.classList.remove("add-contacts-row-error");
        row.querySelectorAll("[data-field]").forEach(input => { input.classList.remove("add-contacts-field-error"); input.removeAttribute("aria-invalid"); });
        const errors = [];
        function reject(name, message) {
            const input = row.querySelector(`[data-field="${name}"]`); input.classList.add("add-contacts-field-error"); input.setAttribute("aria-invalid", "true");
            errors.push(`${labels[name]}: ${message}`);
        }
        ["qso_date", "time_on", "callsign", "band", "frequency", "mode"].forEach(name => { if (!values[name]) reject(name, "This field is required."); });
        if (values.frequency && (values.frequency.length > 7 || !/^\d+(?:\.\d+)?$/.test(values.frequency))) reject("frequency", "Use no more than seven digits and one decimal point.");
        if (values.signal_report && !/^\d{1,2}$/.test(values.signal_report)) reject("signal_report", "Use one or two digits.");
        if (values.state.length > 2) reject("state", "Use no more than two characters.");
        const key = `${values.qso_date}|${values.time_on}|${values.callsign.toUpperCase()}`;
        if (values.callsign && storedRows().some(existing => existing !== row && existing.dataset.duplicateKey === key)) reject("callsign", "This duplicates another unsaved Contact at the same Date and Time.");
        if (errors.length) row.classList.add("add-contacts-row-error");
        return errors;
    }
    function attachLookup(row) {
        const callsign = row.querySelector('[data-field="callsign"]');
        const state = row.querySelector('[data-field="state"]');
        const country = row.querySelector('[data-field="country"]');
        row.dataset.geographyEdit = row.dataset.geographyEdit || "0";
        row.dataset.callsignValue = callsign.value.trim().toUpperCase();
        if (!row.dataset.geographyToken) {
            if (state.value) row.dataset.stateManual = "1";
            if (country.value) row.dataset.countryManual = "1";
        }
        state.addEventListener("input", () => { row.dataset.geographyEdit = String(Number(row.dataset.geographyEdit || 0) + 1); row.dataset.stateManual = "1"; delete row.dataset.autoState; });
        country.addEventListener("input", () => { row.dataset.geographyEdit = String(Number(row.dataset.geographyEdit || 0) + 1); row.dataset.countryManual = "1"; delete row.dataset.autoCountry; });
        function clearQrzGeography() {
            geographyNames.forEach(name => { delete row.dataset[name.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase())]; });
            delete row.dataset.qrzCallsign;
            if (row.dataset.stateManual !== "1" && row.dataset.autoState === state.value) state.value = "";
            if (row.dataset.countryManual !== "1" && row.dataset.autoCountry === country.value) country.value = "";
            delete row.dataset.autoState; delete row.dataset.autoCountry;
        }
        callsign.addEventListener("input", () => {
            const normalized = callsign.value.trim().toUpperCase();
            if (normalized === row.dataset.callsignValue) return;
            row.dataset.callsignValue = normalized;
            row.dataset.lookupToken = String(++lookupSequence);
            delete row.dataset.lookupCallsign; delete row.dataset.lookupState;
            clearQrzGeography();
        });
        async function lookup() {
            const normalized = callsign.value.trim().toUpperCase(); callsign.value = normalized;
            row.dataset.callsignValue = normalized;
            if (row.dataset.lookupCallsign === normalized && ["pending", "complete"].includes(row.dataset.lookupState)) return;
            clearQrzGeography();
            const token = String(++lookupSequence); row.dataset.lookupToken = token;
            row.dataset.lookupCallsign = normalized; row.dataset.lookupState = "pending";
            if (!normalized) { row.dataset.lookupState = "complete"; return; }
            try {
                const response = await fetch(`${lookupUrl}?callsign=${encodeURIComponent(normalized)}`, {headers: {"X-Requested-With": "XMLHttpRequest"}});
                const result = response.ok ? await response.json() : {state: "", country: "", grid_square: "", latitude: null, longitude: null, geography_token: ""};
                if (row.dataset.lookupToken !== token || callsign.value.trim().toUpperCase() !== normalized) return;
                if (row.dataset.stateManual !== "1") { state.value = result.state || ""; row.dataset.autoState = state.value; }
                if (row.dataset.countryManual !== "1") { country.value = result.country || ""; row.dataset.autoCountry = country.value; }
                row.dataset.gridSquare = result.grid_square || "";
                row.dataset.latitude = result.latitude == null ? "" : String(result.latitude);
                row.dataset.longitude = result.longitude == null ? "" : String(result.longitude);
                row.dataset.geographyToken = result.geography_token || "";
                row.dataset.qrzCallsign = normalized; row.dataset.lookupState = "complete";
            } catch (error) {
                if (row.dataset.lookupToken !== token || callsign.value.trim().toUpperCase() !== normalized) return;
                clearQrzGeography(); row.dataset.lookupState = "failed";
            }
        }
        callsign.addEventListener("change", lookup); callsign.addEventListener("blur", lookup);
    }
    function makeUnsavedRow(values) {
        const row = document.createElement("tr"); row.dataset.unsavedRow = "true";
        row.dataset.gridSquare = values.grid_square || ""; row.dataset.latitude = values.latitude || "";
        row.dataset.longitude = values.longitude || ""; row.dataset.geographyToken = values.geography_token || "";
        if (row.dataset.geographyToken) row.dataset.qrzCallsign = (values.callsign || "").trim().toUpperCase();
        fieldNames.forEach(name => {
            const cell = document.createElement("td"); const source = activeRow.querySelector(`[data-field="${name}"]`);
            const input = source.tagName === "SELECT" ? source.cloneNode(true) : document.createElement("input");
            if (input.tagName === "INPUT") input.type = name === "qso_date" ? "date" : name === "time_on" ? "time" : "text";
            input.dataset.field = name; input.value = values[name] || "";
            input.setAttribute("aria-label", labels[name]);
            if (["qso_date", "time_on", "callsign", "band", "frequency", "mode"].includes(name)) input.required = true;
            if (name === "callsign") input.maxLength = 32;
            if (name === "frequency") { input.maxLength = 7; input.inputMode = "decimal"; input.pattern = "[0-9]+(?:\\.[0-9]+)?"; }
            if (name === "signal_report") { input.maxLength = 2; input.inputMode = "numeric"; input.pattern = "[0-9]{1,2}"; }
            if (name === "state") input.maxLength = 2; if (name === "country") input.maxLength = 120;
            cell.appendChild(input); row.appendChild(cell);
        });
        row.dataset.duplicateKey = `${values.qso_date}|${values.time_on}|${values.callsign.toUpperCase()}`;
        row.addEventListener("input", () => { const current = rowValues(row); row.dataset.duplicateKey = `${current.qso_date}|${current.time_on}|${current.callsign.toUpperCase()}`; });
        attachLookup(row); return row;
    }
    function clearActiveRow(defaults) {
        fieldNames.forEach(name => { activeRow.querySelector(`[data-field="${name}"]`).value = defaultFieldNames.includes(name) ? (defaults[name] || "") : ""; });
        geographyNames.forEach(name => { delete activeRow.dataset[name.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase())]; });
        ["qrzCallsign", "lookupCallsign", "lookupState", "stateManual", "countryManual", "autoState", "autoCountry"].forEach(name => { delete activeRow.dataset[name]; });
        activeRow.dataset.callsignValue = "";
        activeRow.classList.remove("add-contacts-row-error"); activeRow.dataset.lookupToken = String(++lookupSequence); activeRow.dataset.geographyEdit = "0";
        activeRow.querySelectorAll("[data-field]").forEach(input => { input.classList.remove("add-contacts-field-error"); input.removeAttribute("aria-invalid"); });
        activeRow.querySelector('[data-field="callsign"]').focus();
    }
    function commitActiveRow() {
        if (storedRows().length >= limit) { warning.hidden = false; return false; }
        const values = rowValues(activeRow); const errors = validate(values, activeRow);
        const requiredMissing = ["qso_date", "time_on", "callsign", "band", "frequency", "mode"].some(name => !values[name]);
        showClientErrors(errors.map(message => `New row, ${message}`), requiredMissing); if (errors.length) return false;
        tbody.appendChild(makeUnsavedRow(values)); clearActiveRow(values); showClientErrors([]); updateStatus(); return true;
    }
    activeRow.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); commitActiveRow(); } });
    attachLookup(activeRow);
    shell.querySelectorAll("[data-save-all]").forEach(button => button.addEventListener("click", () => {
        const activeValues = rowValues(activeRow);
        if (activeValues.callsign || activeValues.signal_report || activeValues.state || activeValues.country || activeValues.comment) { if (!commitActiveRow()) return; }
        const rows = storedRows(); if (!rows.length) {
            activeRow.classList.add("add-contacts-row-error");
            showClientErrors(["Add at least one Contact before saving."], true);
            return;
        }
        const values = rows.map(rowValues); const errors = [];
        values.forEach((valuesForRow, index) => validate(valuesForRow, rows[index]).forEach(message => errors.push(`Row ${index + 1}, ${message}`)));
        const requiredMissing = values.some(row => ["qso_date", "time_on", "callsign", "band", "frequency", "mode"].some(name => !row[name]));
        showClientErrors(errors, requiredMissing); if (errors.length) return;
        jsonInput.value = JSON.stringify(values); form.submit();
    }));
    shell.querySelector("[data-discard]").addEventListener("click", () => {
        if (!storedRows().length || window.confirm("Discard all unsaved Contacts? This cannot be undone.")) {
            const defaults = rowValues(activeRow); storedRows().forEach(row => row.remove()); clearActiveRow(defaults); showClientErrors([]); updateStatus();
        }
    });
    try { JSON.parse(document.getElementById("initial-contact-rows").textContent || "[]").slice(0, limit).forEach(values => tbody.appendChild(makeUnsavedRow(values))); } catch (error) { /* Server validation is authoritative. */ }
    updateStatus(); activeRow.querySelector('[data-field="callsign"]').focus();
})();
