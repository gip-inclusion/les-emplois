import io

import requests
from django.conf import settings


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
        response = requests.post(
            "https://api.pdfshift.io/v3/convert/pdf",
            auth=("api", settings.PDFSHIFT_API_KEY),
            json={"source": html, "sandbox": settings.PDFSHIFT_SANDBOX_MODE},
            stream=True,
            timeout=10,  # in seconds
        )
        response.raise_for_status()

        result = io.BytesIO()
        for chunk in response.iter_content(1024):
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
