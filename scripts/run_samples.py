"""Send the 40 sample messages through the running stack, wait for processing, send scripted
replies to every follow-up question, wait again, and write the results table.

Usage: python scripts/run_samples.py [--base http://localhost:8080] [--out docs/results.md]
Reads samples/messages.json and samples/replies.json. Talks only to the HTTP API, so the table
reflects exactly what the shops and customers would see.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

KEYS = {
    "rb-downtown": "dev-key-rb-downtown",
    "rb-northside": "dev-key-rb-northside",
    "rb-lakeshore": "dev-key-rb-lakeshore",
}
PENDING = {"received"}


def h(shop_id: str) -> dict[str, str]:
    return {"X-API-Key": KEYS[shop_id]}


def post(client: httpx.Client, base: str, shop_id: str, payload: dict) -> httpx.Response:
    return client.post(f"{base}/shops/{shop_id}/messages", json=payload, headers=h(shop_id), timeout=30)


def status(client: httpx.Client, base: str, shop_id: str, message_id: str) -> dict:
    r = client.get(f"{base}/shops/{shop_id}/messages/{message_id}", headers=h(shop_id), timeout=30)
    r.raise_for_status()
    return r.json()


def wait_settled(
    client, base, targets: list[tuple[str, str]], timeout_s: float, pending_states: set[str] = PENDING
) -> dict[tuple[str, str], dict]:
    """Poll customer status until no target is in a pending state (or the deadline passes)."""
    deadline = time.time() + timeout_s
    out: dict[tuple[str, str], dict] = {}
    while True:
        out = {t: status(client, base, *t) for t in targets}
        pending = [t for t, s in out.items() if s["status"] in pending_states]
        if not pending or time.time() > deadline:
            return out
        time.sleep(1.0)


def shop_view(client, base, shop_id) -> dict:
    r = client.get(f"{base}/shops/{shop_id}/work-orders", params={"status": "all"}, headers=h(shop_id), timeout=30)
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--out", default="docs/results.md")
    ap.add_argument("--timeout", type=float, default=180)
    args = ap.parse_args()

    messages = json.loads(Path("samples/messages.json").read_text())
    replies = json.loads(Path("samples/replies.json").read_text())
    client = httpx.Client()
    started = time.time()

    # 1. Send everything, in order, as fast as the API accepts it.
    accepted: list[dict] = []
    for m in messages:
        r = post(client, args.base, m["shop_id"], {k: m[k] for k in ("message_id", "channel", "received_at", "body")})
        accepted.append({"n": m["n"], "http": r.status_code, "duplicate": r.json().get("duplicate")})
    unique = {(m["shop_id"], m["message_id"]) for m in messages}
    first = wait_settled(client, args.base, sorted(unique), args.timeout)

    # 2. Reply to every follow-up question we have a scripted answer for.
    sent_replies: dict[tuple[str, str], str] = {}
    for (shop_id, mid), s in first.items():
        if s["status"] == "awaiting_your_reply" and mid in replies:
            body = replies[mid]
            post(
                client,
                args.base,
                shop_id,
                {"message_id": f"{mid}-reply", "channel": "web", "body": body, "in_reply_to": mid},
            )
            sent_replies[(shop_id, mid)] = body
    final = dict(first)
    if sent_replies:
        # A replied-to order stays "awaiting_your_reply" until the resume job finishes; wait for that too.
        final.update(
            wait_settled(
                client, args.base, sorted(sent_replies), args.timeout, pending_states=PENDING | {"awaiting_your_reply"}
            )
        )

    # 3. Shop-side view for outcomes, totals and spend.
    views = {sid: shop_view(client, args.base, sid) for sid in KEYS}
    orders = {(sid, o["message_id"]): o for sid, v in views.items() for o in v["work_orders"]}

    rows = []
    for m in messages:
        key = (m["shop_id"], m["message_id"])
        s = final[key]
        o = orders.get(key)
        dup = any(a["n"] == m["n"] and a["duplicate"] for a in accepted)
        if dup:
            outcome = "duplicate (no new order)"
        elif o:
            outcome = o["status"] + (f" ({o['review_reason']})" if o.get("review_reason") else "")
        else:
            outcome = s["status"]
        services = ", ".join(f"{i['code']}x{i['quantity']}" for i in (o["estimate"]["line_items"] if o else [])) or "-"
        total = (
            o["estimate"]["total"] if o else ("-" if s["status"] != "answered" else s["message"].split("=")[-1].strip())
        )
        date = (o.get("requested_date") or o.get("date_note") or "-") if o else "-"
        asked = "yes" if (first[key]["status"] == "awaiting_your_reply") else ""
        replied = "yes" if key in sent_replies else ""
        rows.append(
            (m["n"], m["message_id"], m["shop_id"], outcome, services, total, str(date), asked, replied, s["status"])
        )

    c = Counter(r[3].split(" ")[0] for r in rows if not r[3].startswith("duplicate"))
    spend = sum(float(v["llm"]["cost_usd"]) for v in views.values())
    calls = sum(v["llm"]["calls"] for v in views.values())
    invalid = sum(v["llm"]["invalid_output"] for v in views.values())
    failures = sum(v["llm"]["provider_failures"] for v in views.values())
    no_order = sum(1 for r in rows if r[9] in ("answered", "cancellation_received"))
    resolved = sum(1 for k in sent_replies if orders.get(k, {}).get("status") == "open")

    lines = [
        "# Results: 40 sample messages",
        "",
        f"Generated by `scripts/run_samples.py` against `{args.base}` in {time.time() - started:.0f}s.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Messages sent | {len(messages)} ({len(unique)} unique, {len(messages) - len(unique)} duplicate) |",
        f"| Work orders open | {c.get('open', 0)} |",
        f"| Follow-up questions asked | {sum(1 for k, s in first.items() if s['status'] == 'awaiting_your_reply')} |",
        f"| Follow-ups resolved by a scripted reply | {resolved} |",
        f"| Needs staff review | {c.get('needs_review', 0)} |",
        f"| Awaiting customer (no scripted reply) | {c.get('awaiting_customer', 0)} |",
        f"| No work order (price inquiry / cancellation) | {no_order} |",
        f"| Could not process (invalid output / provider failure) | {c.get('could_not_process', 0)} |",
        f"| Model calls | {calls} (invalid output: {invalid}, provider failures: {failures}) |",
        f"| Total model spend (from the ledger) | USD {spend:.4f} |",
        "",
        "Per shop spend: "
        + ", ".join(
            f"{sid} USD {v['llm']['cost_usd']} (cap {v['budget']['cap_usd']}, exhausted={v['budget']['exhausted']})"
            for sid, v in views.items()
        ),
        "",
        "| # | message_id | shop | outcome | services | estimate | date | asked? | replied? |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} | {r[8]} |")
    text = "\n".join(lines) + "\n"
    Path(args.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
