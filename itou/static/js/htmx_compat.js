"use strict";

htmx.onLoad(function () {
  function showEvent(e) {
    /**
      * Select2 events are jQuery events [1][2] and not standard JavaScript
      * events [3].
      *
      * Dispatch a JavaScript change event when the select2 selection changes,
      * for hx-trigger="change".
      *
      * [1] https://api.jquery.com/category/events/event-object/
      * [2] https://select2.org/programmatic-control/events#listening-for-events
      * [3] https://developer.mozilla.org/en-US/docs/Web/API/Event/Event
      */
    e.target.dispatchEvent(new Event("change", {bubbles: true}));
  }
  // Selection events from https://select2.org/programmatic-control/events
  $(".django-select2").on("select2:select", showEvent);
  $(".django-select2").on("select2:unselect", showEvent);
  $(".django-select2").on("select2:clear", showEvent);
});
