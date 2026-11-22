// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=8322-38616
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/utilities-horizontal-rules--docs
// component=hr
// Horizontal=Off is the vertical rule: Bootstrap's .vr helper (styled by $vr-border-width in itou-theme).
const figma = require('figma')
const instance = figma.selectedInstance

const horizontal = instance.getEnum('Horizontal', { On: true, Off: false })

export default {
  example: horizontal ? figma.html`<hr>` : figma.html`<div class="vr"></div>`,
  id: 'horizontal-rule',
  metadata: { nestable: true },
}
