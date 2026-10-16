// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=14421-146
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-tags--docs (Default / Large stories)
// component=Tag_v2
const figma = require('figma')
const instance = figma.selectedInstance

const colors = instance.getEnum('Type', {
  Info: 'bg-info-lighter text-info',
  Grey: 'bg-nuance-09 text-primary',
  Accent: 'bg-accent-01-lighter text-accent-01',
})
const size = instance.getEnum('Size', { xs: '', sm: ' tag-lg' })

// The label is not exposed as a text property: read the "Label" text layer directly.
const label = instance.findText('Label')
const text = label && label.type === 'TEXT' ? label.textContent : 'Label'

export default {
  example: figma.html`<span class="tag${size} ${colors}">${text}</span>`,
  id: 'tag-v2',
  metadata: { nestable: true },
}
