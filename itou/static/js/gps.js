htmx.onLoad((target) => {
    const searchUserInputField = $("#js-search-user-input")
    // Based on static/admin/js/vendor/select2/i18n/fr.js
    // Overriding the noResults text is extraordinary complicated.
    // https://github.com/select2/select2/issues/3799
    searchUserInputField.select2({
        placeholder: 'Jean DUPONT',
        escapeMarkup: function (markup) { return markup; },
        language: {
            errorLoading: function () {
                return "Les résultats ne peuvent pas être chargés."
            },
            inputTooLong: function (e) {
                var n = e.input.length - e.maximum;
                return "Supprimez " + n + " caractère" + (n > 1 ? "s" : "")
            },
            inputTooShort: function (e) {
                var n = e.minimum - e.input.length;
                return "Saisissez au moins " + n + " caractère" + (n > 1 ? "s" : "")
            },
            loadingMore: function () {
                return "Chargement de résultats supplémentaires ¦"
            },
            maximumSelected: function (e) {
                return "Vous pouvez seulement sélectionner " + e.maximum + " élément" + (e.maximum > 1 ? "s" : "")
            },
            noResults: function (e) {
                const select2_i18n = JSON.parse(
                    document.getElementById("js-select2-i18n-vars").textContent
                );
                return `
                    <div class="d-inline-flex w-100 mb-2">
                        <span class="text-muted d-block pe-1">Aucun résultat.</span>
                        <a href="${select2_i18n.noResultUrl}" class="link">Enregistrer un nouveau bénéficiaire</a>
                    </div>
                `
            },
            searching: function () {
                return "Recherche en cours"
            },
            removeAllItems: function () {
                return "Supprimer tous les éléments"
            }
        }
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
