// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5520-36938
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-dropdown--docs (Basic) ; les-emplois itou/templates/employee_record/includes/list_order.html
// component=Dropdowns
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
const variant = instance.getEnum('Type', { Primary: 'btn-primary', 'Primary-outline': 'btn-outline-primary', Link: 'btn-link' })
const size = instance.getEnum('Size', { sm: ' btn-sm', base: '', lg: ' btn-lg' })
// Active = menu open: Bootstrap toggles .show and aria-expanded itself.
const disabled = instance.getEnum('State', { Default: '', Hover: '', Focus: '', Active: '', Disabled: ' disabled' })

export default {
  example: figma.html`<div class="dropdown">
    <button type="button" class="btn${size} ${variant} dropdown-toggle" data-bs-toggle="dropdown" aria-haspopup="true" aria-expanded="false"${disabled}>${text}</button>
    <div class="dropdown-menu">
        <a class="dropdown-item" href="#">Action</a>
    </div>
</div>`,
  id: 'dropdowns',
  metadata: { nestable: true },
}
