"use strict";

htmx.on("htmx:afterSwap", (e) => {
    // Response targeting #dialog => show the modal
    if (e.detail.target.id == "dialog") {
        $('#modal').modal('show');
    }
})

htmx.on("htmx:beforeSwap", (e) => {
    // Empty response targeting #dialog => hide the modal
    if (e.detail.target.id == "dialog" && !e.detail.xhr.response) {
        $('#modal').modal('hide');
        e.detail.shouldSwap = false;
    }
})

// Event fired by Bootstrap when a modal is hidden.
// https://getbootstrap.com/docs/4.6/components/modal/#usage
$(document).on("hidden.bs.modal", () => {
    console.log("Hidden");
    $("#dialog").empty();
})
