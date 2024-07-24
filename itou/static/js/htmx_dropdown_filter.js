"use strict";

(function() {
  const filtersOffcanvas = document.getElementById("offcanvasApplyFilters");
  const filtersContent = document.getElementById("offcanvasApplyFiltersContent");
  const filtersCount = document.getElementById("all-filters-btn");

  function fieldHasValue(container) {
    // selects and select2 do not update the DOM on change, so
    // a query selector cannot be used to know their current value.
    if (container.querySelector(".django-select2")) {
      const selects = container.querySelectorAll(".django-select2");
      for (const select of selects) {
        if (select.value) {
          return true;
        }
      }
    }
    return (
      container.querySelector('input:checked:not([value=""])')
      || container.querySelector('input[value]:not([type=checkbox]):not([type=radio]):not([value=""])')
      || container.querySelector('duet-date-picker[value]:not([value=""])')
    );
  }

  function toggleHasSelectedItem() {
    // Can be called from any element within a dropdown.
    const dropdown = this.closest('.dropdown');
    const btnFilter = dropdown.querySelector(".btn-dropdown-filter");
    btnFilter.classList.toggle('has-selected-item', fieldHasValue(dropdown));
  }

  function updateFiltersCount() {
    if (filtersCount) {
      const activeFiltersCount = Array.from(filtersContent.querySelectorAll(".collapse")).reduce(
        (acc, collapse) => acc + (fieldHasValue(collapse) ? 1 : 0),
        0,
      );
      filtersCount.textContent = activeFiltersCount ? ` (${activeFiltersCount})` : "";
    }
  }

  function toggleActiveFilters() {
    Array.from(filtersContent.querySelectorAll("button[data-bs-toggle]")).forEach((collapse) => {
      const collapseTarget = document.querySelector(collapse.dataset.bsTarget);
      // Avoid transitions as the offcanvas element is shown and associated motion sickness.
      const originalTransitionValue = collapseTarget.style.getPropertyValue("transition");
      collapseTarget.style.setProperty("transition", "none");
      const bsCollapse = bootstrap.Collapse.getOrCreateInstance(collapseTarget, { toggle: false });
      if (fieldHasValue(collapseTarget)) {
        bsCollapse.show();
      } else {
        bsCollapse.hide();
      }
      collapseTarget.style.setProperty("transition", originalTransitionValue);
    });
  }

  function syncInputs(target) {
    target.querySelectorAll("input[data-sync-with]").forEach((syncedInputOrigin) => {
      const syncedInputTarget = document.getElementById(syncedInputOrigin.dataset.syncWith);
      syncedInputOrigin.addEventListener("change", function(event) {
        syncedInputTarget.checked = event.target.checked;
        // Trigger HTMX form submission.
        syncedInputTarget.dispatchEvent(new Event("change", { bubbles: true }));
      });
      syncedInputTarget.addEventListener("change", function(event) {
        syncedInputOrigin.checked = event.target.checked;
        toggleHasSelectedItem.call(syncedInputOrigin);
      });
    })
  }

  function onLoad(target) {
    target.querySelectorAll('.btn-dropdown-filter.dropdown-toggle').forEach((dropdownFilter) => {
      dropdownFilter.addEventListener('hide.bs.dropdown', toggleHasSelectedItem);
      toggleHasSelectedItem.call(dropdownFilter);
    });
    syncInputs(target);
    updateFiltersCount();
  }

  if (filtersOffcanvas) {
    filtersOffcanvas.addEventListener("show.bs.offcanvas", toggleActiveFilters);
  }
  htmx.onLoad(onLoad);
})();
