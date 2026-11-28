"""Tests for the merchant logo tools."""

import json
import struct
import zlib
from unittest.mock import AsyncMock, patch

import pytest

from monarch_mcp_server.tools import merchant_logos as ml
from monarch_mcp_server.tools.merchant_logos import (
    find_merchants_missing_logos,
    icon_candidates,
    set_merchant_logo,
    sniff_image,
)

PNG_64 = (
    b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (256).to_bytes(4, "big")
    + (256).to_bytes(4, "big") + b"\x08\x06\x00\x00\x00" + b"\x00" * 32
)
MERCHANT = {"merchant": {"id": "m1", "name": "Example Store", "logoUrl": None}}


class TestSniff:
    def test_known_formats(self):
        assert sniff_image(PNG_64) == "image/png"
        assert sniff_image(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
        assert sniff_image(b"GIF89a....") == "image/gif"
        assert sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
        assert sniff_image(b"\x00\x00\x01\x00\x01\x00") == "image/x-icon"

    def test_rejects_non_images(self):
        assert sniff_image(b"-----BEGIN OPENSSH PRIVATE KEY-----") is None
        assert sniff_image(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None


class TestIconCandidates:
    def test_apple_touch_icon_ranks_first_then_size(self):
        html = """
        <link rel="icon" href="/favicon-32.png" sizes="32x32">
        <link rel="icon" type="image/svg+xml" href="/icon.svg">
        <link rel='icon' href='/favicon-192.png' sizes='192x192'>
        <link href="/apple-touch-icon.png" rel="apple-touch-icon">
        <link rel="stylesheet" href="/x.css">
        """
        assert icon_candidates(html, "https://www.example.com/home") == [
            "https://www.example.com/apple-touch-icon.png",
            "https://www.example.com/favicon-192.png",
            "https://www.example.com/favicon-32.png",
        ]


class TestSetMerchantLogo:
    async def test_requires_exactly_one_source(self):
        client = AsyncMock()
        client.gql_call.return_value = MERCHANT
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)):
            none = json.loads(await set_merchant_logo(merchant_id="m1"))
            two = json.loads(
                await set_merchant_logo(
                    merchant_id="m1", image_url="https://x/a.png", domain="x.com"
                )
            )
        assert none["error"] and "exactly one" in none["message"]
        assert two["error"] and "exactly one" in two["message"]

    async def test_image_path_refuses_non_image(self, tmp_path):
        secret = tmp_path / "id_rsa"
        secret.write_text("-----BEGIN OPENSSH PRIVATE KEY-----")
        client = AsyncMock()
        client.gql_call.return_value = MERCHANT
        upload = AsyncMock()
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)), \
             patch.object(ml, "upload_to_cloudinary", upload):
            out = json.loads(
                await set_merchant_logo(
                    merchant_id="m1", image_path=str(secret), dry_run=False
                )
            )
        assert out["error"] and "not a PNG" in out["message"]
        upload.assert_not_called()
        assert client.gql_call.await_count == 1  # only the read

    async def test_dry_run_writes_preview_and_never_writes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ml, "PREVIEW_DIR", tmp_path / "previews")
        img = tmp_path / "logo.png"
        img.write_bytes(PNG_64)
        client = AsyncMock()
        client.gql_call.return_value = MERCHANT
        upload = AsyncMock()
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)), \
             patch.object(ml, "upload_to_cloudinary", upload):
            out = json.loads(
                await set_merchant_logo(merchant_id="m1", image_path=str(img))
            )
        assert out["dry_run"] is True
        assert out["merchant_name"] == "Example Store"
        assert out["dimensions"] == "256x256"
        assert (tmp_path / "previews" / "m1.png").read_bytes() == PNG_64
        upload.assert_not_called()
        ops = [c.kwargs["operation"] for c in client.gql_call.await_args_list]
        assert ops == ["Web_GetMerchantDetails"]

    async def test_low_res_warning_uses_source_size_not_padded_size(
        self, tmp_path, monkeypatch
    ):
        # circle_safe upscales to a 512 canvas; a 32px favicon must still warn.
        monkeypatch.setattr(ml, "PREVIEW_DIR", tmp_path / "previews")
        img = tmp_path / "tiny.png"
        img.write_bytes(PNG_64)
        padded = PNG_64[:16] + (512).to_bytes(4, "big") * 2 + PNG_64[24:]
        dims = iter([(32, 32), (512, 512)])
        monkeypatch.setattr(ml, "image_dimensions", lambda data, mime: next(dims))
        monkeypatch.setattr(ml, "pad_for_circle", lambda data, mime, color: padded)
        client = AsyncMock()
        client.gql_call.return_value = MERCHANT
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)):
            out = json.loads(
                await set_merchant_logo(
                    merchant_id="m1", image_path=str(img), circle_safe=True
                )
            )
        assert out["source_dimensions"] == "32x32"
        assert out["dimensions"] == "512x512"
        assert "32x32" in out["warning"]

    async def test_live_run_uploads_then_sets_logo(self, tmp_path):
        img = tmp_path / "logo.png"
        img.write_bytes(PNG_64)
        info = {
            "path": "https://api.cloudinary.com/v1_1/demo/image/upload",
            "requestParams": {"timestamp": 1, "folder": "f", "signature": "s",
                              "api_key": "k", "upload_preset": "p",
                              "__typename": "CloudinaryRequestParams"},
        }
        client = AsyncMock()
        client.gql_call.side_effect = [
            MERCHANT,
            {"getCloudinaryUploadInfo": {"info": info, "errors": None}},
            {"setMerchantLogo": {"merchant": {"id": "m1", "name": "Example Store",
                                              "logoUrl": "https://res/x.png"},
                                 "errors": None}},
        ]
        upload = AsyncMock(return_value="production/merchant_logos/custom/u/abc")
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)), \
             patch.object(ml, "upload_to_cloudinary", upload):
            out = json.loads(
                await set_merchant_logo(
                    merchant_id="m1", image_path=str(img), dry_run=False
                )
            )
        assert out["success"] is True
        assert out["logo_url"] == "https://res/x.png"
        assert upload.await_args.args[0] is info
        final = client.gql_call.await_args_list[-1].kwargs
        assert final["operation"] == "Common_SetMerchantLogo"
        assert final["variables"]["input"] == {
            "merchantId": "m1",
            "cloudinaryPublicId": "production/merchant_logos/custom/u/abc",
        }

    async def test_payload_rejection_is_reported_as_failure(self, tmp_path):
        img = tmp_path / "logo.png"
        img.write_bytes(PNG_64)
        client = AsyncMock()
        client.gql_call.side_effect = [
            MERCHANT,
            {"getCloudinaryUploadInfo": {"info": {"path": "https://u"}, "errors": None}},
            {"setMerchantLogo": {"merchant": None,
                                 "errors": {"message": "bad id", "code": "X"}}},
        ]
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)), \
             patch.object(ml, "upload_to_cloudinary", AsyncMock(return_value="pid")):
            out = json.loads(
                await set_merchant_logo(
                    merchant_id="m1", image_path=str(img), dry_run=False
                )
            )
        assert out["success"] is False
        assert out["errors"]["message"] == "bad id"

    async def test_rejects_plain_http_url(self):
        client = AsyncMock()
        client.gql_call.return_value = MERCHANT
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)):
            out = json.loads(
                await set_merchant_logo(merchant_id="m1", image_url="http://x.com/a.png")
            )
        assert out["error"] and "https" in out["message"]


class TestUploadToCloudinary:
    async def test_strips_typename_and_returns_public_id(self, monkeypatch):
        captured = {}

        class FakeResp:
            status_code = 200
            text = ""

            def json(self):
                return {"public_id": "pid-1"}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, data=None, files=None):
                captured.update(url=url, data=data, files=files)
                return FakeResp()

        monkeypatch.setattr(ml.httpx, "AsyncClient", FakeClient)
        pid = await ml.upload_to_cloudinary(
            {"path": "https://api.cloudinary.com/x/upload",
             "requestParams": {"timestamp": 5, "signature": "s", "__typename": "T"}},
            PNG_64,
            "image/png",
        )
        assert pid == "pid-1"
        assert captured["data"] == {"timestamp": "5", "signature": "s"}
        assert captured["files"]["file"][0] == "logo.png"

    def test_relative_path_resolves_to_cloudinary_api(self):
        # Monarch's live response (2026-11-28) returns a path, not a URL.
        assert (
            ml.cloudinary_upload_url("/v1_1/monarch-money/image/upload/")
            == "https://api.cloudinary.com/v1_1/monarch-money/image/upload/"
        )
        assert (
            ml.cloudinary_upload_url("https://api.cloudinary.com/v1_1/x/image/upload")
            == "https://api.cloudinary.com/v1_1/x/image/upload"
        )

    @pytest.mark.parametrize(
        "path",
        [
            "",
            None,
            "http://api.cloudinary.com/v1_1/x/image/upload",
            "https://evil.example.com/v1_1/x/image/upload",
            "https://api.cloudinary.com.evil.example/v1_1/x",
            "//evil.example.com/upload",
            "v1_1/x/image/upload",
        ],
    )
    def test_refuses_non_cloudinary_targets(self, path):
        with pytest.raises(RuntimeError, match="Unexpected upload path"):
            ml.cloudinary_upload_url(path)


class TestFindMissing:
    async def test_filters_and_ranks(self):
        client = AsyncMock()
        client.gql_call.return_value = {
            "byMerchant": [
                {"groupBy": {"merchant": {"id": "a", "name": "A", "logoUrl": None}},
                 "summary": {"count": 3, "sumExpense": -10, "sumIncome": 0}},
                {"groupBy": {"merchant": {"id": "b", "name": "B", "logoUrl": "https://l"}},
                 "summary": {"count": 9, "sumExpense": -5, "sumIncome": 0}},
                {"groupBy": {"merchant": {"id": "c", "name": "C", "logoUrl": None}},
                 "summary": {"count": 7, "sumExpense": -1, "sumIncome": 0}},
                {"groupBy": {"merchant": None}, "summary": {"count": 2}},
            ]
        }
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)):
            out = json.loads(
                await find_merchants_missing_logos(
                    start_date="2026-01-01", spending_only=False
                )
            )
        assert [m["merchant_id"] for m in out["merchants"]] == ["c", "a"]
        assert out["merchants_with_logo"] == 1
        assert out["merchants_without_logo"] == 2
        assert client.gql_call.await_args.kwargs["variables"] == {
            "filters": {"startDate": "2026-01-01"}
        }
        client.get_transaction_categories.assert_not_called()

    async def test_spending_only_filters_to_expense_categories(self):
        client = AsyncMock()
        client.get_transaction_categories.return_value = {
            "categories": [
                {"id": "groceries", "group": {"type": "expense"}},
                {"id": "transfer", "group": {"type": "transfer"}},
                {"id": "paycheck", "group": {"type": "income"}},
                {"id": "dining", "group": {"type": "expense"}},
                {"id": "orphan", "group": None},
            ]
        }
        client.gql_call.return_value = {"byMerchant": []}
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)):
            out = json.loads(await find_merchants_missing_logos())
        assert out["spending_only"] is True
        assert client.gql_call.await_args.kwargs["variables"] == {
            "filters": {"categories": ["groceries", "dining"]}
        }

    async def test_spending_only_with_no_expense_categories_returns_nothing(self):
        # An empty categories filter means "no filter" to Monarch, so it must
        # never be sent: that would silently count transfers and income again.
        client = AsyncMock()
        client.get_transaction_categories.return_value = {
            "categories": [{"id": "transfer", "group": {"type": "transfer"}}]
        }
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)):
            out = json.loads(await find_merchants_missing_logos())
        assert out["count"] == 0 and out["merchants"] == []
        client.gql_call.assert_not_called()


# ---------------------------------------------------------------------------
# ICO conversion
# ---------------------------------------------------------------------------


def _bmp32_entry(w, h, pixel_fn, alpha=True, mask_fn=None):
    """A 32bpp ICO bitmap: BITMAPINFOHEADER, bottom-up BGRA rows, AND mask."""
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = []
    for y in reversed(range(h)):
        row = b""
        for x in range(w):
            r, g, b, a = pixel_fn(x, y)
            row += bytes((b, g, r, a if alpha else 0))
        rows.append(row)
    stride = ((w + 31) // 32) * 4
    mask_rows = []
    for y in reversed(range(h)):
        bits = bytearray(stride)
        for x in range(w):
            if mask_fn and mask_fn(x, y):
                bits[x // 8] |= 0x80 >> (x % 8)
        mask_rows.append(bytes(bits))
    return header + b"".join(rows) + b"".join(mask_rows)


def _ico(entries):
    """entries: list of (w, h, bpp, payload)."""
    out = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    blobs = b""
    for w, h, bpp, payload in entries:
        out += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, bpp,
                           len(payload), offset + len(blobs))
        blobs += payload
    return out + blobs


def _decode_png(data):
    """Minimal decoder for the filter-0 RGBA PNGs ico_to_png writes."""
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    pos, idat = 8, b""
    w = h = None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        assert zlib.crc32(kind + body) == struct.unpack(
            ">I", data[pos + 8 + length:pos + 12 + length])[0]
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert (depth, ctype) == (8, 6)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = 1 + w * 4
    px = {}
    for y in range(h):
        row = raw[y * stride:(y + 1) * stride]
        assert row[0] == 0
        for x in range(w):
            px[(x, y)] = tuple(row[1 + x * 4:5 + x * 4])
    return w, h, px


def _gradient(x, y):
    return (x * 10 % 256, y * 10 % 256, 200, 255)


class TestIcoToPng:
    def test_picks_largest_bmp_entry_and_keeps_orientation(self):
        ico = _ico([
            (2, 2, 32, _bmp32_entry(2, 2, lambda x, y: (1, 1, 1, 255))),
            (6, 4, 32, _bmp32_entry(6, 4, _gradient)),
            (3, 3, 32, _bmp32_entry(3, 3, lambda x, y: (2, 2, 2, 255))),
        ])
        w, h, px = _decode_png(ml.ico_to_png(ico))
        assert (w, h) == (6, 4)
        # Top-left and bottom-right prove rows were flipped and BGRA swapped.
        assert px[(0, 0)] == (0, 0, 200, 255)
        assert px[(5, 3)] == (50, 30, 200, 255)

    def test_embedded_png_entry_is_returned_as_is(self):
        png = ml._encode_png(8, 8, [bytes((9, 9, 9, 255)) * 8] * 8)
        ico = _ico([
            (4, 4, 32, _bmp32_entry(4, 4, _gradient)),
            (8, 8, 32, png),
        ])
        assert ml.ico_to_png(ico) == png

    def test_256px_entry_size_byte_zero(self):
        ico = _ico([
            (16, 16, 32, _bmp32_entry(16, 16, _gradient)),
            (256, 256, 32, _bmp32_entry(256, 256, lambda x, y: (7, 7, 7, 255))),
        ])
        w, h, px = _decode_png(ml.ico_to_png(ico))
        assert (w, h) == (256, 256) and px[(0, 0)] == (7, 7, 7, 255)

    def test_zero_alpha_bitmap_uses_and_mask(self):
        # Old-style 32bpp icons leave alpha at 0 and rely on the AND mask.
        ico = _ico([(4, 1, 32, _bmp32_entry(
            4, 1, lambda x, y: (100, 100, 100, 0), alpha=False,
            mask_fn=lambda x, y: x == 3))])
        _, _, px = _decode_png(ml.ico_to_png(ico))
        assert px[(0, 0)] == (100, 100, 100, 255)
        assert px[(3, 0)][3] == 0

    def test_palette_icon_without_sips_is_refused(self, monkeypatch):
        header = struct.pack("<IiiHHIIiiII", 40, 4, 8, 1, 8, 0, 0, 0, 0, 0, 0)
        ico = _ico([(4, 4, 8, header + b"\0" * 64)])
        monkeypatch.setattr(ml, "_sips", lambda: None)
        with pytest.raises(ValueError, match="8-bit"):
            ml.ico_to_png(ico)

    @pytest.mark.parametrize(
        "data",
        [b"\0\0\1\0", b"\0\0\1\0\1\0" + b"\0" * 16,
         _ico([(4, 4, 32, b"short")])],
    )
    def test_malformed_ico_is_refused(self, data):
        with pytest.raises(ValueError):
            ml.ico_to_png(data)


class TestSetMerchantLogoIco:
    async def test_ico_is_uploaded_as_png_without_circle_safe(self, tmp_path):
        img = tmp_path / "favicon.ico"
        img.write_bytes(_ico([(48, 48, 32, _bmp32_entry(48, 48, _gradient))]))
        info = {"path": "/v1_1/monarch-money/image/upload/", "requestParams": {}}
        client = AsyncMock()
        client.gql_call.side_effect = [
            MERCHANT,
            {"getCloudinaryUploadInfo": {"info": info, "errors": None}},
            {"setMerchantLogo": {"merchant": {"id": "m1", "logoUrl": "https://l"},
                                 "errors": None}},
        ]
        upload = AsyncMock(return_value="pid")
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)), \
             patch.object(ml, "upload_to_cloudinary", upload):
            out = json.loads(await set_merchant_logo(
                merchant_id="m1", image_path=str(img), dry_run=False))
        assert out["success"] is True
        assert out["mime_type"] == "image/png"
        assert out["source_dimensions"] == "48x48"
        assert "48x48" in out["warning"]
        _, data, mime = upload.await_args.args
        assert mime == "image/png" and data.startswith(b"\x89PNG")

    async def test_ico_dry_run_preview_is_png(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ml, "PREVIEW_DIR", tmp_path / "previews")
        img = tmp_path / "favicon.ico"
        img.write_bytes(_ico([(32, 32, 32, _bmp32_entry(32, 32, _gradient))]))
        client = AsyncMock()
        client.gql_call.return_value = MERCHANT
        with patch.object(ml, "get_monarch_client", AsyncMock(return_value=client)):
            out = json.loads(await set_merchant_logo(
                merchant_id="m1", image_path=str(img)))
        assert out["preview_path"].endswith("m1.png")
        assert out["mime_type"] == "image/png"
