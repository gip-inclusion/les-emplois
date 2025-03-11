htmx.onLoad((target) => {
    // Verify this override when Select2 is updated.
    // Overriding the noResults text is extraordinarily complicated.
    // https://github.com/select2/select2/issues/3799
    const searchUserInputField = $("#js-search-user-input")
    const amdRequire = jQuery.fn.select2.amd.require;
    const Translation = amdRequire("select2/translation");
    const frTranslations = Translation.loadPath("./i18n/fr");
    const select2Utils = amdRequire('select2/utils');

    function format_result(data) {
      if (data.name) {
          return $(`
              <div class="row">
                  <div class="col-1 text-disabled">${select2Utils.escapeMarkup(data.title)}</div>
                  <div class="col-9">${select2Utils.escapeMarkup(data.name)}</div>
                  <div class="col-2 text-disabled text-end">${data.birthdate}</div>
              </div>
          `);
      }
      return data.text
    }
    searchUserInputField.select2({
        ajax: {
          delay: 250 // wait 250 milliseconds before triggering the request
        },
        templateResult: format_result,
        templateSelection: format_result,
    });
    searchUserInputField.on("select2:select", function (e) {
        const submit_button = $("#join_group_form .btn-primary.disabled");
        submit_button.attr("disabled", false);
        submit_button.removeClass("disabled");
        submit_button.attr("type", "submit"); // hack because button_forms.html don't allow easily to change it.
    });
    searchUserInputField.on("select2:unselect", function (e) {
        const submit_button = $("#join_group_form .btn-primary");
        submit_button.attr("disabled", true);
        submit_button.addClass("disabled");
    });
});
