$(document).ready(() => {

  let prescriberOrganizationSearchInput = $('.js-prescriber-organization-autocomplete-input')
  let hiddenPrescriberOrganizationInput = $('.js-prescriber-organization-autocomplete-hidden')
  let loading = $('.js-prescriber-organization-autocomplete-loading')
  let noLoading = $('.js-prescriber-organization-autocomplete-no-loading')

  function clearInput() {
    prescriberOrganizationSearchInput.val('')
    hiddenPrescriberOrganizationInput.val('')
  }

  prescriberOrganizationSearchInput
    // https://api.jqueryui.com/autocomplete/
    .autocomplete({
      delay: 150,
      minLength: 1,
      source: prescriberOrganizationSearchInput.data('autocomplete-source-url'),
      autoFocus: true,
      created: clearInput(),

      focus: (event, ui) => {
        hiddenPrescriberOrganizationInput.data('value', ui.item.id)  // Store org id.
      },

      close: (event, ui) => {
        let value = hiddenPrescriberOrganizationInput.data('value')
        if (value && prescriberOrganizationSearchInput.val()) {
          hiddenPrescriberOrganizationInput.val(value)
        } else {
          clearInput()
        }
      },

      select: (event, ui) => {
        if (event.keyCode === 13) {
          let value = hiddenPrescriberOrganizationInput.data('value')
          hiddenPrescriberOrganizationInput.val(value)
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
        prescriberOrganizationSearchInput.val('')
      }
    })
    .focus(clearInput)

});
