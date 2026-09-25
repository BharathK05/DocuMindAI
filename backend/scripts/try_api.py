"""Walk through the whole API flow against a running server, printing each step.

    python backend/scripts/try_api.py path/to/file.pdf "Your question?"

Steps: register upload -> POST the file straight to S3 (presigned form) -> confirm ->
poll ingestion status -> ask (JSON) -> ask (streaming SSE) -> list. Pass --delete to clean up.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("question")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--delete", action="store_true", help="delete the document at the end")
    args = parser.parse_args()
    data = args.pdf.read_bytes()

    with httpx.Client(base_url=args.api, timeout=60) as api:
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

        print("5) Ask a question (JSON)")
        r = api.post("/v1/query", json={"question": args.question}).json()
        print(f"   answer: {r['answer']}")
        for c in r["citations"]:
            print(f"   [{c['source_id']}] {c['filename']} p.{c['page']}  {c['snippet'][:80]!r}")
        print(f"   usage: {r['usage']}")

        print("6) Ask again, streamed (Server-Sent Events)")
        with api.stream("POST", "/v1/query/stream", json={"question": args.question}) as s:
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
                    elif event in ("done", "error"):
                        print(f"\n   {event}: {payload}")

        print("7) Your documents")
        for d in api.get("/v1/documents").json()["documents"]:
            print(f"   {d['document_id']}  {d['status']:8} {d['filename']}")

        if args.delete:
            print(
                f"8) Delete -> {api.delete(f'/v1/documents/{doc_id}').status_code} (204 = deleted)"
            )


if __name__ == "__main__":
    main()
