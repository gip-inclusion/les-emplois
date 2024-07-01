"use strict";

(function() {
  const filtersContentId = "offcanvasApplyFiltersContent";
  const filtersContent = document.getElementById(filtersContentId);
  const filtersCount = document.getElementById("all-filters-btn");

  function fieldHasValue(container) {
    return (
      container.querySelector('input:checked:not([value=""])')
      || container.querySelector('input[value]:not([type=checkbox]):not([type=radio]):not([value=""])')
      || container.querySelector('duet-date-picker[value]:not([value=""])')
      || container.querySelector("select > option:not([value=''])[selected]")
    );
  }

  function toggleHasSelectedItem() {
    const dropdown = this.closest('.dropdown');
    this.classList.toggle('has-selected-item', fieldHasValue(dropdown));
    this.classList.toggle('font-weight-bold', fieldHasValue(dropdown));
  }

  function initFilters(sidebar) {
    let activeFiltersCount = 0;
    Array.from(sidebar.querySelectorAll(".collapsed")).forEach((collapse) => {
      const collapseTarget = document.querySelector(collapse.dataset.bsTarget);
      if (fieldHasValue(collapseTarget)) {
        activeFiltersCount++;
        bootstrap.Collapse.getOrCreateInstance(collapseTarget, { delay: 0 }).show();
      }
    });
    if (filtersCount) {
      filtersCount.textContent = activeFiltersCount ? ` (${activeFiltersCount})` : "";
    }
  }

  function onLoad(target) {
    target.querySelectorAll('.btn-dropdown-filter.dropdown-toggle').forEach((dropdownFilter) => {
      dropdownFilter.addEventListener('hide.bs.dropdown', toggleHasSelectedItem);
      toggleHasSelectedItem.call(dropdownFilter);
    });
    if (target.id === filtersContentId) {
      initFilters(target);
    }
  }

  if (filtersContent) {
    initFilters(filtersContent);
  }
  htmx.onLoad(onLoad);
})();
