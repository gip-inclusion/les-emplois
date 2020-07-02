/********************************************
    Add or remove a row in a formset.
    /!\ This works only with inline formsets.

    Usage:
    1- Create a formset. Each field should be in a column with the class "inline-col".
    2- Add a button inside the <form> to add a row. Its class should be `add-form-row`.
    3- Add this snippet to the script block:
    ```
    <script src="{% static "js/formset_add_remove_row.js" %}"></script>
    <script type='text/javascript'>
        $(document).on('click', '.add-form-row', function(e){
            e.preventDefault();
            // First argument is a selector targeting the row to clone..
            // Second argument is the name of your form.
            cloneMore('.inline-form-row:last', 'form');
            return false;
        });
        $(document).on('click', '.remove-form-row', function(e){
            e.preventDefault();
            deleteForm('.inline-form-row', 'form', $(this));
            return false;
        });
    </script>
    ```
    Working example: itou.templates.invitations_views.create.html
*********************************************/
function updateElementIndex(el, prefix, ndx) {
    const id_regex = new RegExp(`(${prefix}-\\d+)`);
    const replacement = `${prefix}-${ndx}`;
    if ($(el).attr("for")) $(el).attr("for", $(el).attr("for").replace(id_regex, replacement));
    if (el.id) el.id = el.id.replace(id_regex, replacement);
    if (el.name) el.name = el.name.replace(id_regex, replacement);
}

function addRemoveButton(selector, col_selector, prefix) {
    let total = $(`#id_${prefix}-TOTAL_FORMS`).val();
    if (total > 1) {
        const deletebutton = `<div class="inline-col col-md-1 remove-form-row">
            <button type="button" class="btn-outline-danger btn mt-2 w-100">X</button>
        </div>`;
        $(selector).find(`${col_selector}:last`).after(deletebutton);
    }
}

function cloneMore(selector, prefix) {
    const newElement = $(selector).clone(true);
    let total = $(`#id_${prefix}-TOTAL_FORMS`).val();
    newElement.removeClass('is-invalid');
    newElement.find(':input:not([type=button]):not([type=submit]):not([type=reset])').each(function() {
        const name = $(this).attr('name').replace(`-${(total-1)}-`, `-${total}-`);
        const id = `id_${name}`;
        $(this).attr({'name': name, 'id': id}).val('').removeAttr('checked');
        $(this).removeClass('is-invalid');
    });
    newElement.find('label').each(function() {
        let forValue = $(this).attr('for');
        if (forValue) {
          forValue = forValue.replace(`-${(total-1)}-`, `-${total}-`);
          $(this).attr({'for': forValue});
        }
    });
    // Add a delete button if it does not exist.
    if (newElement.find('.remove-form-row').length == 0) {
        const deletebutton = `<div class="inline-col col-md-1 remove-form-row">
            <button type="button" class="btn-outline-danger btn mt-2 w-100">X</button>
        </div>`;
        $(selector).find('.inline-col').last().after(deletebutton);
        newElement.find('.inline-col').last().after(deletebutton);
    }
    total++;
    $(`#id_${prefix}-TOTAL_FORMS`).val(total);
    $(selector).after(newElement);
    return false;
}

function deleteForm(selector, prefix, btn) {
    const total = parseInt($(`#id_${prefix}-TOTAL_FORMS`).val());
    if (total > 1){
        btn.closest(selector).remove();
        const forms = $(selector);
        $(`#id_${prefix}-TOTAL_FORMS`).val(forms.length);
        for (let i=0, formCount=forms.length; i<formCount; i++) {
            $(forms.get(i)).find(':input').each(function() {
                updateElementIndex(this, prefix, i);
            });
        }
    }

    // Delete the "Remove" button if there's only one form left.
    if (total == 2 ) {
        $(selector).find('.remove-form-row').remove();
    }
    return false;
}
