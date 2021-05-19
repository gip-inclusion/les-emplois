
$(document).ready(() => {

  let communeSearchInput = $('.js-commune-autocomplete-input')
  let hiddenCommuneInput = $('.js-commune-autocomplete-hidden')
  let searchButton = $('.js-search-button')
  let loading = $('.js-commune-autocomplete-loading')
  let noLoading = $('.js-commune-autocomplete-no-loading')

  let autoSubmitOnEnterPressed = communeSearchInput.data('autosubmit-on-enter-pressed')

  function clearInput() {
    communeSearchInput.val('')
    hiddenCommuneInput.val('')
    searchButton.prop("disabled", true)
  }

  communeSearchInput
    // https://api.jqueryui.com/autocomplete/
    .autocomplete({
      delay: 150,
      minLength: 1,
      source: communeSearchInput.data('autocomplete-source-url'),
      autoFocus: true,
      // Make a selection on focus.
      focus: (event, ui) => {
        searchButton.prop("disabled", true)
        hiddenCommuneInput.val(ui.item.code)  // Store commune code.
        hiddenCommuneInput.data('title', ui.item.value)  // Store commune name.
      },
      // When the menu is hidden (usually when the form is submitted)
      // populate communeSearchInput with the commune name so that it is part
      // of the querystring.
      close: (event, ui) => {
        let value = hiddenCommuneInput.data('title')
        if (value && communeSearchInput.val()) {
          searchButton.prop("disabled", false)
          communeSearchInput.val(value)
        } else {
          clearInput()
        }
      },
      // Allow to submit the parent form when the enter key is pressed.
      select: (event, ui) => {
        if (event.keyCode === 13) {
          let value = hiddenCommuneInput.data('title')
          communeSearchInput.val(value)
          if (autoSubmitOnEnterPressed) {
            communeSearchInput.parents('form:first').submit()
          }
        }
      },
      search: (event, ui) => {
        loading.addClass('d-block')
        noLoading.addClass('d-none')
      },
      response: (event, ui) => {
        loading.removeClass('d-block')
        noLoading.removeClass('d-none')
      }
    })
    .keypress(e => {
      if (e.keyCode === 27) {
        communeSearchInput.val('')
      }
    })
    .focus(clearInput)

});
