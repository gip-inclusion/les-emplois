"use strict";

let form = $( ".js-format-nir" );
let input = form.find( "input[name='nir']" ).first();

$(input).keyup(function(e) {
    if (e.keyCode == 8) {
        // Ignore backspace key to let users erase content.
        return;
    }
    let elements = $(this).val().replace(/\s+/g, '').split(""); // Delete already existing white spaces.
    let breakpoints = [0, 2, 4, 6, 9, 12]; // White spaces will be inserted after theses indexes + 1.
    let counter = 0; // When a white space is added, the total number of items in list should be increased by 1.
    $.each(elements, function( index, value ) {
        if ($.inArray(index, breakpoints) != -1) {
            elements.splice(index+1+counter, 0, " "); // Index + 1 to add a white space "in advance".
            counter +=1;
        }
    });
    $(input).val(elements.join(""));
});
