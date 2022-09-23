function submitFiltersForm() {
    $("#js-approvals-filters-form").submit();
}
$("#js-approvals-filters-form :input").change(submitFiltersForm);
$("duet-date-picker").on("duetChange", submitFiltersForm);

// If the Filtres button is present, the associated card should be collapsed on display.
if ($("#js-approvals-filters-button").is(":visible")) {
    // The button should be always visible now (on windows resize)
    $("#js-approvals-filters-button").removeClass("d-md-none");
    $('#js-approvals-filters-form').collapse();
}
