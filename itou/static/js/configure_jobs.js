const trashIcon = `
  <svg class="icon" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align: text-top;">
    <use xlink:href="/static/icons/feather-sprite.svg#trash-2"></use>
  </svg>
`;

$(document).ready(() => {

  let jobsTableSelector = '.js-jobs-table'
  let jobsTable = $(jobsTableSelector)

  // Delete.

  $(jobsTableSelector).on('click', 'a.js-job-delete', e => {
    e.preventDefault()
    const link = $(e.currentTarget)
    const tr = link.parents('tr').first()
    // usefull elements of 'tr' for the click
    const appellationRome = tr.find('.job-appellation-name');
    const inputs = tr.find(':input');
    const inputToDelete = tr.find('input[name="code-delete"]');
    const actionLink = tr.find('a');

    if (!inputToDelete.prop('disabled')) { // click to not delete
      appellationRome.removeClass('text-danger').css({'text-decoration': 'none'})
      inputs.prop('disabled', false)
      inputToDelete.prop('disabled', true);
      actionLink.html(trashIcon)
    } else { // click to delete
      appellationRome.addClass('text-danger').css({'text-decoration': 'line-through'})
      inputs.prop('disabled', true)
      inputToDelete.prop('disabled', false);
      actionLink.text("Rétablir")
    }
  })


  // Autocomplete.

  let codesSelector = '[name="code"]'
  let codesToExclude = $(codesSelector).serialize()

  let jobSearchInput = $('.js-job-autocomplete-input')

  let loading = $('.js-job-autocomplete-loading')
  let noLoading = $('.js-job-autocomplete-no-loading')

  let addJob = appellation => {
    // TODO: get one html in configure_jobs and here, to avoid errors when code is updated
    $('.js-jobs-tbody').prepend(`<tr>
        <td>${appellation.rome}</td>
        <td class="text-left">
            <p class="job-appellation-name text-success">
              <i>${appellation.name}</i>
            </p>
            <input type="hidden" name="code-create" value="${appellation.code}">
            <div class="form-group">
                <label for="custom-name-${appellation.code}">
                    <small>Nom personnalisé</small>
                </label>
                <input
                    type="text"
                    class="form-control form-control-sm"
                    id="custom-name-${appellation.code}"
                    name="custom-name-${appellation.code}">
                <small class="form-text text-muted">
                    Si ce champ est renseigné, il sera utilisé à la place du nom ci-dessus.
                </small>
            </div>
            <div class="form-group">
                <label for="description-${appellation.code}">
                    <small>Description</small>
                </label>
                <textarea
                    class="form-control form-control-sm"
                    id="description-${appellation.code}"
                    name="description-${appellation.code}"
                    rows="3"></textarea>
                <small class="form-text text-muted">
                    Renseignez ici le détail des missions, les compétences/habilitations nécessaires, les conditions de travail, les éventuelles adaptations ou restrictions du poste.
                </small>
            </div>
        </td>
        <td class="text-left align-middle" scope="row">
          <div class="custom-control custom-switch">
              <input name="is_active-${appellation.code}"
                  id="is_active-${appellation.code}" type="checkbox"
                  class="custom-control-input"
                  checked>
              <label class="custom-control-label font-weight-bold"
                  for="is_active-${appellation.code}">Ouvrir au recrutement</label>
          </div>
        </td>
        <td class="align-middle">
          <a href="#" role="button" class="js-job-delete">
            ${trashIcon}
          </a>
          <input type="hidden" name="code-delete" value="${appellation.code}" disabled>
        </td>
    </tr>`)
  }

  jobSearchInput
    // https://api.jqueryui.com/autocomplete/
    .autocomplete({
      delay: 300,
      minLength: 1,
      source: (request, response) => {
        let term = encodeURIComponent(request.term)
        $.getJSON(
          jobSearchInput.data('autocomplete-source-url'),
          `term=${term}&${codesToExclude}`,
          response
        )
      },
      autoFocus: true,
      select: (event, ui) => {
        event.preventDefault()
        jobsTable.removeClass('d-none')
        addJob(ui.item)
        codesToExclude = $(codesSelector).serialize()
        jobSearchInput.val('')
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
    .keypress(e => {
      if (e.keyCode === 27) {
        jobSearchInput.val('')
      }
      // Don't submit the form when the focus is on the autocomplete field and enter is pressed.
      if (e.keyCode === 13) {
        e.preventDefault()
      }
    })

  $(document).on("click", "#js-preview-card", function(){
    const urlPreview = $(this).data("urlPreview");
    const FormDataJobs = $('form.js-prevent-multiple-submit').serializeArray();
    const selectorContentModal = "#js-modal-preview-body";
    $.ajax({
        url: urlPreview,
        type: 'post',
        data: FormDataJobs,
        beforeSend: function() {
          $(selectorContentModal).html(`
            <div class="d-flex justify-content-center">
              <div class="spinner-border" style="width: 5rem; height: 5rem;" role="status">
                <span class="sr-only">Loading...</span>
              </div>
            </div>
          `);
          $('#js-modal-preview').modal('show');
        },
        success: function(data) {
            $(selectorContentModal).html(data)
        },
        failure: function(data) {
            console.error(data);
        }
    });
  })
})
