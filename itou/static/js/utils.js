$(document).ready(() => {
    $(".js-prevent-default").on("click", (event) => {
        event.preventDefault();
    });

    $(".js-display-if-javascript-enabled").css("display", "block");

    /**
     * JS to disable the submit button of the form when it's not valid
     **/
    function checkValidity(e) {
        let submit = $(e.currentTarget).find('button[type="submit"]')
        if (e.currentTarget.checkValidity()) {
            submit.removeClass("disabled")
        } else {
            submit.addClass("disabled")
        }
    }

    $(".js-enable-submit-when-valid").each(function () {
        let form = $(this)
        // Check the validity when something (possibly) change in the form.
        form.on("change reset duetChange", (e) => {
          // Use setTimeout() to execute checkValidity() in the next event cycle,
          // when events *should* have done what they need to do.
          window.setTimeout(checkValidity, 0, e)
        })
        // Check immediately
        checkValidity({"currentTarget": this})
    });

  /**
   * JS to swap elements based on CSS selectors
   */
  function swapElements(e) {
    let box = $(e.currentTarget).parents(".js-swap-elements")
    let swap_elements = $(box).find($(e.currentTarget).data("swap-element"))
    let swap_element_with = swap_elements
      .get()  // Convert the jQuery object to an Array
      .flatMap(item => $(box).find($(item).data("swap-element-with")))  // Make a flat list of elements to swap with
      .reduce($.merge)  // Convert the Array to a jQuery object
    swap_elements.hide()
    swap_element_with.show()
  }
  $(".js-swap-elements").each(function () {
    $(this).find("[data-swap-element]").each(function () {
      $(this).click(swapElements)
    })
  })
});
