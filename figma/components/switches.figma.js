// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=4045-15608
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-switch--docs ; les-emplois: itou/templates/companies/includes/buttons/spontaneous_applications_toggle.html
// component=Switches
const figma = require('figma')
const instance = figma.selectedInstance

const showText = instance.getBoolean('Text')
const text = instance.getString('↳ Text')
const checked = instance.getEnum('State', {
  Disabled: '',
  Active: ' checked',
  Inactive: '',
  'Focus Inactive': '',
  'Focus Active': ' checked',
})
const disabled = instance.getEnum('State', {
  Disabled: ' disabled',
  Active: '',
  Inactive: '',
  'Focus Inactive': '',
  'Focus Active': '',
})
const stateLabel = instance.getEnum("Libellé d'état", { On: true, Off: false })

let example
if (stateLabel) {
  // .has-state-label: the theme prints data-it-state-label-on / -off next to the switch.
  example = figma.html`<div class="form-check form-switch has-state-label">
    <input class="form-check-input" type="checkbox" role="switch" name="field" id="id_field"${checked}${disabled}>
    <label class="form-check-label" for="id_field" data-it-state-label-off="Désactivé" data-it-state-label-on="Activé"><span class="visually-hidden">${text}</span></label>
</div>`
} else if (showText) {
  example = figma.html`<div class="form-check form-switch">
    <input class="form-check-input" type="checkbox" role="switch" name="field" id="id_field"${checked}${disabled}>
    <label class="form-check-label" for="id_field">${text}</label>
</div>`
} else {
  example = figma.html`<div class="form-check form-switch">
    <input class="form-check-input" type="checkbox" role="switch" name="field" id="id_field"${checked}${disabled}>
    <label class="form-check-label" for="id_field"><span class="visually-hidden">${text}</span></label>
</div>`
}

export default {
  example,
  id: 'switches',
  metadata: { nestable: true },
}
