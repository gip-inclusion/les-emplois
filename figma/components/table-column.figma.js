// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=8329-31261
// source=les-emplois itou/templates/apply/includes/list_table.html + list_tr.html (a column is one <th> in <thead> and one cell per <tr>)
// component=Column
const figma = require('figma')
const instance = figma.selectedInstance

// Render a nested instance through its own Code Connect template when it has one.
const nested = (layer) => {
  const child = instance.findInstance(layer)
  return child && child.type === 'INSTANCE' && child.hasCodeConnect() ? child.executeTemplate().example : undefined
}

const type = instance.getEnum('Type', {
  Text: 'text',
  'Text Link': 'text-link',
  'Text + Icon': 'text-icon',
  'Text + Badge': 'text-badge',
  Checkbox: 'checkbox',
  'Checkbox selectionné': 'checkbox-checked',
  Button: 'button',
  Badge: 'badge',
  Switch: 'switch',
  Input: 'input',
  'Add column': 'add',
})
const rows = instance.getBoolean('- / + 5 rows') ? 10 : 5

const header = nested('Header') || figma.html`<th scope="col">Header</th>`
let cell
if (type === 'checkbox-checked') {
  cell = figma.html`<th scope="row" class="text-start w-50px">
            <input class="form-check-input" type="checkbox" name="selected-application" value="1" id="select-1" autocomplete="off" checked>
            <label class="visually-hidden" for="select-1">Sélectionner cette candidature</label>
        </th>`
} else if (type === 'add') {
  cell = figma.html`<td></td>`
} else {
  cell = nested('Content') || figma.html`<td><!-- cellule ${type} --></td>`
}

export default {
  example: figma.html`<!-- Colonne : un <th> dans <thead>, puis une cellule par ligne (${rows} lignes dans la maquette) -->
<thead>
    <tr>
        ${header}
    </tr>
</thead>
<tbody>
    <tr>
        ${cell}
    </tr>
</tbody>`,
  id: 'table-column',
  metadata: { nestable: true },
}
