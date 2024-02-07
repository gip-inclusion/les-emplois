htmx.onLoad((target) => {
    $(".js-prevent-default", target).on("click", (event) => {
        event.preventDefault();
    });

  /**
   * Force select2 initialization after htmx swaps
   * select2-hidden-accessible detection skips already initialized widgets like in the case of document.ready
   */
  $('.django-select2:not(.select2-hidden-accessible)', target).djangoSelect2()

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
  $('[data-disable-btn-if]', target).each(function() {
    const selector = this.getAttribute("data-disable-btn-if")
    $('.btn', this).toggleClass("disabled", $(selector).length !== 0)
    // null value removes the attribute altogether instead of having aria-disabled="false"
    $('a.btn', this).attr("aria-disabled", $(selector).length !== 0 || null)
  })

  /*
   * File selector.
   */
  function initDropZone(container) {
    const selector = container.querySelector(".file-dropzone-selector");
    const preview = container.querySelector(".file-dropzone-preview");
    const fileInput = container.querySelector("input[type=file]");
    const fileNameContainer = container.querySelector(".file-dropzone-filename");

    function toggleFileView(container, force) {
      selector.classList.toggle("d-none", force);
      preview.classList.toggle("d-none", !force);
    }

    function handleFileChange() {
      const fileName = fileInput.files[0].name;
      fileNameContainer.textContent = fileName;
      toggleFileView(container, true);
    }

    function handleFileClear() {
      fileInput.value = null;
      toggleFileView(container, false);
    }

    function handleDrag(e) {
      e.preventDefault();
      container.classList.add("highlighted");
    }

    function handleDragLeave(e) {
      e.preventDefault();
      container.classList.remove("highlighted");
    }

    function handleDrop(e) {
      e.preventDefault();
      fileInput.files = e.dataTransfer.files;
      container.classList.remove("highlighted");
      handleFileChange();
    }

    fileInput.addEventListener("change", handleFileChange);
    container.addEventListener("dragenter", handleDrag);
    container.addEventListener("dragover", handleDrag);
    container.addEventListener("dragleave", handleDragLeave);
    container.addEventListener("drop", handleDrop);
    container.querySelector(".file-dropzone-clear").addEventListener("click", handleFileClear);
  }
  target.querySelectorAll(".file-dropzone").forEach(initDropZone);
});
