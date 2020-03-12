import io

import pdfshift
from django.conf import settings
from requests import exceptions as requests_exceptions


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
        try:
            pdfshift.api_key = settings.PDFSHIFT_API_KEY
            binary_file = pdfshift.convert(html, sandbox=settings.PDFSHIFT_SANDBOX_MODE)
        except requests_exceptions.ConnectionError as error:
            # With Django 3 we could use RequestAborted here.
            raise ConnectionAbortedError(error)

        return binary_file

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
