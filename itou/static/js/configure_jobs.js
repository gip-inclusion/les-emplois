$(document).ready(() => {
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
                <span class="sr-only">Chargement...</span>
              </div>
            </div>
          `);
        },
        success: function(data) {
            $(selectorContentModal).html(data);
            // remove links in preview
            $(`${selectorContentModal} a`).css({"pointer-events":"none"});
        },
        error: function() {
          $(selectorContentModal).html(`
            <p class="alert alert-warning">
              <i>Nous sommes désolés, mais suite à une erreur, la prévisualisation n'est pas disponible.</i>
            </p>
          `);
        },
        complete: function(){
          $('#js-modal-preview').modal('show');
        }
    });
  })
});