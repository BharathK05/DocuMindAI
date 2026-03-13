import os
from dotenv import load_dotenv
import google as genai
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb

# Load the API key from the .env file
load_dotenv()

class RAGEngine:
    def __init__(self):
        # Initialize Gemini Client
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        
        # Initialize Persistent ChromaDB
        self.chroma_client = chromadb.PersistentClient(path="./chroma_db")
        self.collection = self.chroma_client.get_or_create_collection(name="docu_mind_collection")
        
        # Text Splitter based on your original code
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=75
        )

    def get_embedding(self, text):
        result = self.client.models.embed_content(
            model="gemini-embedding-001",
            contents=text
        )
        return result.embeddings[0].values

    def process_document(self, file_path):
        try:
            loader = PyPDFLoader(file_path)
            documents = loader.load()
            
            chunks = self.splitter.split_documents(documents)
            texts = [c.page_content for c in chunks]
            
            embeddings = [self.get_embedding(t) for t in texts]
            ids = [str(i) for i in range(len(texts))]
            
            # --- THE FIX IS HERE ---
            # Get existing document IDs and delete them properly
            existing_data = self.collection.get()
            if existing_data["ids"]:
                self.collection.delete(ids=existing_data["ids"])
            # -----------------------
                
            self.collection.add(
                documents=texts,
                embeddings=embeddings,
                ids=ids
            )
            return f"✅ Success: {len(texts)} chunks indexed."
        except Exception as e:
            return f"❌ Error: {str(e)}"

    def get_response(self, user_query, chat_history):
        try:
            query_embedding = self.get_embedding(user_query)
            
            # Retrieve top 5 chunks
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=5
            )

            top_chunks = results["documents"][0][:5]
            context = "\n\n".join(top_chunks)
            
            # System prompt based on your original notebook
            system_prompt = f"""
            You are DocuMind AI, a professional document assistant.
            Answer ONLY using the context below.
            If the answer is not present, say "I Dont Know", do not hallucinate,

            Context:
            {context}

            User Query:
            {user_query}

            Give the answer is a presentable manner to the user, dont just give the answer.
            Also understand the question as a human and answer accordingly, if the question is vague, ask for clarification and 
            if needs a one word answer, give a one word answer, if needs a detailed answer, give a detailed answer.
            """

            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=system_prompt,
            )
            
            return response.text
        except Exception as e:
            return f"I encountered an error: {str(e)}"