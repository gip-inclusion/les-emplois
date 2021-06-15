import io
import logging
from dataclasses import dataclass, fields

import httpx
from django.conf import settings


logger = logging.getLogger(__name__)


class HtmlToPdf:
    """
    Convert HTML to PDF documents thanks to
    the PDF Shift API.
    Style your PDF using CSS.

    Usage:
    ```
    with HtmlToPdf(html) as transformer:
        # do something with the PDF file:
        print(transformer.file)
    ```

    --------------------------------------
    WARNING:
    If using it with FileResponse(), you should NOT close it as
    FileResponse does it already.
    See https://code.djangoproject.com/ticket/29278

    Usage with FileResponse:
    ```
    with HtmlToPdf(html, autoclose=False) as transformer:
        return FileResponse(transformer.file, filename=filename)
    ```
    """

    @classmethod
    def html_to_bytes(cls, html):
        kwargs = {
            "auth": ("api", settings.PDFSHIFT_API_KEY),
            "json": {"source": html, "sandbox": settings.PDFSHIFT_SANDBOX_MODE},
        }
        url = f"{settings.PDFSHIFT_API_BASE_URL}/convert/pdf"
        logger.info("POST request to `%s`", url)
        with httpx.stream("POST", url, **kwargs) as response:
            response.raise_for_status()
            result = io.BytesIO()
            for chunk in response.iter_bytes(1024):
                result.write(chunk)

            return result.getvalue()

    def __init__(self, html, autoclose=True):
        self.bytes = self.html_to_bytes(html)
        self.file = io.BytesIO()
        self.autoclose = autoclose

    def __enter__(self):
        self.file.write(self.bytes)
        return self

    def __exit__(self, *exc):
        self.file.seek(0)

        # Don't close the file when using this context manager with
        # FileResponse() as it does it on its own.
        if self.autoclose:
            self.file.close()
        return self


@dataclass
class PDFShiftUsage:
    """
    For internal usage: retrieve PDFShift credits usage.
    A credit is counted per 5Mb chunks.

    Doc:
        https://docs.pdfshift.io/#credits-usage

    Usage:
        from itou.utils.pdf import PDFShiftUsage
        usage = PDFShiftUsage()
        usage.number_of_approval_pdf_delivered
    """

    base: int
    remaining: int
    total: int
    used: int

    def __init__(self):
        data = self.get()
        for field in fields(self):
            setattr(self, field.name, data["credits"][field.name])

    def get(self):
        r = httpx.get(f"{settings.PDFSHIFT_API_BASE_URL}/credits/usage", auth=("api", settings.PDFSHIFT_API_KEY))
        r.raise_for_status()
        return r.json()

    @property
    def number_of_approval_pdf_delivered(self):
        # A credit is counted per 5Mb chunks.
        # 1 PDF == 150K
        return (self.used * 5000) // 150
