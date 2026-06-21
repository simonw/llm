"""Tests for attachment URL redirect following and Content-Type charset stripping.

Fixes https://github.com/simonw/llm/issues/1046

Two bugs fixed:
1. httpx.head() and httpx.get() in Attachment.resolve_type() and content_bytes()
   did not follow redirects, causing redirected image URLs to fail.
2. Content-Type headers from HTTP responses may include charset params like
   "image/jpeg; charset=utf-8" which wouldn't match attachment_types sets
   like {"image/jpeg", "image/png", ...} used by model plugins.
"""
import pytest

import llm
from llm.cli import resolve_attachment


class TestAttachmentResolveTypeCharsetStripping:
    """Content-Type headers may include charset params like
    'image/jpeg; charset=utf-8'. These should be stripped so that
    the type matches against model.attachment_types sets like
    {'image/jpeg', 'image/png', ...}."""

    def test_resolve_type_strips_charset_from_url_content_type(self, httpx_mock):
        """When a URL returns Content-Type with charset, resolve_type()
        should strip it down to just the MIME type."""
        httpx_mock.add_response(
            url="https://example.com/photo.jpg",
            headers={"content-type": "image/jpeg; charset=utf-8"},
            content=b"\xff\xd8\xff\xe0",
        )
        attachment = llm.Attachment(
            type=None, path=None, url="https://example.com/photo.jpg", content=None
        )
        # Before the fix, this would return "image/jpeg; charset=utf-8"
        # which wouldn't match {"image/jpeg"} in attachment_types
        assert attachment.resolve_type() == "image/jpeg"

    def test_resolve_type_preserves_plain_content_type(self, httpx_mock):
        """When Content-Type has no charset, resolve_type() should return it as-is."""
        httpx_mock.add_response(
            url="https://example.com/photo.png",
            headers={"content-type": "image/png"},
            content=b"\x89PNG\r\n\x1a\n",
        )
        attachment = llm.Attachment(
            type=None, path=None, url="https://example.com/photo.png", content=None
        )
        assert attachment.resolve_type() == "image/png"

    def test_resolve_type_handles_multi_param_content_type(self, httpx_mock):
        """Content-Type may have multiple parameters."""
        httpx_mock.add_response(
            url="https://example.com/image.webp",
            headers={"content-type": "image/webp; charset=binary; boundary=foo"},
            content=b"RIFF",
        )
        attachment = llm.Attachment(
            type=None, path=None, url="https://example.com/image.webp", content=None
        )
        assert attachment.resolve_type() == "image/webp"


class TestAttachmentFollowsRedirects:
    """URL attachments should follow HTTP redirects when resolving
    type and fetching content."""

    def test_resolve_type_follows_redirects(self, httpx_mock):
        """resolve_type() should follow 301/302 redirects."""
        httpx_mock.add_response(
            url="https://example.com/redirect",
            status_code=302,
            headers={"location": "https://cdn.example.com/image.jpg"},
        )
        httpx_mock.add_response(
            url="https://cdn.example.com/image.jpg",
            headers={"content-type": "image/jpeg"},
            content=b"\xff\xd8\xff\xe0",
        )
        attachment = llm.Attachment(
            type=None, path=None, url="https://example.com/redirect", content=None
        )
        assert attachment.resolve_type() == "image/jpeg"

    def test_content_bytes_follows_redirects(self, httpx_mock):
        """content_bytes() should follow 301/302 redirects."""
        image_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        httpx_mock.add_response(
            url="https://example.com/redirect",
            status_code=301,
            headers={"location": "https://cdn.example.com/image.png"},
        )
        httpx_mock.add_response(
            url="https://cdn.example.com/image.png",
            content=image_data,
        )
        attachment = llm.Attachment(
            type="image/png", path=None, url="https://example.com/redirect", content=None
        )
        assert attachment.content_bytes() == image_data


class TestResolveAttachmentCharsetStripping:
    """Test the CLI's resolve_attachment function strips charset params."""

    def test_resolve_attachment_strips_charset(self, httpx_mock):
        """resolve_attachment should strip charset from Content-Type header."""
        httpx_mock.add_response(
            url="https://example.com/photo.jpg",
            headers={"content-type": "image/jpeg; charset=utf-8"},
            content=b"\xff\xd8\xff\xe0",
        )
        attachment = resolve_attachment("https://example.com/photo.jpg")
        assert attachment.type == "image/jpeg"
        assert attachment.url == "https://example.com/photo.jpg"

    def test_resolve_attachment_preserves_plain_type(self, httpx_mock):
        """resolve_attachment should preserve Content-Type without charset."""
        httpx_mock.add_response(
            url="https://example.com/photo.png",
            headers={"content-type": "image/png"},
            content=b"\x89PNG\r\n\x1a\n",
        )
        attachment = resolve_attachment("https://example.com/photo.png")
        assert attachment.type == "image/png"

    def test_resolve_attachment_follows_redirects(self, httpx_mock):
        """resolve_attachment should follow 301/302 redirects when checking URL type."""
        httpx_mock.add_response(
            url="https://short.url/img",
            status_code=301,
            headers={"location": "https://cdn.example.com/image.jpg"},
        )
        httpx_mock.add_response(
            url="https://cdn.example.com/image.jpg",
            headers={"content-type": "image/jpeg"},
            content=b"\xff\xd8\xff\xe0",
        )
        attachment = resolve_attachment("https://short.url/img")
        assert attachment.type == "image/jpeg"
        assert attachment.url == "https://short.url/img"