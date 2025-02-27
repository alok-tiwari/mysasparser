from typing import List, Dict, Any
import chromadb
from chromadb.config import Settings
from embedding_generator import CodeEmbedding
import os
import numpy as np

class VectorStore:
    def __init__(self, persist_directory: str = "chroma_db"):
        self.client = chromadb.Client(Settings(
            persist_directory=persist_directory,
            anonymized_telemetry=False
        ))
        
        # Create collections with more meaningful names
        self.collections = {
            "sas_procedures": self.client.get_or_create_collection("sas_procedures"),
            "data_steps": self.client.get_or_create_collection("data_steps"),
            "sas_macros": self.client.get_or_create_collection("sas_macros"),
            "other_components": self.client.get_or_create_collection("other_components")
        }
        
        # Create a collection for file-level embeddings
        self.file_collection = self.client.get_or_create_collection("sas_files")
    
    def store_embeddings(self, embeddings: List[CodeEmbedding]):
        """Store embeddings in appropriate collections based on their type."""
        # Group embeddings by file
        file_groups: Dict[str, List[CodeEmbedding]] = {}
        
        for emb in embeddings:
            file_path = emb.metadata["file_path"]
            if file_path not in file_groups:
                file_groups[file_path] = []
            file_groups[file_path].append(emb)
            
            # Store in component-specific collection
            collection = self._get_collection_for_type(emb.component.type)
            
            # Create a unique ID that includes file path and location
            component_id = f"{emb.metadata['file_path']}_{emb.component.type}_{emb.component.line_start}"
            
            # Store the embedding with metadata
            collection.add(
                embeddings=[emb.embedding.tolist()],
                metadatas=[emb.metadata],
                documents=[emb.component.content],
                ids=[component_id]
            )
        
        # Store file-level embeddings
        for file_path, file_embeddings in file_groups.items():
            # Combine all component contents
            combined_content = "\n".join(emb.component.content for emb in file_embeddings)
            
            # Calculate file-level metadata
            file_metadata = {
                "file_path": file_path,
                "component_count": len(file_embeddings),
                "component_types": ",".join(sorted(set(emb.component.type for emb in file_embeddings))),  # Convert list to string
                "line_count": max(emb.component.line_end for emb in file_embeddings)
            }
            
            # Use average of all embeddings as file-level embedding
            file_embedding = np.mean([emb.embedding for emb in file_embeddings], axis=0).tolist()
            
            # Store in file collection
            self.file_collection.add(
                embeddings=[file_embedding],
                metadatas=[file_metadata],
                documents=[combined_content],
                ids=[file_path]
            )
    
    def _get_collection_for_type(self, component_type: str) -> chromadb.Collection:
        """Get the appropriate collection based on component type."""
        if component_type == "PROC":
            return self.collections["sas_procedures"]
        elif component_type == "DATA":
            return self.collections["data_steps"]
        elif component_type == "MACRO":
            return self.collections["sas_macros"]
        else:
            return self.collections["other_components"]
    
    def search_similar_code(self, query_text: str, n_results: int = 5) -> Dict[str, Any]:
        """Search for similar code across all collections."""
        results = {}
        
        # Search in each collection
        for collection_name, collection in self.collections.items():
            query_results = collection.query(
                query_texts=[query_text],
                n_results=n_results,
                include=["metadatas", "documents", "distances"]
            )
            results[collection_name] = {
                "documents": query_results["documents"][0],
                "metadatas": query_results["metadatas"][0],
                "distances": query_results["distances"][0]
            }
            
        # Also search in file collection
        file_results = self.file_collection.query(
            query_texts=[query_text],
            n_results=n_results,
            include=["metadatas", "documents", "distances"]
        )
        results["files"] = {
            "documents": file_results["documents"][0],
            "metadatas": file_results["metadatas"][0],
            "distances": file_results["distances"][0]
        }
        
        return results