"use strict";
htmx.onLoad((target) => {
  function querySelectorAllIncludingTarget(target, selector) {
    const results = Array.from(target.querySelectorAll(selector))
    if (target.matches(selector)) {
      results.push(target)
    }
    return results
  }

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
    $(this).click(function () {
      $(".js-shroud").removeClass("js-shroud")
      $("[data-shroud-input]").prop("disabled", true)
    })
  })

  /**
    * JS to disable/enable targeted field
    **/
  $('input[type="checkbox"][data-disable-target]', target).change(function (e) {
    const target = this.getAttribute("data-disable-target")
    $(target).attr("disabled", this.checked)
  })

  /**
    * JS to disable/enable targeted field depending on radio select choice
    **/
  function toggleDisableOnRadioSelect() {
    const targetId = this.getAttribute("data-disable-target");
    const checkedRadio = this.querySelector("input:checked");
    $(targetId).attr("disabled", checkedRadio.value === "True");
  }
  querySelectorAllIncludingTarget(target, 'div[data-disable-target]').forEach(function (radioWithDisable) {
    toggleDisableOnRadioSelect.call(radioWithDisable);
    $(radioWithDisable).change(toggleDisableOnRadioSelect);
  });

  /**
  * JS to disable/enable and set another select field value.
  **/
  function toggleDisableAndSetValue() {
    if (this.disabled) {
      return;
    }
    const targetId = this.getAttribute("data-disable-target");
    const isSet = $(this).val().length > 0;
    if (isSet) {
      $(targetId).val(this.getAttribute("data-target-value"));
    }
    $(targetId).attr("disabled", isSet);
  }
  querySelectorAllIncludingTarget(target, 'select[data-disable-target]').forEach(function (selectFieldWithDisable) {
    toggleDisableAndSetValue.call(selectFieldWithDisable);
    $(selectFieldWithDisable).change(toggleDisableAndSetValue);
  });

  /**
    * JS to allow to disable buttons (elements with "btn" class)
    * when other elements are present.
    * Typically useful when forms are available and you don't want the user
    * to be confused in which button to use or to forget to validate the editing form.
  **/
  $('[data-disable-btn-if]', target).each(function () {
    const selector = this.getAttribute("data-disable-btn-if")
    $('.btn', this).toggleClass("disabled", $(selector).length !== 0)
    // null value removes the attribute altogether instead of having aria-disabled="false"
    $('a.btn', this).attr("aria-disabled", $(selector).length !== 0 || null)
  })

  document.querySelectorAll("form.submit-on-change").forEach((form) => {
    form.addEventListener("change", form.submit);
  });

  $('form.js-prevent-multiple-submit', target).on('submit', function () {
    // Prevent multiple submit client side.
    // Never trust the client: validation must also happen server side.
    // Opt-in by adding a `js-prevent-multiple-submit` CSS class to a <form>.

    // Pay attention: in multi-step forms, the browser will remember the disabled
    // state of the button when clicking "Previous" in the browser, eventually
    // disabling moving forward afterwards !
    $(':submit', this).on('click', function () {
      return false
    })
  });

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
  querySelectorAllIncludingTarget(target, ".file-dropzone").forEach(initDropZone);

  /**
   * JS to add the birthdate parameter when querying Commune for birthplace
   **/
  $('select[data-select2-link-with-birthdate]', target).each(function () {
    const identifier = this.getAttribute("data-select2-link-with-birthdate")
    const birthdatePicker = document.querySelector('duet-date-picker[identifier="' + identifier + '"]')

    $(this).select2({
      ajax: {
        data: function(params) {
          return {
            term: params.term,
            date: birthdatePicker.getAttribute("value"),
          }
        }
      }
    })
  })

  /**
   * JS to set an input value from a button
   **/
  querySelectorAllIncludingTarget(target, "button[data-emplois-setter-target]").forEach((button) => {
    button.addEventListener("click", function() {
      const inputElement = document.querySelector(this.getAttribute("data-emplois-setter-target"))
      if (this.hasAttribute("data-emplois-setter-value")) {
        inputElement.value = this.getAttribute("data-emplois-setter-value")
      } else if (this.hasAttribute("data-emplois-setter-checked")) {
        inputElement.checked = this.getAttribute("data-emplois-setter-checked") === 'true'
        inputElement.indeterminate = false
      }
      inputElement.dispatchEvent(new Event("change", { bubbles: true }));
    });

  })

  /**
   * JS to check/unckeck all checkbox in one click
   **/
  querySelectorAllIncludingTarget(target, "input[type='checkbox'][data-emplois-select-all-target-input-name]").forEach((selectAllCheckbox) => {
    const targetCheckboxes = Array.from(document.querySelectorAll(`input[name='${selectAllCheckbox.getAttribute("data-emplois-select-all-target-input-name")}']`));

    // Check & uncheck all linked checkboxes when changing the "Select all" checkbox
    selectAllCheckbox.addEventListener("change", function() {
      targetCheckboxes.forEach((checkBox) => {
        checkBox.checked = selectAllCheckbox.checked
      })
    })

    // On each linked checkbox change, adapt "Select all" check status
    targetCheckboxes.forEach((checkBox) => {
      checkBox.addEventListener("change", function() {
        if (targetCheckboxes.every(cb => cb.checked)) {
          selectAllCheckbox.checked = true
          selectAllCheckbox.indeterminate = false
        } else if (targetCheckboxes.every(cb => !cb.checked)) {
          selectAllCheckbox.checked = false
          selectAllCheckbox.indeterminate = false
        } else {
          selectAllCheckbox.indeterminate = true
        }
      })
    });
  })

  /**
   * JS to hide/unhide UI elements
   **/
  querySelectorAllIncludingTarget(target, "form[data-emplois-elements-visibility-on-selection-controller]").forEach((form) => {
    const checkBoxInputName = form.getAttribute("data-emplois-elements-visibility-on-selection-controller")
    form.addEventListener("change", function() {
      const attribute = "data-emplois-elements-visibility-on-selection"
      if (Array.from(form.elements).some((input) => input.name == checkBoxInputName && input.checked)) {
        document.querySelectorAll(`[${attribute}="hidden"]`).forEach((element) => element.classList.add("d-none"))
        document.querySelectorAll(`[${attribute}="shown"]`).forEach((element) => element.classList.remove("d-none"))
        document.querySelectorAll(`[${attribute}="disabled"]`).forEach((element) => { element.disabled = true; })
      } else {
        document.querySelectorAll(`[${attribute}="shown"]`).forEach((element) => element.classList.add("d-none"))
        document.querySelectorAll(`[${attribute}="hidden"]`).forEach((element) => element.classList.remove("d-none"))
        document.querySelectorAll(`[${attribute}="disabled"]`).forEach((element) => { element.disabled = false; })
      }
    })
  })

  function formatNir(nir) {
    if (!nir) {
      return "";
    }
    let elements = nir.replace(/\s+/g, '').split(""); // Delete already existing white spaces.
      let breakpoints = [0, 2, 4, 6, 9, 12]; // White spaces will be inserted after theses indexes + 1.
      let counter = 0; // When a white space is added, the total number of items in list should be increased by 1.
      $.each(elements, function( index, value ) {
        if ($.inArray(index, breakpoints) !== -1) {
          elements.splice(index+1+counter, 0, " "); // Index + 1 to add a white space "in advance".
            counter +=1;
        }
      });
    return elements.join("");
  }

  function initNir() {
    let form = $(".js-format-nir", target);
    let input = form.find("input[name='nir']").first();

    $(input).keyup(function(e) {
      if (e.keyCode == 8) {
        // Ignore backspace key to let users erase content.
          return;
      }
      $(this).val(formatNir($(this).val()));
    });
    // Format the current content of the input
    $(input).val(formatNir($(input).val()));
  }
  initNir();
});
