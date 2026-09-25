"""Optional single-process Gradio demo on top of the same service layer as the API.

Every browser session gets its own user id, so visitors can't see each other's documents (the
original app shared one global collection). Data lives in memory and is lost on restart.

    pip install -e "backend[demo]"
    python demos/gradio_app.py
"""

import asyncio
import uuid
from pathlib import Path
from typing import Any

import gradio as gr
from documind.core.config import Backend, get_settings
from documind.core.container import build_container
from documind.core.errors import DocumindError
from documind.domain import Message

settings = get_settings().model_copy(update={"backend": Backend.MEMORY})
container = build_container(settings)

CSS = """
#header { text-align: center; padding: 16px; }
footer { display: none !important; }
"""


async def upload(file_path: str | None, user_id: str) -> str:
    if not file_path:
        return "⚠️ Choose a PDF first."
    path = Path(file_path)
    try:
        data = await asyncio.to_thread(path.read_bytes)
        doc = await container.ingestion_service.ingest_bytes(user_id, path.name, data)
    except DocumindError as exc:
        return f"❌ {exc.message}"
    return f"✅ {doc.filename}: {doc.page_count} pages, {doc.chunk_count} chunks indexed."


async def chat(
    message: str, history: list[dict[str, Any]], user_id: str
) -> tuple[str, list[dict[str, Any]]]:
    if not message.strip():
        return "", history
    turns = [
        Message(t["role"], str(t["content"]))
        for t in history
        if t.get("role") in ("user", "assistant")
    ]
    try:
        answer = await container.query_service.answer(user_id, message, turns)
        reply = answer.text
        if answer.citations:
            sources = ", ".join(
                f"[{c.source_id}] {c.filename} p.{c.page}" for c in answer.citations
            )
            reply += f"\n\n*Sources: {sources}*"
    except DocumindError as exc:
        reply = f"⚠️ {exc.message}"
    return "", [
        *history,
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]


with gr.Blocks(title="DocuMind AI") as demo:
    user_id = gr.State("")
    demo.load(lambda: uuid.uuid4().hex, None, user_id)  # one isolated tenant per session

    with gr.Column(elem_id="header"):
        gr.Markdown("# 🧠 DocuMind AI\n### Ask questions about your PDFs, with page citations")

    with gr.Row():
        with gr.Column(scale=1):
            file = gr.File(label="Upload PDF", file_types=[".pdf"], type="filepath")
            build = gr.Button("Build knowledge base", variant="primary")
            status = gr.Textbox(
                label="Status", placeholder="Awaiting document...", interactive=False
            )
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(label="Conversation", height=500)
            with gr.Row():
                question = gr.Textbox(
                    show_label=False, placeholder="Ask a question and press Enter...", scale=4
                )
                send = gr.Button("Send", variant="primary", scale=1)
            clear = gr.Button("🗑️ Clear chat")

    build.click(upload, [file, user_id], status)
    question.submit(chat, [question, chatbot, user_id], [question, chatbot])
    send.click(chat, [question, chatbot, user_id], [question, chatbot])
    clear.click(lambda: [], None, chatbot, queue=False)

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft(), css=CSS)
