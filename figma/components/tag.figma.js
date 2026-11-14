// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=6976-35445
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-tags--docs
// component=Tag
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
const type = instance.getEnum('Type', { Default: 'nuance-09', Info: 'info', Accent: 'accent-01', Important: 'important' })
// Hover is a CSS state. "Active" (solid fill) has no story: it uses the solid theme colours.
const active = instance.getEnum('State', { Inactive: false, Hover: false, Active: true })
const colors = {
  'nuance-09': active ? 'bg-primary text-white' : 'bg-nuance-09 text-primary',
  info: active ? 'bg-info text-white' : 'bg-info-lighter text-info',
  'accent-01': active ? 'bg-accent-01 text-white' : 'bg-accent-01-lighter text-accent-01',
  important: active ? 'bg-important text-white' : 'bg-important-lighter text-important',
}[type]
const icon = (enabled, swapProp, fallback) => {
  if (!enabled) return ''
  const layer = instance.getInstanceSwap(swapProp)
  const name = layer && layer.type === 'INSTANCE' ? layer.name : fallback
  return `<i class="ri-${name} ri-xs" aria-hidden="true"></i>`
}
const left = icon(instance.getBoolean('Icon left'), '↳ Icon left', 'check-line')
const right = icon(instance.getBoolean('Icon right'), '↳ Icon right', 'close-line')

// Clickable variant (<a>) of the story, since the Figma tag has hover/active states.
export default {
  example: figma.html`<a href="#" class="tag ${colors}">${left}${text}${right}</a>`,
  id: 'tag',
  metadata: { nestable: true },
}
