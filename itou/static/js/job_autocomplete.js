$(document).ready(() => {

  let jobAppellationSearchInput = $('.js-job-autocomplete-input')
  let jobApplicationCodeInput = $('.js-job-autocomplete-hidden')
  let loading = $('.js-job-autocomplete-loading')
  let noLoading = $('.js-job-autocomplete-no-loading')
  let autoSubmitOnEnterPressed = jobAppellationSearchInput.data('autosubmit-on-enter-pressed')

  function clearInput() {
    jobAppellationSearchInput.val('')
    jobApplicationCodeInput.val('')
  }

  jobAppellationSearchInput
    // https://api.jqueryui.com/autocomplete/
    .autocomplete({
      delay: 300,
      minLength: 1,
      // Use a callback to add custom parameter 'date':
      source: function(request, response) {
        $.getJSON(jobAppellationSearchInput.data('autocomplete-source-url'), 
          {term: request.term, siae_id: request.siae_id,}, 
          response)
      },
      autoFocus: true,
      // Make a selection on focus.
      focus: (event, ui) => {
        jobApplicationCodeInput.val(ui.item.code)  // Store commune code.
        jobAppellationSearchInput.data('title', ui.item.value)  // Store commune name.
      },
      close: (event, ui) => {
        let value = jobApplicationCodeInput.val()
        if (!value) clearInput()
        else jobAppellationSearchInput.blur()
      },
      // Allow to submit the parent form when the enter key is pressed.
      select: (event, ui) => {
        if (event.keyCode === 13) {
          let value = jobApplicationCodeInput.data('title')
          jobAppellationSearchInput.val(value)
          if (autoSubmitOnEnterPressed) {
            jobAppellationSearchInput.parents('form:first').submit()
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
        jobAppellationSearchInput.val('')
      }
    })
    .focus(clearInput)

});
