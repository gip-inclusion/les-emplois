$(document).ready(function () {

  /**
   * JS that can be used in combination with HX-Trigger to show/hide modals
   * via an HTMX response:
   * "HX-Trigger": {"modalControl": {"id": "delete_prior_action_modal", "action": "hide"}}
   **/

  document.body.addEventListener("modalControl", function (evt) {
    if (!evt.detail.id) {
      console.error("Received modalControl event without id");
      return;
    }
    if (!evt.detail.action) {
      console.error("Received modalControl event without action");
      return;
    }
    if (!["show", "hide"].includes(evt.detail.action)) {
      console.error(
        "Received modalControl event with invalid action:",
        evt.detail.action
      );
      return;
    }

    const htmxModalControl = new bootstrap.Modal(`#${evt.detail.id}`);

    if (evt.detail.action === "show") {
      htmxModalControl.show();
    } else {
      htmxModalControl.hide();
    }
  });
});
