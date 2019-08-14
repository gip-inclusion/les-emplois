$(document).ready(function () {

  let citySearchInput = $('.js-city-autocomplete-input')
  let hiddenCityInput = $('.js-city-autocomplete-hidden')

  citySearchInput
    // https://api.jqueryui.com/autocomplete/
    .autocomplete({
      delay: 100,
      minLength: 1,
      source: citySearchInput.data('autocomplete-source-url'),
      autoFocus: true,
      select: function (event, ui) {
        hiddenCityInput.val(ui.item.slug)
        if (event.keyCode === 13) {
          citySearchInput.val(ui.item.value)
          citySearchInput.parents('form:first').submit()
        }
      },
    })
    .focus(function() {
      citySearchInput.val('')
      hiddenCityInput.val('')
    })

})
