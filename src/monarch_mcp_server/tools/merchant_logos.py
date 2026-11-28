"""Merchant logo tools: find merchants with no logo, and set a custom one.

Monarch's web app sets a custom merchant logo in three steps, mirrored here
(captured from app.monarch.com, web client v1.0.6593):

1. ``Common_GetCloudinaryUploadInfo`` with ``entityType: "merchant"`` returns
   an upload path (``info.path``, e.g. ``/v1_1/monarch-money/image/upload/``,
   relative to ``api.cloudinary.com``) plus a signed parameter set:
   ``timestamp``, ``folder``, ``signature``, ``api_key`` and ``upload_preset``.
2. The image is POSTed as multipart form data straight to that URL
   (Cloudinary). The JSON response carries the uploaded image's ``public_id``,
   e.g. ``production/merchant_logos/custom/<uuid>/<id>``.
3. ``Common_SetMerchantLogo`` attaches that public id to the merchant.

The signed parameters are sent back exactly as received, since the signature
covers them. The Cloudinary POST needs no Monarch credentials.
"""

import asyncio
import logging
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import (
    json_error,
    json_rejected,
    json_success,
    payload_errors,
)

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT = 20.0
UPLOAD_TIMEOUT = 60.0
# Some sites refuse an obviously scripted client, so present as Safari.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)
# Canvas for circle-safe padding. The square inscribed in a circle spans
# 1/sqrt(2) ~= 70.7% of its diameter, so a mark scaled to that fraction of the
# canvas survives Monarch's circular crop untouched.
CIRCLE_CANVAS = 512
CIRCLE_INSET = 0.70
PREVIEW_DIR = Path(tempfile.gettempdir()) / "monarch-logo-previews"

# ---------------------------------------------------------------------------
# GraphQL constants (operation names and shapes match the web client)
# ---------------------------------------------------------------------------

GET_MERCHANT_LOGO_QUERY = gql(
    """
query Web_GetMerchantDetails($id: ID!) {
  merchant(id: $id) {
    id
    name
    logoUrl
    __typename
  }
}
"""
)

GET_CLOUDINARY_UPLOAD_INFO_MUTATION = gql(
    """
mutation Common_GetCloudinaryUploadInfo($input: GetLogoCloudinaryUploadInfoMutationInput!) {
  getCloudinaryUploadInfo(input: $input) {
    info {
      path
      requestParams {
        timestamp
        folder
        signature
        api_key
        upload_preset
        __typename
      }
      __typename
    }
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""
)

SET_MERCHANT_LOGO_MUTATION = gql(
    """
mutation Common_SetMerchantLogo($input: SetMerchantLogoInput!) {
  setMerchantLogo(input: $input) {
    merchant {
      id
      name
      logoUrl
      __typename
    }
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""
)

MERCHANT_AGGREGATES_QUERY = gql(
    """
query Common_GetMerchantLogoAggregates($filters: TransactionFilterInput) {
  byMerchant: aggregates(filters: $filters, groupBy: ["merchant"]) {
    groupBy {
      merchant {
        id
        name
        logoUrl
        __typename
      }
      __typename
    }
    summary {
      count
      sumExpense
      sumIncome
      __typename
    }
    __typename
  }
}
"""
)

# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

_EXT_FOR_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/x-icon": ".ico",
}


def sniff_image(data: bytes) -> Optional[str]:
    """Return the MIME type of a raster image from its magic bytes, else None.

    This is the gate that keeps ``image_path`` from uploading arbitrary local
    files: anything that is not a PNG, JPEG, GIF, WebP or ICO is refused before
    it leaves the machine. SVG is deliberately excluded (it can carry script).
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon"
    return None


def png_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    """Width and height from a PNG's IHDR chunk, without decoding it."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    return None


def _sips() -> Optional[str]:
    return shutil.which("sips")


def _run_sips(*args: str) -> str:
    proc = subprocess.run(
        [_sips(), *args], capture_output=True, text=True, check=True  # type: ignore[list-item]
    )
    return proc.stdout


def image_dimensions(data: bytes, mime: str) -> Optional[Tuple[int, int]]:
    """Best-effort dimensions: PNG header directly, anything else via sips."""
    dims = png_dimensions(data)
    if dims or not _sips():
        return dims
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"img{_EXT_FOR_MIME.get(mime, '.bin')}"
        src.write_bytes(data)
        try:
            out = _run_sips("-g", "pixelWidth", "-g", "pixelHeight", str(src))
        except (subprocess.CalledProcessError, OSError):
            return None
    w = re.search(r"pixelWidth:\s*(\d+)", out)
    h = re.search(r"pixelHeight:\s*(\d+)", out)
    return (int(w.group(1)), int(h.group(1))) if w and h else None


def pad_for_circle(data: bytes, mime: str, pad_color: str) -> bytes:
    """Scale the image into the circle's inscribed square and pad to a square.

    Uses macOS ``sips`` so the server needs no imaging dependency. Output is
    always PNG. Transparent regions of the source stay transparent; only the
    added margin takes ``pad_color``.
    """
    if not _sips():
        raise RuntimeError("circle_safe padding needs macOS 'sips', which was not found")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", pad_color):
        raise ValueError("pad_color must be a 6-digit hex colour such as FFFFFF")
    inner = round(CIRCLE_CANVAS * CIRCLE_INSET)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"src{_EXT_FOR_MIME.get(mime, '.bin')}"
        out = Path(tmp) / "logo.png"
        src.write_bytes(data)
        _run_sips("-s", "format", "png", str(src), "--out", str(out))
        _run_sips("-Z", str(inner), str(out))
        _run_sips(
            "--padToHeightWidth",
            str(CIRCLE_CANVAS),
            str(CIRCLE_CANVAS),
            "--padColor",
            pad_color.upper(),
            str(out),
        )
        return out.read_bytes()


# ---------------------------------------------------------------------------
# Fetching and source resolution
# ---------------------------------------------------------------------------

_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_ATTR_RE = re.compile(r"""([a-zA-Z:-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""")


def icon_candidates(html: str, base_url: str) -> List[str]:
    """Icon URLs declared in a page's <link> tags, best first.

    apple-touch-icon outranks plain icon (it is a large, padded PNG made for a
    rounded tile), then larger declared sizes win. SVG icons are skipped.
    """
    scored: List[Tuple[int, str]] = []
    for tag in _LINK_RE.findall(html):
        attrs = {
            m.group(1).lower(): (m.group(3) or m.group(4) or m.group(5) or "")
            for m in _ATTR_RE.finditer(tag)
        }
        rel = attrs.get("rel", "").lower().split()
        href = attrs.get("href")
        if not href:
            continue
        if "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel:
            bonus, default_size = 10_000, 180
        elif "icon" in rel:
            bonus, default_size = 0, 16
        else:
            continue
        if href.lower().split("?")[0].endswith(".svg") or "svg" in attrs.get("type", ""):
            continue
        size_match = re.match(r"(\d+)x\d+", attrs.get("sizes", ""))
        size = int(size_match.group(1)) if size_match else default_size
        scored.append((bonus + size, urljoin(base_url, href)))
    seen, ordered = set(), []
    for _, url in sorted(scored, key=lambda s: -s[0]):
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


async def _fetch(http: httpx.AsyncClient, url: str) -> bytes:
    """GET a URL with a hard size cap."""
    async with http.stream("GET", url) as resp:
        resp.raise_for_status()
        chunks, total = [], 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise ValueError(f"{url} exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
            chunks.append(chunk)
        return b"".join(chunks)


def _require_https(url: str) -> None:
    if urlparse(url).scheme != "https":
        raise ValueError("image_url must be an https:// URL")


async def resolve_from_domain(
    http: httpx.AsyncClient, domain: str
) -> Tuple[bytes, str, str, List[str]]:
    """Find a usable icon for a domain. Returns (bytes, mime, url, tried)."""
    host = re.sub(r"^https?://", "", domain.strip()).split("/")[0]
    if not host or "." not in host:
        raise ValueError(f"'{domain}' does not look like a domain")
    home = f"https://{host}/"
    candidates: List[str] = []
    try:
        page = await http.get(home)
        if page.status_code < 400:
            candidates += icon_candidates(page.text[:500_000], str(page.url))
    except httpx.HTTPError as exc:
        # repr, not str: a timeout's str() is empty, which hid the cause.
        logger.info("set_merchant_logo: homepage fetch failed for %s: %r", host, exc)
    candidates += [
        urljoin(home, "/apple-touch-icon.png"),
        f"https://icons.duckduckgo.com/ip3/{host}.ico",
    ]
    tried: List[str] = []
    for url in dict.fromkeys(candidates):
        tried.append(url)
        try:
            data = await _fetch(http, url)
        except (httpx.HTTPError, ValueError):
            continue
        mime = sniff_image(data)
        if mime:
            return data, mime, url, tried
    raise ValueError(f"No usable raster icon found for {host}")


async def load_source(
    image_url: Optional[str], image_path: Optional[str], domain: Optional[str]
) -> Dict[str, Any]:
    """Resolve exactly one source into validated image bytes."""
    sources = [s for s in (image_url, image_path, domain) if s]
    if len(sources) != 1:
        raise ValueError("Provide exactly one of image_url, image_path or domain")

    if image_path:
        path = Path(image_path).expanduser()
        if not path.is_file():
            raise ValueError(f"{path} is not a file")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError(f"{path} exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        data = path.read_bytes()
        mime = sniff_image(data)
        if not mime:
            raise ValueError(f"{path} is not a PNG, JPEG, GIF, WebP or ICO image")
        return {"data": data, "mime": mime, "source": str(path), "tried": []}

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=FETCH_TIMEOUT,
        headers={"User-Agent": BROWSER_UA},
    ) as http:
        if image_url:
            _require_https(image_url)
            data = await _fetch(http, image_url)
            mime = sniff_image(data)
            if not mime:
                raise ValueError(
                    "image_url did not return a PNG, JPEG, GIF, WebP or ICO image "
                    "(signed CDN links such as Instagram's expire; copy a fresh one)"
                )
            return {"data": data, "mime": mime, "source": image_url, "tried": []}

        data, mime, url, tried = await resolve_from_domain(http, domain)  # type: ignore[arg-type]
        return {"data": data, "mime": mime, "source": url, "tried": tried}


CLOUDINARY_API_BASE = "https://api.cloudinary.com"


def cloudinary_upload_url(path: Optional[str]) -> str:
    """Turn Monarch's ``info.path`` into the Cloudinary upload URL.

    Monarch returns a path relative to Cloudinary's API host
    (``/v1_1/monarch-money/image/upload/``), which is joined to
    ``api.cloudinary.com``. A full URL is accepted too, but only https on a
    cloudinary.com host, so the image and signed params cannot be sent
    anywhere else.
    """
    if path and path.startswith("/") and not path.startswith("//"):
        url = CLOUDINARY_API_BASE + path
    else:
        url = path or ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        host == "cloudinary.com" or host.endswith(".cloudinary.com")
    ):
        raise RuntimeError(f"Unexpected upload path from Monarch: {path!r}")
    return url


async def upload_to_cloudinary(info: Dict[str, Any], data: bytes, mime: str) -> str:
    """POST the image to the signed upload URL and return its public_id."""
    url = cloudinary_upload_url(info.get("path"))
    params = {
        k: str(v)
        for k, v in (info.get("requestParams") or {}).items()
        if k != "__typename" and v is not None
    }
    filename = f"logo{_EXT_FOR_MIME.get(mime, '.png')}"
    async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT) as http:
        resp = await http.post(url, data=params, files={"file": (filename, data, mime)})
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400 or not body.get("public_id"):
        detail = (body.get("error") or {}).get("message") if isinstance(body, dict) else None
        raise RuntimeError(
            f"Image upload failed (HTTP {resp.status_code}): {detail or resp.text[:300]}"
        )
    return body["public_id"]


def _write_preview(merchant_id: str, data: bytes, mime: str) -> str:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = PREVIEW_DIR / f"{merchant_id}{_EXT_FOR_MIME.get(mime, '.png')}"
    path.write_bytes(data)
    return str(path)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def find_merchants_missing_logos(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_with_logos: bool = False,
    spending_only: bool = True,
) -> str:
    """
    List merchants that have no logo, ranked by how many transactions use them.

    Built on Monarch's transaction aggregates grouped by merchant, so only
    merchants with at least one transaction in the window appear. Merchants
    you renamed or created yourself are the usual ones without a logo, since
    they lose Monarch's automatic brand match.

    By default only transactions in expense categories are counted, so
    transfers, card payments, deposits, interest, paychecks and brokerage
    journal entries (which are not vendors and gain nothing from a logo) drop
    out. Counts and totals then cover spending only.

    Args:
        start_date: Optional window start, YYYY-MM-DD. Omit for all time.
        end_date: Optional window end, YYYY-MM-DD.
        include_with_logos: Also return merchants that already have a logo.
        spending_only: Count only transactions in expense-type categories
            (default True). Set False to include income and transfer merchants.

    Returns:
        Merchants with id, name, logo_url, transaction_count and totals, plus
        counts of merchants with and without logos.

    Example:
        find_merchants_missing_logos(start_date="2026-01-01")
    """
    try:
        filters: Dict[str, Any] = {}
        if start_date:
            filters["startDate"] = start_date
        if end_date:
            filters["endDate"] = end_date

        client = await get_monarch_client()
        if spending_only:
            cats = await client.get_transaction_categories()
            expense_ids = [
                c["id"]
                for c in (cats or {}).get("categories") or []
                if c.get("id") and ((c.get("group") or {}).get("type") == "expense")
            ]
            if not expense_ids:
                # An empty categories filter means "all categories" to Monarch,
                # which would bring transfers and income straight back.
                return json_success(
                    {
                        "spending_only": True,
                        "merchants_with_logo": 0,
                        "merchants_without_logo": 0,
                        "count": 0,
                        "merchants": [],
                        "message": "No expense categories found",
                    }
                )
            filters["categories"] = expense_ids

        result = await client.gql_call(
            operation="Common_GetMerchantLogoAggregates",
            graphql_query=MERCHANT_AGGREGATES_QUERY,
            variables={"filters": filters},
        )

        rows: List[Dict[str, Any]] = []
        with_logo = without_logo = 0
        for agg in result.get("byMerchant") or []:
            merchant = (agg.get("groupBy") or {}).get("merchant")
            if not merchant or not merchant.get("id"):
                continue
            summary = agg.get("summary") or {}
            has_logo = bool(merchant.get("logoUrl"))
            with_logo += has_logo
            without_logo += not has_logo
            if has_logo and not include_with_logos:
                continue
            rows.append(
                {
                    "merchant_id": merchant["id"],
                    "name": merchant.get("name"),
                    "logo_url": merchant.get("logoUrl"),
                    "transaction_count": summary.get("count"),
                    "sum_expense": summary.get("sumExpense"),
                    "sum_income": summary.get("sumIncome"),
                }
            )
        rows.sort(key=lambda r: -(r.get("transaction_count") or 0))
        return json_success(
            {
                "spending_only": spending_only,
                "merchants_with_logo": with_logo,
                "merchants_without_logo": without_logo,
                "count": len(rows),
                "merchants": rows,
            }
        )
    except Exception as e:
        return json_error("find_merchants_missing_logos", e)


@mcp.tool()
async def set_merchant_logo(
    merchant_id: str,
    image_url: Optional[str] = None,
    image_path: Optional[str] = None,
    domain: Optional[str] = None,
    circle_safe: bool = False,
    pad_color: str = "FFFFFF",
    dry_run: bool = True,
) -> str:
    """
    Set a custom logo on a merchant. Dry run by default.

    Give exactly one image source:
      - image_url: any https image, e.g. a brand's Instagram profile picture
        (already composed for a circle, which suits Monarch's round crop).
        Instagram and similar CDN links are signed and expire, so use a
        freshly copied one.
      - image_path: a local PNG/JPEG/GIF/WebP/ICO file on this Mac.
      - domain: e.g. "example.com". Resolves the site's apple-touch-icon, then
        its largest declared icon, then /apple-touch-icon.png, then
        DuckDuckGo's icon service (low resolution, last resort).

    With dry_run=True (the default) nothing is uploaded or changed: the tool
    resolves and validates the image, writes a preview file you can open in
    Quick Look, and reports the merchant's current logo. Call again with
    dry_run=False to upload it and attach it to the merchant. Replacing a logo
    is reversible by setting another one.

    Args:
        merchant_id: Monarch merchant ID (from find_merchants_missing_logos,
            get_merchant, or transaction listings).
        image_url: https URL of the image.
        image_path: Path to a local image file (~ is expanded).
        domain: Website domain to pull an icon from.
        circle_safe: Shrink the image into the circle's inscribed square and
            pad it to a 512x512 square, so a square logo is not clipped by
            the round crop. Leave off for images already made for a circle.
        pad_color: 6-digit hex colour for the padding margin (default white).
        dry_run: Validate and preview only (default True).

    Returns:
        Merchant name, previous and resulting logo URL, image source, MIME
        type, size, dimensions and (for dry runs) the preview file path.

    Example:
        set_merchant_logo(merchant_id="123456789012345678",
                          domain="example.com", circle_safe=True)
    """
    try:
        client = await get_monarch_client()
        current = await client.gql_call(
            operation="Web_GetMerchantDetails",
            graphql_query=GET_MERCHANT_LOGO_QUERY,
            variables={"id": merchant_id},
        )
        merchant = current.get("merchant")
        if not merchant:
            return json_success(
                {"success": False, "message": f"No merchant found with ID {merchant_id}"}
            )

        loaded = await load_source(image_url, image_path, domain)
        data, mime = loaded["data"], loaded["mime"]
        # Measure before padding: circle_safe always yields a 512 canvas, so
        # the padded size says nothing about how sharp the source was.
        src_dims = await asyncio.to_thread(image_dimensions, data, mime)
        if circle_safe:
            data = await asyncio.to_thread(pad_for_circle, data, mime, pad_color)
            mime = "image/png"
            dims = await asyncio.to_thread(image_dimensions, data, mime)
        else:
            dims = src_dims

        report: Dict[str, Any] = {
            "merchant_id": merchant_id,
            "merchant_name": merchant.get("name"),
            "previous_logo_url": merchant.get("logoUrl"),
            "source": loaded["source"],
            "sources_tried": loaded["tried"] or None,
            "mime_type": mime,
            "bytes": len(data),
            "source_dimensions": f"{src_dims[0]}x{src_dims[1]}" if src_dims else None,
            "dimensions": f"{dims[0]}x{dims[1]}" if dims else None,
            "circle_safe": circle_safe,
        }
        if src_dims and min(src_dims) < 128:
            report["warning"] = (
                f"Source image is only {src_dims[0]}x{src_dims[1]}; it will look "
                "soft in Monarch. A larger source (apple-touch-icon or a profile "
                "picture via image_url) is better."
            )

        if dry_run:
            report["dry_run"] = True
            report["preview_path"] = await asyncio.to_thread(
                _write_preview, merchant_id, data, mime
            )
            return json_success(report)

        info_result = await client.gql_call(
            operation="Common_GetCloudinaryUploadInfo",
            graphql_query=GET_CLOUDINARY_UPLOAD_INFO_MUTATION,
            variables={"input": {"entityType": "merchant"}},
        )
        errors = payload_errors(info_result, "getCloudinaryUploadInfo")
        if errors:
            return json_rejected("set_merchant_logo", errors)
        info = (info_result.get("getCloudinaryUploadInfo") or {}).get("info") or {}

        public_id = await upload_to_cloudinary(info, data, mime)

        set_result = await client.gql_call(
            operation="Common_SetMerchantLogo",
            graphql_query=SET_MERCHANT_LOGO_MUTATION,
            variables={
                "input": {"merchantId": merchant_id, "cloudinaryPublicId": public_id}
            },
        )
        errors = payload_errors(set_result, "setMerchantLogo")
        if errors:
            return json_rejected("set_merchant_logo", errors)

        updated = (set_result.get("setMerchantLogo") or {}).get("merchant") or {}
        report.update(
            {
                "success": True,
                "dry_run": False,
                "cloudinary_public_id": public_id,
                "logo_url": updated.get("logoUrl"),
            }
        )
        return json_success(report)
    except Exception as e:
        return json_error("set_merchant_logo", e)
