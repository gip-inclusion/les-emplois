// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=14590-886
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-input-select-textarea--docs ; markup as rendered by {% bootstrap_field %} (django-bootstrap5) in les-emplois
// component=Select
const figma = require('figma')
const instance = figma.selectedInstance

const label = instance.getString('Label')
const value = instance.getString('Valeur')
const hasHelp = instance.getBoolean('Help text')
const state = instance.getEnum('State', {
  '01. Default': 'default',
  '02. Focus': 'default',
  '04. Valid': 'valid',
  '05. Error': 'error',
  '06. Disabled': 'disabled',
})
const size = instance.getEnum('Size', { sm: ' form-select-sm', default: '', lg: ' form-select-lg', xl: ' form-select-xl' })
// itou-theme only generates breakpoint-scoped width classes (.form-group-input-w-{bp}-{width}).
// lg is the breakpoint les-emplois uses for these widths (form-group-input-w-lg-66 / -lg-33).
const width = instance.getEnum('Largeur', {
  '100%': '',
  '66%': ' form-group-input-w-lg-66',
  '33%': ' form-group-input-w-lg-33',
})

// The help / feedback text is not a component property: read it from the "Message" layer.
const messageLayer = hasHelp ? instance.findText('Message') : undefined
const message = messageLayer && messageLayer.type === 'TEXT' ? messageLayer.textContent : "Texte d'aide"

const validation = state === 'valid' ? ' is-valid' : state === 'error' ? ' is-invalid' : ''
const disabled = state === 'disabled' ? ' disabled' : ''
const ariaInvalid = state === 'error' ? ' aria-invalid="true"' : ''
const describedBy = hasHelp ? ' aria-describedby="id_field_helptext"' : ''

let feedback = ''
if (hasHelp && state === 'valid') {
  feedback = `\n    <div class="valid-feedback" id="id_field_helptext">${message}</div>`
} else if (hasHelp && state === 'error') {
  feedback = `\n    <div class="invalid-feedback" id="id_field_helptext">${message}</div>`
} else if (hasHelp) {
  feedback = `\n    <div class="form-text" id="id_field_helptext">${message}</div>`
}

export default {
  example: figma.html`<div class="form-group${width}">
    <label class="form-label" for="id_field">${label}</label>
    <select name="field" class="form-select${size}${validation}" id="id_field"${describedBy}${ariaInvalid}${disabled}>
        <option value="1" selected>${value}</option>
    </select>${feedback}
</div>`,
  id: 'select',
  metadata: { nestable: true },
}
