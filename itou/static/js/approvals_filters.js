(function() {
  const filtersToggleBtn = document.getElementById("js-approvals-filters-button");
  const filtersForm = document.getElementById("js-approvals-filters-form");

  function submitFiltersForm() {
    filtersForm.submit();
  }
  $("#js-approvals-filters-form :input").change(submitFiltersForm);

  function showFilters() {
    // The filters toggle button is only displayed on small viewports.
    return window.getComputedStyle(filtersToggleBtn).getPropertyValue("display") === "none";
  }

  function autoCollapseForm() {
    filtersForm.classList.toggle("show", showFilters());
  }

  $(document).ready(function () {
    autoCollapseForm()
    window.addEventListener("resize", autoCollapseForm);
  });
})();
