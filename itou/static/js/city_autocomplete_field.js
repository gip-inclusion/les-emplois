$(document).ready(() => {

  let citySearchInput = $('.js-city-autocomplete-input')
  let hiddenCityInput = $('.js-city-autocomplete-hidden')

  let loading = $('.js-city-autocomplete-loading')
  let noLoading = $('.js-city-autocomplete-no-loading')

  citySearchInput
    // https://api.jqueryui.com/autocomplete/
    .autocomplete({
      delay: 300,
      minLength: 1,
      source: citySearchInput.data('autocomplete-source-url'),
      autoFocus: true,
      select: (event, ui) => {
        hiddenCityInput.val(ui.item.slug)
        if (event.keyCode === 13) {
          citySearchInput.val(ui.item.value)
          citySearchInput.parents('form:first').submit()
        }
      },
      search: (event, ui) => {
          loading.addClass('d-block')
          noLoading.addClass('d-none')
      },
      response: (event, ui) => {
          loading.removeClass('d-block')
          noLoading.removeClass('d-none')
      },
    })
    .focus(() => {
      citySearchInput.val('')
      hiddenCityInput.val('')
    })

})
