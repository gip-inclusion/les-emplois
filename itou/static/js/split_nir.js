"use strict";

let $form = $( ".js-format-nir" );
let $input = $form.find( "input[name='nir']" ).first();

$($input).keyup(function(e) {
    if (e.keyCode == 8) {
        // Backspace key
        return;
    }
    let elements = $(this).val().replace(/\s+/g, '').split("");
    let breakpoints = [0, 2, 4, 6, 9, 12];
    let counter = 0;
    $.each(elements, function( index, value ) {
        if ($.inArray(index, breakpoints) != -1) {
            elements.splice(index+1+counter, 0, " ");
            counter +=1;
        }
    });
    $($input).val(elements.join(""));
});