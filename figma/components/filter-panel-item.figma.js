// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=11200-1263
// source=les-emplois itou/templates/includes/field_collapse_checkbox.html (preceded by <hr> in apply/includes/job_applications_filters/departments.html)
// component=Item_Filter_Pannel
const figma = require('figma')
const instance = figma.selectedInstance

const label = instance.getString('Text')
const open = instance.getEnum('Open', { Off: false, On: true })
const hasDescription = instance.getBoolean('Description')
const description = hasDescription ? instance.getString('↳ Description') : ''

export default {
  example: figma.html`<hr>
<fieldset>
    <legend>
        <button class="btn btn-outline-transparent has-collapse-caret${open ? '' : ' collapsed'}" data-bs-toggle="collapse" data-bs-target="#collapse-departments" type="button" aria-expanded="${open ? 'true' : 'false'}" aria-controls="collapse-departments">
            ${label}
        </button>
    </legend>
    <div class="my-3 collapse${open ? ' show' : ''}" id="collapse-departments">
        ${hasDescription ? figma.html`<div class="form-text">${description}</div>` : ''}
        <ul>
            <li>
                <div class="form-check">
                    <input id="id_departments_0" class="form-check-input" name="departments" type="checkbox" value="90" checked>
                    <label for="id_departments_0" class="form-check-label">90 - Territoire de Belfort</label>
                </div>
            </li>
        </ul>
    </div>
</fieldset>`,
  id: 'filter-panel-item',
  metadata: { nestable: true },
}
