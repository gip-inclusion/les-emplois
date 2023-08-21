htmx.onLoad((target) => {
    let addressSearchInput = $('.js-address-autocomplete-input', target);
    let addressLine1Input = $('.js-address-line-1', target);
    let addressLine2Input = $('.js-address-line-2', target);
    let postCodeInput = $('.js-post-code', target);
    let inseeCodeHiddenInput = $('.js-insee-code', target);
    let longitudeHiddenInput = $('.js-longitude', target);
    let latitudeHiddenInput = $('.js-latitude', target);
    let geocodingScoreHiddenInput = $(".js-geocoding-score", target);

    // Hide fallback fields.
    let fallbackFields = [addressLine1Input, postCodeInput]
    fallbackFields.forEach(element => {
        $(element).parent(".form-group").addClass("d-none");
    });

    addressSearchInput
        .autocomplete({
            delay: 300,
            minLength: 3,
            source: (request, response) => {
                $.ajax({
                    url: addressSearchInput.data('autocomplete-source-url'),
                    type: 'get',
                    dataType: "json",
                    data: {
                        q: request.term
                    },
                    success: (data) => {
                        response($.map(data.features, function (item) {
                            let item_values = item.properties;
                            item_values["longitude"] = item.geometry.coordinates[0];
                            item_values["latitude"] = item.geometry.coordinates[1];
                            return {
                                label: item.properties.label,
                                value: item.properties.label,
                                extra_values: item_values,
                            }
                        }));
                    },
                    error: (jqXHR, textStatus, errorThrown) => {
                        // Delete any initial data that may be present if the job seeker already had an address.
                        let fieldstoBeCleaned = [addressLine1Input, addressLine2Input, postCodeInput, inseeCodeHiddenInput, longitudeHiddenInput, latitudeHiddenInput]
                        fieldstoBeCleaned.forEach(element => {
                            $(element).val("");
                        });
                        let error_message = "L'adresse entrée n'a pas été trouvée. Merci de la renseigner dans les champs ci-dessous.";
                        let html = `<div class='mt-4 alert alert-primary' role='alert'>${error_message}</div>`;
                        $(addressSearchInput).prop("disabled", true);
                        $(addressSearchInput).after(html);
                        fallbackFields.forEach(element => {
                            $(element).parent(".form-group").removeClass("d-none");
                            $(element).parent(".form-group").addClass("form-group-required");
                            $(element).prop("required", true);
                        });
                        //
                    }
                })
            },
            select: (event, ui) => {
                addressLine1Input.val(ui.item.extra_values.name);
                postCodeInput.val(ui.item.extra_values.postcode);
                inseeCodeHiddenInput.val(ui.item.extra_values.citycode);
                longitudeHiddenInput.val(ui.item.extra_values.longitude);
                latitudeHiddenInput.val(ui.item.extra_values.latitude);
                geocodingScoreHiddenInput.val(ui.item.extra_values.score);
            },
        })
});

