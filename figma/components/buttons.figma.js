// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5360-32681
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-buttons--docs
// component=Buttons
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
const theme = instance.getEnum('Theme', { Light: 'light', Dark: 'dark' })
const variant = instance.getEnum('Type', {
  '1. Primary': theme === 'dark' ? 'btn-white' : 'btn-primary',
  '2. Primary outline': theme === 'dark' ? 'btn-outline-white' : 'btn-outline-primary',
  '3. Secondary': 'btn-secondary',
  '4. Link': theme === 'dark' ? 'btn-link-white' : 'btn-link',
  '5. Danger': 'btn-danger',
})
const size = instance.getEnum('Size', { sm: ' btn-sm', base: '', lg: ' btn-lg' })
const iconPosition = instance.getEnum('Icon', { Off: 'off', Left: 'left', Right: 'right', Only: 'only' })
const disabled = instance.getEnum('State', { Default: '', Focus: '', Hover: '', Disabled: ' disabled' })
const iconLayer = iconPosition === 'off' ? undefined : instance.getInstanceSwap('↳ Icon')
const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : 'arrow-right-line'
const icon = `<i class="ri-${iconName}" aria-hidden="true"></i>`

let example
if (iconPosition === 'only') {
  example = figma.html`<button type="button" class="btn${size} btn-ico-only ${variant}" aria-label="${text}"${disabled}>
    ${icon}
</button>`
} else if (iconPosition === 'left') {
  example = figma.html`<button type="button" class="btn${size} btn-ico ${variant}"${disabled}>
    ${icon}
    <span>${text}</span>
</button>`
} else if (iconPosition === 'right') {
  example = figma.html`<button type="button" class="btn${size} btn-ico ${variant}"${disabled}>
    <span>${text}</span>
    ${icon}
</button>`
} else {
  example = figma.html`<button type="button" class="btn${size} ${variant}"${disabled}>${text}</button>`
}

export default {
  example,
  id: 'buttons',
  metadata: { nestable: true },
}
