// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=4090-15510
// source=les-emplois itou/templates/search/includes/siaes_search_tabs.html (tab with icon + badge), companies/job_description_list.html (.s-tabs-01__nav); vertical: itou-theme stories/ItouTabs.stories.js (Vertical) and utils/templatetags/nav.html (collapsible group); horizontal dropdown: Bootstrap 5 "Navs and tabs › Tabs with dropdowns"
// component=Tabs items
const figma = require('figma')
const instance = figma.selectedInstance

const label = instance.getString('Label')
const hasIcon = instance.getBoolean('Icon')
const hasBadge = instance.getBoolean('Badge')
const vertical = instance.getEnum('Horizontal / Vertical', { Off: false, On: true })
const dropdown = instance.getEnum('Dropdown', { Off: false, On: true })
const active = instance.getEnum('Current', { Off: '', On: ' active' })
// Hover is a CSS state, no markup change.
instance.getEnum('Hover', { Off: '', On: '' })
const iconLayer = hasIcon ? instance.getInstanceSwap('↳ Icon') : undefined
const iconName = iconLayer && iconLayer.type === 'INSTANCE' ? iconLayer.name : 'briefcase-4-line'
const icon = hasIcon ? `<i class="ri-${iconName} fw-normal me-1" aria-hidden="true"></i>\n        ` : ''
// Counter badge, e.g. {{ siaes_count }} in siaes_search_tabs.html.
const badge = hasBadge ? '\n        <span class="badge badge-sm rounded-pill ms-2">12</span>' : ''

let example
if (vertical && dropdown) {
  example = figma.html`<li class="nav-item">
    <button class="nav-link has-collapse-caret w-100 text-start${active}"
            type="button"
            data-bs-target="#collapse-nav-SLUG"
            data-bs-toggle="collapse"
            aria-expanded="${active ? 'true' : 'false'}"
            aria-controls="collapse-nav-SLUG">
        ${icon}<span>${label}</span>${badge}
    </button>
    <div class="collapse${active ? ' show' : ''}" id="collapse-nav-SLUG">
        <ul>
            <li><a href="…">…</a></li>
        </ul>
    </div>
</li>`
} else if (dropdown) {
  example = figma.html`<li class="nav-item dropdown">
    <a class="nav-link dropdown-toggle${active}" data-bs-toggle="dropdown" href="#" role="button" aria-expanded="false">
        ${icon}<span>${label}</span>${badge}
    </a>
    <ul class="dropdown-menu">
        <li><a class="dropdown-item" href="…">…</a></li>
    </ul>
</li>`
} else {
  // Same item markup in a horizontal .nav-tabs and in a vertical .nav-tabs.flex-column.
  example = figma.html`<li class="nav-item">
    <a class="nav-link${active}" href="…">
        ${icon}<span>${label}</span>${badge}
    </a>
</li>`
}

export default {
  example,
  id: 'tab-item',
  metadata: { nestable: true },
}
