$("#js-job-applications-filters-apply-button").hide();

// If the Filtres button is present, the associated card should be collapsed on display.
if ($("#js-job-applications-filters-button").is(":visible")) {
    // The button should be always visible now (on windows resize)
    $("#js-job-applications-filters-button").removeClass("d-md-none");
    $('#js-job-applications-filters-form').collapse();
}
