htmx.onLoad((target) => {
    // Verify this override when Select2 is updated.
    // Overriding the noResults text is extraordinarily complicated.
    // https://github.com/select2/select2/issues/3799
    const searchUserInputField = $("#js-search-user-input")
    const amdRequire = jQuery.fn.select2.amd.require;
    const Translation = amdRequire("select2/translation");
    const frTranslations = Translation.loadPath("./i18n/fr");
    searchUserInputField.select2({
        placeholder: 'Jean DUPONT',
        escapeMarkup: function (markup) { return markup; },
        language: {
          ...frTranslations.dict,
          noResults: () => `
              <div class="d-inline-flex w-100 mb-2">
                  <span class="text-muted d-block pe-1">Aucun résultat.</span>
                  <a href="${searchUserInputField.data('noResultsUrl')}" class="link">Enregistrer un nouveau bénéficiaire</a>
              </div>
          `,
        },
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
