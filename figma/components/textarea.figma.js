// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=14590-758
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-input-select-textarea--docs ; markup as rendered by {% bootstrap_field %} (django-bootstrap5) in les-emplois
// component=Textarea
const figma = require('figma')
const instance = figma.selectedInstance

const label = instance.getString('Label')
const value = instance.getString('Valeur')
const state = instance.getEnum('State', {
  '01. Default': 'empty',
  '02. Focus': 'empty',
  '04. Filled': 'filled',
  '05. Disabled': 'disabled',
})
// itou-theme only generates breakpoint-scoped width classes (.form-group-input-w-{bp}-{width}).
// lg is the breakpoint les-emplois uses for these widths (form-group-input-w-lg-66 / -lg-33).
const width = instance.getEnum('Largeur', {
  '100%': '',
  '66%': ' form-group-input-w-lg-66',
  '33%': ' form-group-input-w-lg-33',
})

// The help text has no visibility property in Figma: it is always shown, read from the "Message" layer.
const messageLayer = instance.findText('Message')
const message = messageLayer && messageLayer.type === 'TEXT' ? messageLayer.textContent : "Texte d'aide"

// No placeholder, ever: empty states render an empty textarea.
const content = state === 'filled' ? value : ''
const disabled = state === 'disabled' ? ' disabled' : ''

export default {
  example: figma.html`<div class="form-group${width}">
    <label class="form-label" for="id_field">${label}</label>
    <textarea name="field" cols="40" rows="10" class="form-control" id="id_field" aria-describedby="id_field_helptext"${disabled}>${content}</textarea>
    <div class="form-text" id="id_field_helptext">${message}</div>
</div>`,
  id: 'textarea',
  metadata: { nestable: true },
}
