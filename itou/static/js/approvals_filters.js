function submitFiltersForm() {
  $("#js-job-applications-filters-form").submit();
}
$("#js-job-applications-filters-form :input").change(submitFiltersForm);
