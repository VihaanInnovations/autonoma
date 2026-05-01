import chromadb
from chromadb.config import Settings
from pathlib import Path
from typing import List, Dict, Any

class RAGEngine:
    def __init__(self):
        # Database path: daemon/db/chroma_db
        self.db_path = Path(__file__).parent.parent / "db" / "chroma_db"
        
        # Ensure the directory exists (Chroma might create it, but being safe)
        self.db_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize Persistent Client
        self.client = chromadb.PersistentClient(path=str(self.db_path))
        
        # Get or create collection
        # Uses default embedding function (all-MiniLM-L6-v2) automatically
        self.collection = self.client.get_or_create_collection(name="code_chunks")
        
    def add_document(self, path: str, content: str):
        """
        Chunk content and add to vector DB.
        UPSERT behavior: overwrites if ID exists.
        """
        # 1. Chunking
        chunk_size = 1000
        chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
        
        if not chunks:
            return

        # 2. Prepare Data
        ids = [f"{path}_{i}" for i in range(len(chunks))]
        metadatas = [{"path": path, "chunk_index": i} for i in range(len(chunks))]
        
        # 3. Upsert into Chroma (Computing embeddings happens internally)
        self.collection.upsert(
            documents=chunks,
            ids=ids,
            metadatas=metadatas
        )
        
    def retrieve(self, query: str, k: int = 3) -> List[Dict[str, Any]]:
        """
        Query the vector DB for relevant code chunks.
        """
        results = self.collection.query(
            query_texts=[query],
            n_results=k
        )
        
        formatted_results = []
        
        # results structure is {ids: [[...]], distances: [[...]], metadatas: [[...]], documents: [[...]]}
        if results.get("documents"):
            # Iterate over the first query's results
            for i in range(len(results["documents"][0])):
                doc = results["documents"][0][i]
                metadata = results["metadatas"][0][i]
                distance = results["distances"][0][i] if results["distances"] else 0
                
                formatted_results.append({
                    "path": metadata["path"],
                    "content": doc,
                    "score": 1.0 - distance # Chroma returns distance, RAG expected score (simulated)
                })
                
                
        return formatted_results

    def query_context(self, query: str, k: int = 3) -> List[Dict[str, Any]]:
        """Alias for retrieve to match AnalysisQueue usage"""
        return self.retrieve(query, k)
