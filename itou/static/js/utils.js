htmx.onLoad((target) => {
    $(".js-prevent-default", target).on("click", (event) => {
        event.preventDefault();
    });

    $(".js-display-if-javascript-enabled", target).css("display", "block");

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

    $(".js-enable-submit-when-valid", target).each(function () {
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
    swap_elements.addClass('d-none').removeClass('d-block')
    swap_element_with.addClass('d-block').removeClass('d-none')
  }
  $(".js-swap-elements", target).each(function () {
    $(this).find("[data-swap-element]").each(function () {
      $(this).click(swapElements)
    })
  })

  /**
   * JS to manage shroud
   */
  $("[data-shroud-input]", target).prop("disabled", true)
  $(".js-shroud", target).find("[data-shroud-input]").prop("disabled", false)
  $("[data-shroud-clear]", target).each(function () {
    $(this).click(function() {
      $(".js-shroud").removeClass("js-shroud")
      $("[data-shroud-input]").prop("disabled", true)
    })
  })

  /**
    * JS to disable/enable targeted field
    **/
  $('input[type="checkbox"][data-disable-target]', target).change(function(e) {
    const target = this.getAttribute("data-disable-target")
    $(target).attr("disabled", this.checked)
  })

  /**
    * JS to allow to disable buttons (elements with "btn" class)
    * when other elements are present.
    * Typically useful when forms are available and you don't want the user
    * to be confused in which button to use or to forget to validate the editing form.
  **/
  $('[data-disable-btn-if]').each(function() {
    const selector = this.getAttribute("data-disable-btn-if")
    $('.btn', this).toggleClass("disabled", $(selector).length !== 0)
    // null value removes the attribute altogether instead of having aria-disabled="false"
    $('a.btn', this).attr("aria-disabled", $(selector).length !== 0 || null)
  })
});
