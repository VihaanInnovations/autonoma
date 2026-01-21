import os
import chromadb
from chromadb.config import Settings
import glob
from pathlib import Path
import re
import hashlib

class RAGEngine:
    def __init__(self, persistence_path="rag_db"):
        """
        Initialize ChromaDB client with local persistence.
        """
        self.client = chromadb.PersistentClient(path=persistence_path)
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name="code_context",
            metadata={"hnsw:space": "cosine"}
        )

    def _chunk_code(self, content: str, file_path: str):
        """
        Simple heuristic chunking: Split by functions or classes.
        Fallback to fixed size if no structure found.
        """
        chunks = []
        lines = content.split('\n')
        current_chunk = []
        current_id = f"{file_path}:start"
        
        # Regex for python def/class
        # This is a naive implementation for MVP. 
        # Production should use TreeSitter.
        pattern = re.compile(r'^\s*(def|class)\s+(\w+)')
        
        for i, line in enumerate(lines):
            match = pattern.match(line)
            if match:
                # Save previous chunk if valid
                if current_chunk:
                    text = "\n".join(current_chunk)
                    if len(text.strip()) > 50: # Ignore tiny chunks
                        chunks.append({
                            "id": hashlib.md5((current_id + text).encode()).hexdigest(),
                            "text": text,
                            "metadata": {"source": file_path, "type": "code"}
                        })
                
                # Start new chunk
                current_chunk = [line]
                current_id = f"{file_path}:{match.group(2)}"
            else:
                current_chunk.append(line)
                
        # Last chunk
        if current_chunk:
            text = "\n".join(current_chunk)
            if len(text.strip()) > 50:
                chunks.append({
                    "id": hashlib.md5((current_id + text).encode()).hexdigest(),
                    "text": text,
                    "metadata": {"source": file_path, "type": "code"}
                })
        
        return chunks

    def index_codebase(self, root_path: str):
        """
        Recursively index supported files in root_path.
        """
        root = Path(root_path)
        extensions = ['*.py', '*.ts', '*.js', '*.java', '*.go']
        files = []
        for ext in extensions:
            files.extend(root.rglob(ext))

        print(f"Indexing {len(files)} files from {root_path}...")
        
        ids = []
        documents = []
        metadatas = []

        for file_path in files:
            # Skip hidden dirs or venv
            if ".venv" in str(file_path) or "node_modules" in str(file_path):
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                chunks = self._chunk_code(content, str(file_path))
                for chunk in chunks:
                    ids.append(chunk['id'])
                    documents.append(chunk['text'])
                    metadatas.append(chunk['metadata'])
            except Exception as e:
                print(f"Failed to index {file_path}: {e}")

        # Batch upsert
        if ids:
            # Chroma works best with batches < 5000 approx
            batch_size = 100
            for i in range(0, len(ids), batch_size):
                end = min(i + batch_size, len(ids))
                self.collection.upsert(
                    ids=ids[i:end],
                    documents=documents[i:end],
                    metadatas=metadatas[i:end]
                )
        print(f"Indexed {len(ids)} chunks.")

    def query_context(self, query_text: str, n_results=3):
        """
        Retrieve relevant context for a query.
        """
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        
        # Flatten results
        context_snippets = []
        if results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i]
                source = meta.get('source', 'unknown')
                context_snippets.append(f"--- Context (from {source}) ---\n{doc}\n")
                
        return "\n".join(context_snippets)

if __name__ == "__main__":
    # Test run
    rag = RAGEngine()
    rag.index_codebase(".")
    results = rag.query_context("How does the circuit breaker work?")
    print("\nSearch Results:")
    print(results)
