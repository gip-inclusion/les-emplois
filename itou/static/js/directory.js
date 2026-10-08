"use strict";

const subject = document.getElementById("id_subject");
const customSubject = document.getElementById("id_custom_subject");
if (subject && customSubject) {
  const customSubjectContainer = customSubject.closest(".form-group");
  const updateCustomSubject = () => {
    const visible = subject.value === "other";
    customSubjectContainer.classList.toggle("d-none", !visible);
    customSubject.disabled = !visible;
  };
  subject.addEventListener("change", updateCustomSubject);
  updateCustomSubject();
}

htmx.onLoad(() => {
  const searchForm = document.getElementById("people-search-form");
  if (!searchForm || searchForm.clearFiltersInitialized) {
    return;
  }
  // Unlike data attributes, this flag is not copied into HTMX history snapshots.
  searchForm.clearFiltersInitialized = true;
  const clearFilters = document.getElementById("people-clear-filters");
  const updateClearFilters = () => {
    const hasFilters = Boolean(searchForm.querySelector('input[name="q"]').value.trim())
      || Array.from(searchForm.querySelectorAll('input[name="types"]')).some((input) => input.checked);
    clearFilters.classList.toggle("d-none", !hasFilters);
  };
  searchForm.addEventListener("input", updateClearFilters);
  searchForm.addEventListener("change", updateClearFilters);
  updateClearFilters();
});
