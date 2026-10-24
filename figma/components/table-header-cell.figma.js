// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10749-6723
// source=les-emplois itou/templates/apply/includes/list_table.html + itou/templates/common/tables/th_with_sort.html
// component=Header
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
// "Multitaches" (drag handle to reorder columns) and "Add" have no equivalent in les-emplois yet.
const type = instance.getEnum('Type', {
  'Multitaches défaut': 'reorderable',
  'Multitaches hover': 'reorderable',
  'Texte simple': 'text',
  Checkbox: 'checkbox',
  Add: 'add',
})
const sortable = type === 'text' && instance.getBoolean('Filter')

let example
if (sortable) {
  example = figma.html`{% include "common/tables/th_with_sort.html" with order=order ascending_value=order.CREATED_AT_ASC name="${text}" only %}`
} else if (type === 'checkbox') {
  example = figma.html`<th scope="col" class="text-start w-50px">
    <input class="form-check-input" type="checkbox" id="select-all-applications" data-emplois-select-all-target-input-name="selected-application" autocomplete="off">
    <label class="visually-hidden" for="select-all-applications">Sélectionner toutes les candidatures</label>
</th>`
} else if (type === 'add') {
  example = figma.html`<!-- Ajout de colonne : pas encore d'équivalent dans les-emplois -->
<th scope="col" class="text-end w-50px">
    <button type="button" class="btn btn-sm btn-link btn-ico-only" aria-label="Ajouter une colonne">
        <i class="ri-add-line" aria-hidden="true"></i>
    </button>
</th>`
} else if (type === 'reorderable') {
  example = figma.html`<!-- Colonne déplaçable : pas encore d'équivalent dans les-emplois -->
<th scope="col">${text}</th>`
} else {
  example = figma.html`<th scope="col">${text}</th>`
}

export default {
  example,
  id: 'table-header-cell',
  metadata: { nestable: true },
}
