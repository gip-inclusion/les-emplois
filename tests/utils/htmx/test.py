from urllib.parse import urlparse

from tests.utils.test import ItouClient, parse_response_to_soup


class HtmxClient(ItouClient):
    def generic(self, method, path, data="", content_type="application/octet-stream", secure=False, **extra):
        # Add HTMX-specific headers according to your needs.
        # https://htmx.org/reference/#request_headers
        htmx_headers = {
            "HTTP_HX_REQUEST": "true",
        }
        extra = htmx_headers | extra
        return super().generic(method=method, path=path, data=data, content_type=content_type, secure=secure, **extra)


def _handle_swap(page, *, target, new_elements, mode):
    if mode == "none":
        # Easy one!
        return
    if mode == "outerHTML":
        target_element = page.select_one(target) if isinstance(target, str) else target
        if not new_elements:
            # Empty response: remove the target completely
            target_element.decompose()
            return
        [first_element, *rest] = new_elements
        for rest_elt in reversed(rest):
            target_element.insert_after(rest_elt)
        target_element.replace_with(first_element)
        return
    raise NotImplementedError("Other kinds of swap not implemented, please do")


def _get_hx_attribute(element, attribute, default=None):
    while (value := element.attrs.get(attribute)) is None:
        element = element.parent
        if element is None:
            if default is not None:
                return default
            raise ValueError(f"Attribute {attribute} not found on element or its parents")
    if attribute == "hx-target" and value == "this":
        return element
    return value


def update_page_with_htmx(page, select_htmx_element, htmx_response):
    [htmx_element] = page.select(select_htmx_element)
    request_method = htmx_response.request["REQUEST_METHOD"]
    if request_method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        raise ValueError(f"Unsupported method {request_method}")
    attribute = f"hx-{htmx_response.request['REQUEST_METHOD'].lower()}"
    if attribute not in htmx_element.attrs:
        raise ValueError(f"No {attribute} attribute on provided HTMX element")
    url = htmx_element[attribute]
    if url:
        # If url is "", it means that HTMX will have targeted the current URL
        # https://github.com/bigskysoftware/htmx/blob/v1.8.6/src/htmx.js#L2799-L2802
        # Let's not assert anything in that case, since we currently don't have that info in our test
        parsed_url = urlparse(url)
        assert htmx_response.request["PATH_INFO"] == parsed_url.path
    # We only support HTMX responses that do not try to swap the whole HTML body
    parsed_response = parse_response_to_soup(htmx_response, no_html_body=True)
    out_of_band_swaps = [element.extract() for element in parsed_response.select("[hx-swap-oob]")]
    for out_of_band_swap in out_of_band_swaps:
        oob_swap = out_of_band_swap["hx-swap-oob"]
        target_selector = None
        if oob_swap == "true":
            mode = "outerHTML"
        elif "," in oob_swap:
            mode, target_selector = oob_swap.split(",", maxsplit=1)
        else:
            mode = oob_swap
        del out_of_band_swap["hx-swap-oob"]
        if not target_selector:
            assert out_of_band_swap["id"], out_of_band_swap
            target_selector = f"#{out_of_band_swap['id']}"
        targets = page.select(target_selector)
        for target in targets:
            _handle_swap(page, target=target, new_elements=[out_of_band_swap], mode=mode)
    _handle_swap(
        page,
        target=_get_hx_attribute(htmx_element, "hx-target", default=htmx_element),
        new_elements=parsed_response.contents,
        mode=_get_hx_attribute(htmx_element, "hx-swap", default="innerHTML"),
    )


def assertSoupEqual(soup1, soup2):
    assert soup1.prettify() == soup2.prettify()
