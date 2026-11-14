// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=4360-20091
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-badges--docs
// component=Badges
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
const size = instance.getEnum('Size', { sm: 'badge-sm', default: 'badge-base' })
const light = instance.getEnum('Light', { Off: false, On: true })
// [solid classes, light classes], as listed in the "AllVersions" story.
// "Grey" only exists in one tone; the theme has no primary-lighter, so "Générique" light uses bg-light.
const colors = instance.getEnum('Color', {
  Info: ['bg-info text-white', 'bg-info-lighter text-info'],
  Success: ['bg-success text-white', 'bg-success-lighter text-success'],
  Error: ['bg-danger text-white', 'bg-danger-lighter text-danger'],
  Warning: ['bg-warning text-white', 'bg-warning-lighter text-warning'],
  New: ['bg-important text-white', 'bg-important-lighter text-important'],
  'Accent - Blue': ['bg-accent-02 text-primary', 'bg-accent-02-lighter text-primary'],
  'Accent - Yellow': ['bg-accent-03 text-primary', 'bg-accent-03-lighter text-primary'],
  'Accent - Pink': ['bg-accent-01 text-white', 'bg-accent-01-lighter text-accent-01'],
  Générique: ['bg-primary text-white', 'bg-light text-primary'],
  Grey: ['bg-disabled-color-light text-primary', 'bg-disabled-color-light text-primary'],
})
const color = light ? colors[1] : colors[0]
const hasIcon = instance.getBoolean('Icon')
const hasDropdown = instance.getBoolean('Dropdown')
const iconLayer = hasIcon ? instance.getInstanceSwap('↳ Icon') : undefined
const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : 'global-line'
const icon = hasIcon ? `<i class="ri-${iconName}" aria-hidden="true"></i> ` : ''

let example
if (hasDropdown) {
  // "WithDropdown" story: the badge becomes the dropdown trigger (badge-base only).
  example = figma.html`<div class="dropdown">
    <button type="button" class="badge ${size} rounded-pill ${color} dropdown-toggle" id="badge-dropdown-trigger" data-bs-toggle="dropdown" aria-haspopup="true" aria-expanded="false" aria-controls="badge-dropdown">
        ${icon}${text}
    </button>
    <ul class="dropdown-menu" id="badge-dropdown" aria-labelledby="badge-dropdown-trigger">
        <li><button type="button" class="dropdown-item">Action</button></li>
    </ul>
</div>`
} else {
  example = figma.html`<span class="badge ${size} rounded-pill ${color}">${icon}${text}</span>`
}

export default {
  example,
  id: 'badges',
  metadata: { nestable: true },
}
