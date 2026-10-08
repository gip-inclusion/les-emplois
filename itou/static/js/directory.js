"use strict";

htmx.onLoad((target) => {
  const subject = target.querySelector("#id_subject");
  const customSubject = target.querySelector("#id_custom_subject");
  // Form is not displayed when user is rate-limited, not all HTMX fragment contain the form.
  if (subject && customSubject) {
    const customSubjectContainer = customSubject.closest(".form-group");
    function updateCustomSubject() {
      const visible = subject.value === "other";
      customSubjectContainer.classList.toggle("d-none", !visible);
      customSubject.disabled = !visible;
      subject.addEventListener("change", updateCustomSubject);
    }
    updateCustomSubject();
  }

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
