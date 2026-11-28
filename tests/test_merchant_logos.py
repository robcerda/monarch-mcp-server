"""Tests for the merchant logo tools."""

import json
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
            out = json.loads(await find_merchants_missing_logos(start_date="2026-01-01"))
        assert [m["merchant_id"] for m in out["merchants"]] == ["c", "a"]
        assert out["merchants_with_logo"] == 1
        assert out["merchants_without_logo"] == 2
        assert client.gql_call.await_args.kwargs["variables"] == {
            "filters": {"startDate": "2026-01-01"}
        }
