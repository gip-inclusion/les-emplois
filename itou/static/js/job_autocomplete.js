htmx.onLoad((target) => {

  let jobAppellationSearchInput = $('.js-job-autocomplete-input', target)
  let jobAppellationCodeInput = $('.js-job-autocomplete-hidden', target)
  let loading = $('.js-job-autocomplete-loading', target)
  let noLoading = $('.js-job-autocomplete-no-loading', target)
  let autoSubmitOnEnterPressed = jobAppellationSearchInput.data('autosubmit-on-enter-pressed')

  function clearInput() {
    jobAppellationSearchInput.val('')
    jobAppellationCodeInput.val('')
  }

  jobAppellationSearchInput
    // https://api.jqueryui.com/autocomplete/
    .autocomplete({
      delay: 300,
      minLength: 1,
      source: jobAppellationSearchInput.data('autocomplete-source-url'),
      autoFocus: true,
      // Make a selection on focus.
      focus: (event, ui) => {
        jobAppellationCodeInput.val(ui.item.code)  // Store commune code.
        jobAppellationSearchInput.data('title', ui.item.value)  // Store commune name.
      },
      close: (event, ui) => {
        let value = jobAppellationCodeInput.val()
        if (!value) jobAppellationCodeInput.val('')
        // clearInput()
        else jobAppellationSearchInput.blur()
      },
      // Allow to submit the parent form when the enter key is pressed.
      select: (event, ui) => {
        if (event.keyCode === 13) {
          let value = jobAppellationCodeInput.data('title')
          jobAppellationSearchInput.val(value)
          if (autoSubmitOnEnterPressed) {
            jobAppellationSearchInput.parents('form:first').submit()
          }
        }
      },
      search: (event, ui) => {
        loading.addClass('d-block')
        noLoading.addClass('d-none')
        jobAppellationCodeInput.val('')
      },
      response: (event, ui) => {
        loading.removeClass('d-block')
        noLoading.removeClass('d-none')
      }
    })
    .keypress(e => {
      if (e.keyCode === 27) {
        jobAppellationSearchInput.val('')
      }
    })
    .focus(clearInput)

});
