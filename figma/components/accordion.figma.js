// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=12560-188
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-accordion--docs
// component=Accordion
const figma = require('figma')
const instance = figma.selectedInstance

// Item 1 is always shown; Item 2…6 toggle the following ones.
const count = 1 + ['Item 2', 'Item 3', 'Item 4', 'Item 5', 'Item 6'].filter((name) => instance.getBoolean(name)).length
const connected = instance.findConnectedInstances(() => true)
const items = connected.length
  ? connected.slice(0, count).map((item) => item.executeTemplate().example)
  : Array.from({ length: count }, () => figma.html`
    <!-- Accordion item -->`)

export default {
  example: figma.html`<div class="accordion" id="accordion">${items}
</div>`,
  id: 'accordion',
  metadata: { nestable: true },
}
