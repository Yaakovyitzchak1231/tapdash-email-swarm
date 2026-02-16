#!/usr/bin/env python3
"""On-demand CRM enrichment service with source references."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PORT = int(os.environ.get("PORT", "8090"))
MONDAY_API_URL = os.environ.get("MONDAY_API_URL", "https://api.monday.com/v2")
MONDAY_API_TOKEN = os.environ.get("MONDAY_API_TOKEN", "").strip()
MONDAY_BOARD_IDS = os.environ.get("MONDAY_BOARD_IDS") or os.environ.get("MONDAY_BOARD_ID") or "18397429943"

FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
}


@dataclass
class SourceReference:
    id: str
    kind: str
    title: str
    url: str | None
    accessed_at: str
    note: str


@dataclass
class EnrichedField:
    value: Any
    confidence: str
    source_refs: list[str]


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _safe_get(payload: dict[str, Any], key: str) -> str:
    return str(payload.get(key, "")).strip()


def _email_domain(email: str) -> str:
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].lower().strip()


def _company_from_domain(domain: str) -> str:
    root = domain.split(".")[0] if domain else ""
    root = re.sub(r"[^a-z0-9]+", " ", root.lower()).strip()
    return " ".join(part.capitalize() for part in root.split())


def configured_board_ids() -> list[int]:
    board_ids: list[int] = []
    for token in str(MONDAY_BOARD_IDS).split(","):
        cleaned = token.strip()
        if not cleaned:
            continue
        if cleaned.isdigit():
            board_ids.append(int(cleaned))
    return board_ids


def _build_board_summary_query(board_ids: list[int]) -> str:
    id_list = ",".join(str(v) for v in board_ids)
    return (
        "query { boards(ids: ["
        + id_list
        + "]) { id name state items_page(limit: 5) { items { id name updated_at } } } }"
    )


def _monday_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    if not MONDAY_API_TOKEN:
        raise RuntimeError("MONDAY_API_TOKEN is not set")

    payload = {"query": query, "variables": variables or {}}
    req = urllib.request.Request(
        MONDAY_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": MONDAY_API_TOKEN,
            "Content-Type": "application/json",
            "User-Agent": "TapdashEmailSwarm/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Monday API HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Monday API connection error: {exc.reason}") from exc

    parsed = json.loads(raw)
    if "errors" in parsed and parsed["errors"]:
        raise RuntimeError(f"Monday API GraphQL errors: {parsed['errors']}")
    if not isinstance(parsed.get("data"), dict):
        raise RuntimeError("Monday API returned no data object")
    return parsed["data"]


def fetch_board_summary(board_ids: list[int] | None = None) -> dict[str, Any]:
    scope = board_ids or configured_board_ids()
    if not scope:
        raise RuntimeError("No valid Monday board IDs configured")

    query = _build_board_summary_query(scope)
    data = _monday_graphql(query)
    boards = data.get("boards") or []

    summarized: list[dict[str, Any]] = []
    for board in boards:
        items_page = board.get("items_page") or {}
        items = items_page.get("items") or []
        summarized.append(
            {
                "id": board.get("id"),
                "name": board.get("name"),
                "state": board.get("state"),
                "sample_item_count": len(items),
                "sample_items": items,
            }
        )

    return {
        "provider": "monday_api_v2",
        "requested_at": _now_iso(),
        "board_scope": scope,
        "boards": summarized,
    }


def enrich_lead(payload: dict[str, Any]) -> dict[str, Any]:
    lead = payload.get("lead", {})
    if not isinstance(lead, dict):
        raise ValueError("lead must be an object")

    requested_fields = payload.get("requested_fields")
    if requested_fields is not None and (
        not isinstance(requested_fields, list)
        or not all(isinstance(item, str) for item in requested_fields)
    ):
        raise ValueError("requested_fields must be an array of strings")

    lead_id = _safe_get(lead, "id") or "unknown"
    email = _safe_get(lead, "email")
    website = _safe_get(lead, "website")
    title = _safe_get(lead, "title")
    company = _safe_get(lead, "company")

    accessed_at = _now_iso()
    source_refs: list[SourceReference] = []

    source_refs.append(
        SourceReference(
            id="src_input",
            kind="input_payload",
            title="Inbound lead payload",
            url=None,
            accessed_at=accessed_at,
            note="Customer-provided lead data used as primary source.",
        )
    )

    if website:
        source_refs.append(
            SourceReference(
                id="src_website",
                kind="company_website",
                title=f"{company or 'Company'} website",
                url=website,
                accessed_at=accessed_at,
                note="Website value was provided in payload.",
            )
        )

    extra_sources = payload.get("lookup_sources", [])
    if not isinstance(extra_sources, list):
        raise ValueError("lookup_sources must be an array when provided")
    for idx, source in enumerate(extra_sources, start=1):
        if not isinstance(source, dict):
            raise ValueError("lookup_sources entries must be objects")
        source_refs.append(
            SourceReference(
                id=f"src_lookup_{idx}",
                kind=_safe_get(source, "kind") or "external_lookup",
                title=_safe_get(source, "title") or f"Lookup source {idx}",
                url=_safe_get(source, "url") or None,
                accessed_at=accessed_at,
                note=_safe_get(source, "note") or "External lookup evidence.",
            )
        )

    domain = _email_domain(email) or _safe_get(lead, "company_domain").lower()
    inferred_company = company or _company_from_domain(domain)
    is_free_email = domain in FREE_EMAIL_DOMAINS if domain else False
    fit_tier = "low" if is_free_email else ("high" if domain else "medium")

    title_lower = title.lower()
    if any(token in title_lower for token in ("chief", "vp", "vice president", "head", "director")):
        seniority = "executive"
    elif any(token in title_lower for token in ("manager", "lead", "owner", "founder")):
        seniority = "mid"
    elif title:
        seniority = "individual_contributor"
    else:
        seniority = "unknown"

    fields: dict[str, EnrichedField] = {
        "company_domain": EnrichedField(
            value=domain or None,
            confidence="high" if domain else "low",
            source_refs=["src_input"],
        ),
        "company_name_inferred": EnrichedField(
            value=inferred_company or None,
            confidence="medium" if inferred_company else "low",
            source_refs=["src_input"],
        ),
        "is_free_email": EnrichedField(
            value=is_free_email,
            confidence="high" if domain else "low",
            source_refs=["src_input"],
        ),
        "contact_seniority": EnrichedField(
            value=seniority,
            confidence="medium" if title else "low",
            source_refs=["src_input"],
        ),
        "fit_tier": EnrichedField(
            value=fit_tier,
            confidence="medium",
            source_refs=["src_input"],
        ),
        "monday_board_scope": EnrichedField(
            value=configured_board_ids(),
            confidence="high" if configured_board_ids() else "low",
            source_refs=["src_input"],
        ),
    }

    if website:
        fields["company_website"] = EnrichedField(
            value=website,
            confidence="high",
            source_refs=["src_website"],
        )

    if extra_sources:
        fields["external_source_count"] = EnrichedField(
            value=len(extra_sources),
            confidence="high",
            source_refs=[ref.id for ref in source_refs if ref.id.startswith("src_lookup_")],
        )

    if requested_fields is not None:
        filtered = {k: v for k, v in fields.items() if k in requested_fields}
    else:
        filtered = fields

    return {
        "lead_id": lead_id,
        "requested_at": accessed_at,
        "provider": "monday_crm_enrichment_v1",
        "enriched_fields": {k: asdict(v) for k, v in filtered.items()},
        "source_references": [asdict(ref) for ref in source_refs],
    }


class MondayEnrichmentHandler(BaseHTTPRequestHandler):
    server_version = "MondayCRMEnrichmentService/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok", "board_scope": configured_board_ids()})
            return

        if self.path.startswith("/monday/board-summary"):
            try:
                summary = fetch_board_summary()
            except RuntimeError as exc:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, {"summary": summary})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/monday/enrich":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length)
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
            return

        if not isinstance(parsed, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "payload must be an object"})
            return

        try:
            enrichment = enrich_lead(parsed)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        self._send_json(HTTPStatus.OK, {"enrichment": enrichment})

    def _send_json(self, code: HTTPStatus, data: dict[str, Any]) -> None:
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")


def run_server() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), MondayEnrichmentHandler)
    print(f"Listening on http://0.0.0.0:{PORT} (board_scope={configured_board_ids()})")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
