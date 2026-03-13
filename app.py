import gradio as gr
from engine import RAGEngine

# Initialize the backend logic
engine = RAGEngine()

# 1. FIXED HEADER CSS: Removed the hardcoded background color so it adapts to dark/light mode
custom_css = """
#main-header { text-align: center; margin-bottom: 20px; padding: 20px; }
.message { border-radius: 12px !important; }
footer { display: none !important; } /* Hides the default Gradio watermark footer */
"""

def chat_interface(message, history):
    if not message:
        return "", history
    
    response = engine.get_response(message, history)
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": response})
    
    return "", history

def upload_file(file):
    if file is None:
        return "⚠️ No file uploaded."
    status_msg = engine.process_document(file.name)
    return status_msg

# 2. FIXED TAB NAME: Added title="DocuMind AI" to change the browser tab text
with gr.Blocks(title="DocuMind AI") as demo:
    with gr.Column(elem_id="main-header"):
        gr.Markdown("# 🧠 DocuMind AI")
        gr.Markdown("### *Enterprise-grade Retrieval-Augmented Generation*")

    with gr.Row():
        # Left Column: Document Management
        with gr.Column(scale=1):
            gr.Markdown("#### 📂 Knowledge Base")
            file_upload = gr.File(
                label="Upload PDF Document",
                file_types=[".pdf"],
                type="filepath"
            )
            upload_button = gr.Button("Build Knowledge Base", variant="primary")
            system_status = gr.Textbox(
                label="System Status", 
                placeholder="Awaiting document...", 
                interactive=False
            )
            
            gr.Markdown("---")
            gr.Markdown(
                "**How it works:**\n"
                "1. Upload a technical document or resume.\n"
                "2. The engine fragments and embeds the data.\n"
                "3. Ask specific questions in the chat."
            )

        # Right Column: The Chat Experience
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(
                label="Conversation",
                height=500
            ) 
            
            with gr.Row():
                user_input = gr.Textbox(
                    show_label=False,
                    placeholder="Type your question here and press Enter...",
                    scale=4
                )
                submit_btn = gr.Button("Send", variant="primary", scale=1)

            clear_btn = gr.Button("🗑️ Clear Chat History")

    # 3. ADDED FOOTER: Professional centered footer with hyperlinks
    gr.Markdown("---")
    gr.HTML(
        """
        <div style="text-align: center; padding: 10px;">
            <p>Built by <b>Bharath</b> | 
            <a href="https://github.com/BharathK05" target="_blank" style="text-decoration: none; color: #4F46E5;">GitHub</a> • 
            <a href="https://www.linkedin.com/in/bharathk0611/" target="_blank" style="text-decoration: none; color: #4F46E5;">LinkedIn</a></p>
        </div>
        """
    )

    # Event Listeners
    upload_button.click(fn=upload_file, inputs=[file_upload], outputs=[system_status])
    user_input.submit(fn=chat_interface, inputs=[user_input, chatbot], outputs=[user_input, chatbot])
    submit_btn.click(fn=chat_interface, inputs=[user_input, chatbot], outputs=[user_input, chatbot])
    clear_btn.click(lambda: [], None, chatbot, queue=False)

if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(), 
        css=custom_css, 
        debug=True
    )