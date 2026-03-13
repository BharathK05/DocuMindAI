---
title: DocuMind AI
emoji: 🧠
colorFrom: blue
colorTo: indigo
sdk: gradio
app_file: app.py
pinned: false
---

# 🧠 DocuMind AI
**Enterprise-Grade Retrieval-Augmented Generation (RAG) System**

[![Hugging Face Space](https://img.shields.io/badge/🤗%20Hugging%20Face-Live%20Demo-blue)](https://huggingface.co/spaces/Bhrthx/DocuMindAI)

DocuMind AI is a production-ready document intelligence platform. It allows users to upload complex PDF documents and "interrogate" them using a conversational interface. By combining Google's latest Gemini models with vector search, it guarantees answers are strictly grounded in the uploaded context, eliminating AI hallucinations.

## 🚀 Live Demo
**Try the application here:** [DocuMind AI on Hugging Face](https://huggingface.co/spaces/Bhrthx/DocuMindAI)

## 🛠️ Tech Stack & Architecture
* **LLM Reasoning**: Google `gemini-2.5-flash` for high-speed, accurate context synthesis.
* **Embeddings**: Google `gemini-embedding-001` for high-dimensional vector representations.
* **Vector Database**: **ChromaDB** with persistent cloud storage for fast semantic retrieval.
* **Data Processing**: **LangChain** (`PyPDFLoader`, `RecursiveCharacterTextSplitter` with 500 chunk size and 75 overlap).
* **Frontend UI**: **Gradio** built with a custom professional dashboard layout.
* **DevOps**: Automated CI/CD pipeline via **GitHub Actions** deploying directly to Hugging Face Spaces.

## 💡 Key Features
* **Zero-Hallucination Guardrails**: The system prompt strictly forces the AI to output "I Don't Know" if the user's query cannot be answered using the provided document.
* **Hybrid Contextual Awareness**: Retains conversational chat history so users can ask follow-up questions seamlessly.
* **Dynamic Indexing**: Wipes old database collections securely before embedding new documents to prevent cross-document contamination.

---