htmx.onLoad((target) => {
    $(".js-prevent-default", target).on("click", (event) => {
        event.preventDefault();
    });

    $(".js-display-if-javascript-enabled", target).css("display", "block");

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

  /**
   * JS to copy some text from the DOM into the clipboard.
   */
  $(".js-copy-to-clipboard", target).on("click", function(event) {
    navigator.clipboard.writeText(event.currentTarget.dataset.copyToClipboard)
  })
});
