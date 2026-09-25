"""Walk through the whole API flow against a running server, printing each step.

    python backend/scripts/try_api.py path/to/file.pdf "Your question?" [--user alice]

Steps: log in (local dev token) -> register upload -> POST the file straight to S3 (presigned
form) -> confirm -> poll ingestion -> start a conversation -> ask (JSON) -> ask a follow-up
(streaming SSE) -> show the usage bars. Pass --delete to clean up afterwards.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from documind.scripts.dev_token import mint


def bars(context: dict[str, Any] | None, account: dict[str, Any]) -> None:
    if context:
        print(
            f"   context window: {context['tokens']:,} / {context['limit']:,} tokens "
            f"({context['fraction']:.0%})"
            + (f"  NOTE: {context['notice']}" if context["notice"] else "")
        )
    print(
        f"   daily quota:    {account['tokens_used_today']:,} / {account['daily_quota']:,} tokens "
        f"used (${account['cost_usd_today']:.4f}), resets {account['reset_at']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("question")
    parser.add_argument("--user", default="alice", help="who to log in as (each is isolated)")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--delete", action="store_true", help="delete the document at the end")
    args = parser.parse_args()
    data = args.pdf.read_bytes()

    print(f"0) Log in as {args.user!r} (a local development token; Cognito on AWS)")
    headers = {"Authorization": f"Bearer {mint(args.user)}"}

    with httpx.Client(base_url=args.api, timeout=60, headers=headers) as api:
        print("1) Register the upload")
        r = api.post("/v1/documents", json={"filename": args.pdf.name, "size_bytes": len(data)})
        if r.status_code != 201:
            sys.exit(f"   failed: {r.status_code} {r.text}")
        doc_id, upload = r.json()["document"]["document_id"], r.json()["upload"]
        print(f"   document_id={doc_id}\n   upload goes straight to: {upload['url']}")

        print("2) Upload the PDF directly to S3 with the presigned form (not through the API)")
        s3 = httpx.post(
            upload["url"],
            data=upload["fields"],
            files={"file": (args.pdf.name, data, "application/pdf")},
            timeout=120,
        )
        print(f"   S3 answered {s3.status_code} (204 = stored)")

        print("3) Confirm the upload; the API queues an ingestion job on SQS")
        r = api.post(f"/v1/documents/{doc_id}/complete")
        print(f"   {r.status_code} status={r.json().get('status', r.text)}")

        print("4) Poll the status while the worker parses, chunks and embeds")
        started = time.time()
        while True:
            doc = api.get(f"/v1/documents/{doc_id}").json()
            print(f"   {time.time() - started:5.1f}s  {doc['status']}")
            if doc["status"] in ("ready", "failed"):
                break
            time.sleep(1)
        if doc["status"] == "failed":
            sys.exit(f"   ingestion failed: {doc['error']}")
        print(f"   pages={doc['page_count']} chunks={doc['chunk_count']}")

        print("5) Start a conversation (the server keeps its history)")
        cid = api.post("/v1/conversations", json={"title": args.question[:60]}).json()[
            "conversation_id"
        ]
        print(f"   conversation_id={cid}")

        print("6) Ask the question (JSON)")
        r = api.post("/v1/query", json={"question": args.question, "conversation_id": cid})
        if r.status_code != 200:
            sys.exit(f"   failed: {r.status_code} {r.text}")
        body = r.json()
        print(f"   answer: {body['answer']}")
        for c in body["citations"]:
            print(f"   [{c['source_id']}] {c['filename']} p.{c['page']}  {c['snippet'][:70]!r}")
        bars(body["context"], body["account"])

        follow_up = "Can you say that more briefly?"
        print(f"7) Follow-up in the same conversation, streamed: {follow_up!r}")
        with api.stream(
            "POST", "/v1/query/stream", json={"question": follow_up, "conversation_id": cid}
        ) as s:
            event = ""
            for line in s.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: "):
                    payload = json.loads(line[6:])
                    if event == "token":
                        print(payload["text"], end="", flush=True)
                    elif event == "sources":
                        print(f"   (sources arrived first: {len(payload)} citations)\n   ", end="")
                    elif event == "done":
                        print()
                        bars(payload["context"], payload["account"])
                    elif event == "error":
                        print(f"\n   error: {payload}")

        print("8) GET /v1/usage (what the frontend polls for the two bars)")
        usage = api.get("/v1/usage", params={"conversation_id": cid}).json()
        bars(usage["context"], usage["account"])

        if args.delete:
            print("9) Clean up")
            print(f"   delete document -> {api.delete(f'/v1/documents/{doc_id}').status_code}")
            print(f"   delete conversation -> {api.delete(f'/v1/conversations/{cid}').status_code}")


if __name__ == "__main__":
    main()
