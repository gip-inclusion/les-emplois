htmx.onLoad((target) => {
  let citySearchInput = $('.js-city-autocomplete-input', target)
  let hiddenSlugInput = $('.js-city-autocomplete-hidden', target)
  let searchButton = $('.js-search-button', target)
  let loading = $('.js-city-autocomplete-loading', target)
  let noLoading = $('.js-city-autocomplete-no-loading', target)

  citySearchInput
    .autocomplete({
      delay: 300,
      minLength: 1,
      source: citySearchInput.data('autocomplete-source-url'),
      select: (event, ui) => {
        citySearchInput.val(ui.item.value)
        hiddenSlugInput.val(ui.item.slug)
        searchButton.prop('disabled', false)
        if (event.keyCode === 13) {
          citySearchInput.parents('form:first').submit()
        }
      },
      search: (event, ui) => {
        loading.removeClass('d-none').addClass('d-block')
        noLoading.removeClass('d-block').addClass('d-none')
      },
      response: (event, ui) => {
        loading.removeClass('d-block').addClass('d-none')
        noLoading.removeClass('d-none').addClass('d-block')
      }
    }).keydown(e => {
      searchButton.prop('disabled', true)
    })
});
