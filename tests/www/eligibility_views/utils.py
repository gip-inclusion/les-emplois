CERTIFICATION_ERROR_BADGE_HTML = """\
<span class="badge badge-xs rounded-pill bg-danger-lighter text-danger ms-1">
    <i class="ri-error-warning-fill" aria-hidden="true"></i>
    Certification impossible</span>"""
CERTIFIED_BADGE_HTML = """\
<span class="badge badge-xs rounded-pill bg-info-lighter text-info ms-1">
    <i class="ri-verified-badge-fill" aria-hidden="true"></i>
    Certifié</span>"""
IN_PROGRESS_BADGE_HTML = """\
<span class="badge badge-xs rounded-pill bg-warning-lighter text-warning ms-1">
    <i class="ri-loader-4-line" aria-hidden="true"></i>
    En cours de certification</span>"""
NOT_CERTIFIED_BADGE_HTML = """\
<span class="badge badge-xs rounded-pill bg-warning-lighter text-warning ms-1">
    <i class="ri-error-warning-fill" aria-hidden="true"></i>
    Non certifié</span>"""
EXPIRED_CERTIFICATION_HTML = """\
    <span class="badge badge-xs bg-warning-lighter ms-1 rounded-pill text-warning">
        <i aria-hidden="true" class="ri-error-warning-fill"></i>
        Certification expirée</span>"""


def certified_temporarily_html(until_date):
    return f"""\
    <span class="badge badge-xs bg-warning-lighter ms-1 rounded-pill text-warning">
        <i aria-hidden="true" class="ri-timer-line"></i>Certifié jusqu’au {until_date:%d/%m/%Y}
    </span>"""


def certified_in_the_future_html(from_date):
    return f"""\
    <span class="badge badge-xs bg-warning-lighter ms-1 rounded-pill text-warning">
        <i aria-hidden="true" class="ri-timer-line"></i>Certifié à partir du {from_date:%d/%m/%Y}
    </span>"""
