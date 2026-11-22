// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=14574-7958
// source=Vertical: les-emplois itou/templates/utils/templatetags/nav.html (side menu entry / collapsible group). Horizontal: les-emplois itou/templates/search/includes/siaes_search_tabs.html (.nav-tabs item); horizontal dropdown: Bootstrap 5 "Navs and tabs › Tabs with dropdowns"
// component=Item de navigation
const figma = require('figma')
const instance = figma.selectedInstance

const label = instance.getString('Label')
const hasIcon = instance.getBoolean('Icon')
const vertical = instance.getEnum('Horizontal / Vertical', { Off: false, On: true })
const dropdown = instance.getEnum('Dropdown', { Off: false, On: true })
const active = instance.getEnum('Current', { Off: '', On: ' active' })
// Hover is a CSS state, no markup change.
instance.getEnum('Hover', { Off: '', On: '' })
const iconLayer = hasIcon ? instance.getInstanceSwap('↳ Icon') : undefined
const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : 'settings-3-line'
// nav.html uses fw-medium in the side menu; tabs use fw-normal me-1.
const icon = hasIcon
  ? vertical
    ? `<i class="ri-${iconName} fw-medium" aria-hidden="true"></i>\n        `
    : `<i class="ri-${iconName} fw-normal me-1" aria-hidden="true"></i>\n        `
  : ''

let example
if (vertical && dropdown) {
  example = figma.html`<li class="nav-item">
    <button class="nav-link has-collapse-caret w-100 text-start${active}"
            type="button"
            data-bs-target="#collapse-nav-SLUG"
            data-bs-toggle="collapse"
            aria-expanded="${active ? 'true' : 'false'}"
            aria-controls="collapse-nav-SLUG">
        ${icon}<span>${label}</span>
    </button>
    <div class="collapse${active ? ' show' : ''}" id="collapse-nav-SLUG">
        <ul>
            <li><a href="…">…</a></li>
        </ul>
    </div>
</li>`
} else if (vertical) {
  example = figma.html`<li class="nav-item">
    <a href="…" class="nav-link${active}">
        ${icon}<span>${label}</span>
    </a>
</li>`
} else if (dropdown) {
  example = figma.html`<li class="nav-item dropdown">
    <a class="nav-link dropdown-toggle${active}" data-bs-toggle="dropdown" href="#" role="button" aria-expanded="false">
        ${icon}<span>${label}</span>
    </a>
    <ul class="dropdown-menu">
        <li><a class="dropdown-item" href="…">…</a></li>
    </ul>
</li>`
} else {
  example = figma.html`<li class="nav-item">
    <a class="nav-link${active}" href="…">
        ${icon}<span>${label}</span>
    </a>
</li>`
}

export default {
  example,
  id: 'nav-item',
  metadata: { nestable: true },
}
