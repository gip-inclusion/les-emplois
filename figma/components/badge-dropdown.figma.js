// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=14444-8327
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-badges--docs (WithDropdown story)
// component=Badge dropdown
const figma = require('figma')
const instance = figma.selectedInstance

const open = instance.getEnum('Open', { On: true, Off: false })
const badge = instance.findInstance('Badges')
const text = badge && badge.type === 'INSTANCE' ? badge.getString('Text') : 'Prise de contact'
// Bootstrap toggles .show and aria-expanded at runtime; shown here for the open state.
const show = open ? ' show' : ''

export default {
  example: figma.html`<div class="dropdown">
    <button type="button" class="badge badge-base rounded-pill bg-info dropdown-toggle${show}" id="badge-dropdown-trigger" data-bs-toggle="dropdown" aria-haspopup="true" aria-expanded="${open ? 'true' : 'false'}" aria-controls="badge-dropdown">
        ${text}
    </button>
    <ul class="dropdown-menu${show}" id="badge-dropdown" aria-labelledby="badge-dropdown-trigger">
        <li><button type="button" class="dropdown-item">Action</button></li>
        <li><button type="button" class="dropdown-item">Another action</button></li>
    </ul>
</div>`,
  id: 'badge-dropdown',
  metadata: { nestable: true },
}
