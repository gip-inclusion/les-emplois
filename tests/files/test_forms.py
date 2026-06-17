import pytest
from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile

from itou.files.forms import ItouFileInput, ItouMultiFileField, ItouMultiFileInput


ALLOWED_EXTENSIONS = ["pdf", "png"]


def _create_multifile_input(max_upload_size=42):
    return ItouMultiFileField(
        required=False,
        content_type=".pdf,.png",
        max_upload_size=max_upload_size,
        allowed_extensions=ALLOWED_EXTENSIONS,
    )


def test_input_inherits_and_specializes_minimally():
    widget = ItouMultiFileInput(
        content_type="foo/bar",
        max_upload_size_mb=5,
        accepted_formats_label="On prend tout !",
    )
    assert isinstance(widget, ItouFileInput)
    assert widget.allow_multiple_selected is True
    assert widget.template_name == "utils/widgets/multi_file_input.html"
    assert widget.attrs["accept"] == "foo/bar"
    context = widget.get_context("docs", None, {"id": "id_docs"})["widget"]
    assert context["max_upload_size_mb"] == 5
    assert context["accepted_formats_label"] == "On prend tout !"


@pytest.mark.parametrize(
    "data,expected_count",
    [
        (SimpleUploadedFile("a.pdf", b"some_content"), 1),
        (
            [
                SimpleUploadedFile("a.pdf", b"some_content"),
                SimpleUploadedFile("b.png", b"other_content"),
            ],
            2,
        ),
    ],
)
def test_clean_returns_list(data, expected_count):
    assert len(_create_multifile_input().clean(data)) == expected_count


def test_clean_rejects_invalid_extension():
    with pytest.raises(forms.ValidationError):
        _create_multifile_input().clean(
            [
                SimpleUploadedFile("ok.pdf", b"valid"),
                SimpleUploadedFile("left-pad.exe", b"boo"),
            ]
        )


def test_clean_rejects_oversized_file():
    field = _create_multifile_input(max_upload_size=10)
    with pytest.raises(forms.ValidationError):
        field.clean([SimpleUploadedFile("a.pdf", b"x" * 11)])
