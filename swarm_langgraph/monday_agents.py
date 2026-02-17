from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

MONDAY_API_URL = os.environ.get("MONDAY_API_URL", "https://api.monday.com/v2")
MONDAY_API_TOKEN = os.environ.get("MONDAY_API_TOKEN", "").strip()
MONDAY_BOARD_IDS = os.environ.get("MONDAY_BOARD_IDS") or os.environ.get("MONDAY_BOARD_ID") or "18397429943"


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def configured_board_ids() -> list[int]:
    board_ids: list[int] = []
    for token in str(MONDAY_BOARD_IDS).split(","):
        token = token.strip()
        if token.isdigit():
            board_ids.append(int(token))
    return board_ids


def _email_domain(email: str) -> str:
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].lower().strip()


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
    if parsed.get("errors"):
        raise RuntimeError(f"Monday API GraphQL errors: {parsed['errors']}")
    data = parsed.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Monday API returned no data object")
    return data


def _boards_with_items_and_updates(board_ids: list[int]) -> list[dict[str, Any]]:
    if not board_ids:
        return []
    query = (
        "query { boards(ids: ["
        + ",".join(str(v) for v in board_ids)
        + "]) { id name items_page(limit: 50) { items { id name updated_at column_values { id text } updates(limit: 5) { id body created_at } } } } }"
    )
    data = _monday_graphql(query)
    boards = data.get("boards")
    return boards if isinstance(boards, list) else []


def _item_score(item: dict[str, Any], sender_email: str, sender_domain: str) -> tuple[int, list[str]]:
    name = str(item.get("name", "")).lower()
    text_blob_parts = [name]
    for column in item.get("column_values") or []:
        if isinstance(column, dict):
            text_blob_parts.append(str(column.get("text", "")).lower())
    blob = " ".join(text_blob_parts)

    score = 0
    reasons: list[str] = []
    if sender_email and sender_email.lower() in blob:
        score += 5
        reasons.append("matched_sender_email")
    if sender_domain and sender_domain in blob:
        score += 3
        reasons.append("matched_sender_domain")
    domain_root = sender_domain.split(".", 1)[0] if sender_domain else ""
    if domain_root and domain_root in blob:
        score += 2
        reasons.append("matched_company_root")
    if name and sender_domain and sender_domain in name:
        score += 1
        reasons.append("matched_name")
    return score, reasons


def monday_contact_subagent(sender_email: str, boards: list[dict[str, Any]]) -> dict[str, Any]:
    sender_domain = _email_domain(sender_email)
    best_item: dict[str, Any] | None = None
    best_board: dict[str, Any] | None = None
    best_score = 0
    best_reasons: list[str] = []

    for board in boards:
        items = ((board.get("items_page") or {}).get("items") or []) if isinstance(board, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            score, reasons = _item_score(item, sender_email=sender_email, sender_domain=sender_domain)
            if score > best_score:
                best_score = score
                best_item = item
                best_board = board
                best_reasons = reasons

    return {
        "sender_email": sender_email,
        "sender_domain": sender_domain,
        "match_score": best_score,
        "match_reasons": best_reasons,
        "matched_board": {
            "id": str(best_board.get("id")) if best_board else None,
            "name": str(best_board.get("name")) if best_board else None,
        },
        "matched_item": best_item,
    }


def monday_deal_subagent(contact_result: dict[str, Any]) -> dict[str, Any]:
    item = contact_result.get("matched_item") or {}
    if not isinstance(item, dict):
        item = {}
    status_candidates: list[str] = []
    for column in item.get("column_values") or []:
        if not isinstance(column, dict):
            continue
        column_id = str(column.get("id", "")).lower()
        text = str(column.get("text", "")).strip()
        if not text:
            continue
        if "status" in column_id or re.search(r"\b(active|won|lost|blocked|pending|qualified|proposal)\b", text.lower()):
            status_candidates.append(text)
    deal_status = status_candidates[0] if status_candidates else "unknown"
    return {
        "deal_status": deal_status,
        "deal_stage_candidates": status_candidates[:5],
    }


def monday_updates_subagent(contact_result: dict[str, Any]) -> dict[str, Any]:
    item = contact_result.get("matched_item") or {}
    if not isinstance(item, dict):
        item = {}
    updates = item.get("updates") or []
    parsed_updates: list[dict[str, Any]] = []
    for upd in updates:
        if not isinstance(upd, dict):
            continue
        parsed_updates.append(
            {
                "id": str(upd.get("id", "")),
                "created_at": upd.get("created_at"),
                "body": str(upd.get("body", "")).strip()[:500],
            }
        )
    latest = parsed_updates[0] if parsed_updates else None
    return {
        "latest_update": latest,
        "recent_updates": parsed_updates[:3],
    }


def monday_coordinator_agent(work_order: dict[str, Any]) -> dict[str, Any]:
    sender_email = str(work_order.get("sender", "")).strip().lower()
    board_ids = configured_board_ids()
    response = {
        "enabled": bool(MONDAY_API_TOKEN and board_ids),
        "requested_at": _now_iso(),
        "board_ids": board_ids,
        "agent_trace": [
            "monday_coordinator_agent",
            "monday_contact_subagent",
            "monday_deal_subagent",
            "monday_updates_subagent",
        ],
        "source": "monday_api_v2",
        "errors": [],
    }
    if not response["enabled"]:
        response["errors"].append("monday_not_configured")
        response["match_confidence"] = "none"
        response["crm_context"] = {}
        return response

    try:
        boards = _boards_with_items_and_updates(board_ids)
        contact = monday_contact_subagent(sender_email=sender_email, boards=boards)
        deal = monday_deal_subagent(contact)
        updates = monday_updates_subagent(contact)
        score = int(contact.get("match_score", 0))
        confidence = "high" if score >= 5 else ("medium" if score >= 2 else "low")
        response["match_confidence"] = confidence
        response["crm_context"] = {
            "matched_board": contact.get("matched_board"),
            "matched_item_id": (contact.get("matched_item") or {}).get("id"),
            "matched_item_name": (contact.get("matched_item") or {}).get("name"),
            "deal_status": deal.get("deal_status"),
            "deal_stage_candidates": deal.get("deal_stage_candidates"),
            "latest_update": updates.get("latest_update"),
            "recent_updates": updates.get("recent_updates"),
            "match_reasons": contact.get("match_reasons"),
            "match_score": score,
        }
        return response
    except Exception as exc:
        response["errors"].append(str(exc))
        response["match_confidence"] = "none"
        response["crm_context"] = {}
        return response
