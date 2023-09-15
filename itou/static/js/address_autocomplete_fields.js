htmx.onLoad(function () {
  let autocompleteNbErrors = 0;
  let addressSearchInput = $("#id_address_for_autocomplete");
  let addressLine1Input = $("#id_address_line_1");
  let addressLine2Input = $("#id_address_line_2");
  let postCodeInput = $("#id_post_code");
  let cityInput = $("#id_city");
  let inseeCodeHiddenInput = $("#id_insee_code");
  let geocodingScoreHiddenInput = $("#id_geocoding_score");
  let banApiResolvedAddressInput = $("#id_ban_api_resolved_address");
  let fillMode = $("#id_fill_mode");

  // Hide fallback fields.
  let fallbackFields = [addressLine1Input, postCodeInput, cityInput];
  fallbackFields.forEach((element) => {
    $(element).parent(".form-group").addClass("d-none");
  });

  addressSearchInput.on("select2:select", function (e) {
    addressLine1Input.val(e.params.data.name);
    postCodeInput.val(e.params.data.postcode);
    cityInput.val(e.params.data.city);
    inseeCodeHiddenInput.val(e.params.data.citycode);
    geocodingScoreHiddenInput.val(e.params.data.score);
    banApiResolvedAddressInput.val(e.params.data.label);
    fillMode.val("ban_api");
  });
  addressSearchInput.select2({
    ajax: {
      processResults: function (data) {
        // Reset debounce counter
        autocompleteNbErrors = 0;
        var results = data.features.map(function (item, index) {
          let prop = item.properties;

          // Without context it's impossible to know what city it is when you
          // only search for a city. Try with Cernay for example
          let text =
            prop.type == "municipality"
              ? prop.label + " (" + prop.context + ")"
              : prop.label;

          return {
            id: prop.id,
            text: text,
            city: prop.city,
            name: prop.name,
            postcode: prop.postcode,
            citycode: prop.citycode,
            street: prop.street,
            score: prop.score,
            label: prop.label,
          };
        });
        return {
          results,
        };
      },
      error: (jqXHR, textStatus, errorThrown) => {
        autocompleteNbErrors++;

        // Debounce errors. Display the error fallback only when we detect 4 errors in a row
        // For some reasons, the BAN API can return temporary errors
        if (autocompleteNbErrors < 7) {
          return;
        }

        // Delete any initial data that may be present if the job seeker already had an address.
        let fieldstoBeCleaned = [
          addressLine1Input,
          addressLine2Input,
          postCodeInput,
          cityInput,
          inseeCodeHiddenInput,
          geocodingScoreHiddenInput,
          banApiResolvedAddressInput,
        ];
        fieldstoBeCleaned.forEach((element) => {
          element.val("");
        });

        let error_message =
          "Une erreur s'est produite lors de la recherche automatique de l'adresse. Merci de renseigner votre adresse dans les champs ci-dessous.";
        let html = `<div class='alert alert-warning' role='alert'>${error_message}</div>`;
        $(addressSearchInput).prop("disabled", true);
        $(addressSearchInput).after(html);

        fillMode.val("fallback");
        fallbackFields.forEach((element) => {
          $(element).parent(".form-group").removeClass("d-none");
          $(element).parent(".form-group").addClass("form-group-required");
          $(element).prop("required", true);
        });
      },
    },
  });
});
