from typing import List, Dict, Any, Optional, Tuple, Union
import chromadb
from chromadb.config import Settings
from embedding_generator import CodeEmbedding
import os
import numpy as np
import json
import logging
from tqdm import tqdm
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('VectorStore')

class VectorStore:
    """
    Enhanced vector store for SAS code embeddings with improved search capabilities
    and more detailed metadata handling.
    """
    
    def __init__(
        self, 
        persist_directory: str = "chroma_db",
        collection_prefix: str = "sas_",
        create_collections: bool = True
    ):
        """
        Initialize the vector store.
        
        Args:
            persist_directory: Directory to persist ChromaDB data
            collection_prefix: Prefix for collection names
            create_collections: Whether to create default collections
        """
        # Initialize ChromaDB client
        self.client = chromadb.Client(Settings(
            persist_directory=persist_directory,
            anonymized_telemetry=False
        ))
        
        self.collection_prefix = collection_prefix
        
        # Create collections with more meaningful names
        self.collections = {}
        
        if create_collections:
            self._create_default_collections()
            
        # Track metrics
        self.metrics = {
            "embeddings_stored": 0,
            "search_count": 0,
            "average_search_time": 0
        }
    
    def _create_default_collections(self):
        """Create default collections for SAS components."""
        collection_names = [
            "procedures",  # For all PROC statements
            "data_steps",  # For all DATA steps
            "macros",      # For SAS macros
            "sql",         # For SQL procedures
            "files",       # For file-level embeddings
            "other"        # For other components
        ]
        
        for name in collection_names:
            collection_name = f"{self.collection_prefix}{name}"
            self.collections[name] = self.client.get_or_create_collection(
                name=collection_name,
                metadata={"description": f"SAS {name} components"}
            )
            
        logger.info(f"Created/loaded {len(self.collections)} collections")
    
    def get_or_create_collection(self, collection_name: str, description: str = "") -> chromadb.Collection:
        """Get or create a collection with the given name."""
        prefixed_name = f"{self.collection_prefix}{collection_name}"
        collection = self.client.get_or_create_collection(
            name=prefixed_name,
            metadata={"description": description}
        )
        self.collections[collection_name] = collection
        return collection
    
    def get_collection_names(self) -> List[str]:
        """Get all collection names."""
        return list(self.collections.keys())
    
    def get_collection_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for each collection."""
        stats = {}
        for name, collection in self.collections.items():
            try:
                count = collection.count()
                stats[name] = {
                    "count": count,
                    "name": f"{self.collection_prefix}{name}"
                }
            except Exception as e:
                logger.error(f"Error getting stats for collection {name}: {str(e)}")
                stats[name] = {"error": str(e)}
                
        return stats
    
    def _get_collection_for_component(self, component_type: str) -> chromadb.Collection:
        """Get the appropriate collection based on component type."""
        component_type = component_type.upper() if isinstance(component_type, str) else "OTHER"
        
        if component_type == "FILE":
            return self.collections["files"]
        elif component_type == "PROC" or component_type.startswith("PROC_"):
            if component_type == "PROC_SQL":
                return self.collections["sql"]
            else:
                return self.collections["procedures"]
        elif component_type == "DATA":
            return self.collections["data_steps"]
        elif component_type == "MACRO":
            return self.collections["macros"]
        else:
            return self.collections["other"]
    
    def store_embeddings(self, embeddings: List[CodeEmbedding], batch_size: int = 100):
        """
        Store embeddings in appropriate collections with improved batching and error handling.
        
        Args:
            embeddings: List of CodeEmbedding objects
            batch_size: Number of embeddings to process in each batch
        """
        # Group embeddings by collection
        collection_groups: Dict[str, List[CodeEmbedding]] = {}
        
        for emb in embeddings:
            component_type = emb.component.type
            collection_name = self._get_collection_key_for_type(component_type)
            
            if collection_name not in collection_groups:
                collection_groups[collection_name] = []
                
            collection_groups[collection_name].append(emb)
            
        # Store embeddings in batches for each collection
        total_stored = 0
        
        for collection_name, group_embeddings in collection_groups.items():
            collection = self._get_collection_for_component(collection_name)
            
            # Process in batches
            for i in range(0, len(group_embeddings), batch_size):
                batch = group_embeddings[i:i+batch_size]
                
                # Prepare batch data
                ids = []
                embeddings_list = []
                metadatas = []
                documents = []
                
                for emb in batch:
                    # Create a unique ID based on file path and component details
                    component_id = self._create_component_id(emb)
                    
                    # Convert embedding to list for storage
                    embedding_list = emb.embedding.tolist() if isinstance(emb.embedding, np.ndarray) else emb.embedding
                    
                    # Ensure metadata is serializable (no nested objects)
                    metadata = self._prepare_metadata_for_storage(emb.metadata)
                    
                    # Get component content
                    content = emb.component.content if hasattr(emb.component, 'content') else ""
                    
                    ids.append(component_id)
                    embeddings_list.append(embedding_list)
                    metadatas.append(metadata)
                    documents.append(content)
                
                try:
                    # Add embeddings to collection
                    collection.add(
                        ids=ids,
                        embeddings=embeddings_list,
                        metadatas=metadatas,
                        documents=documents
                    )
                    total_stored += len(batch)
                    logger.info(f"Stored {len(batch)} embeddings in {collection_name} collection")
                except Exception as e:
                    logger.error(f"Error storing embeddings in {collection_name}: {str(e)}")
                    # Try to add one by one to identify problematic embeddings
                    for j, emb in enumerate(batch):
                        try:
                            component_id = self._create_component_id(emb)
                            embedding_list = emb.embedding.tolist() if isinstance(emb.embedding, np.ndarray) else emb.embedding
                            metadata = self._prepare_metadata_for_storage(emb.metadata)
                            content = emb.component.content if hasattr(emb.component, 'content') else ""
                            
                            collection.add(
                                ids=[component_id],
                                embeddings=[embedding_list],
                                metadatas=[metadata],
                                documents=[content]
                            )
                            total_stored += 1
                        except Exception as sub_e:
                            logger.error(f"Error storing individual embedding {j}: {str(sub_e)}")
        
        self.metrics["embeddings_stored"] += total_stored
        logger.info(f"Total embeddings stored: {total_stored}")
    
    def _get_collection_key_for_type(self, component_type: str) -> str:
        """Get the collection key for a component type."""
        component_type = component_type.upper() if isinstance(component_type, str) else "OTHER"
        
        if component_type == "FILE":
            return "FILE"
        elif component_type == "PROC" or component_type.startswith("PROC_"):
            if component_type == "PROC_SQL":
                return "PROC_SQL"
            else:
                return "PROC"
        elif component_type == "DATA":
            return "DATA"
        elif component_type == "MACRO":
            return "MACRO"
        else:
            return "OTHER"
    
    def _create_component_id(self, embedding: CodeEmbedding) -> str:
        """Create a unique ID for a component embedding."""
        component = embedding.component
        file_path = embedding.metadata.get("file_path", "unknown")
        file_name = os.path.basename(file_path)
        
        if component.type == "FILE":
            return f"file_{file_name.replace('.', '_')}"
        else:
            return f"{component.type}_{component.name}_{file_name}_{component.line_start}_{component.line_end}"
    
    def _prepare_metadata_for_storage(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare metadata for storage in ChromaDB by ensuring all values are serializable.
        
        Args:
            metadata: The metadata dictionary to prepare
            
        Returns:
            A serializable metadata dictionary
        """
        prepared_metadata = {}
        
        for key, value in metadata.items():
            # Handle lists
            if isinstance(value, list):
                # Convert list to string for storage
                prepared_metadata[key] = json.dumps(value)
            # Handle dictionaries
            elif isinstance(value, dict):
                # Convert dict to string for storage
                prepared_metadata[key] = json.dumps(value)
            # Handle other non-primitive types
            elif not isinstance(value, (str, int, float, bool, type(None))):
                # Convert to string
                prepared_metadata[key] = str(value)
            else:
                # Primitive types can be stored as-is
                prepared_metadata[key] = value
                
        return prepared_metadata
    
    def search_similar_code(
    self, 
    query_text: str,
    query_embedding: Optional[List[float]] = None,  # Add this parameter
    n_results: int = 5,
    collection_names: Optional[List[str]] = None,
    metadata_filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Search for similar code across specified collections.
        
        Args:
            query_text: The text to search for
            query_embedding: Optional pre-generated embedding to use directly
            n_results: Number of results to return per collection
            collection_names: List of collection names to search, or None for all
            metadata_filters: Metadata filters to apply
            
        Returns:
            Dictionary with search results per collection
        """
        start_time = time.time()
        results = {}
        
        # Determine which collections to search
        if collection_names is None:
            search_collections = list(self.collections.keys())
        else:
            search_collections = [name for name in collection_names if name in self.collections]
                
        if not search_collections:
            logger.warning("No valid collections specified for search")
            return {"error": "No valid collections specified"}
                
        # Apply metadata filters if provided
        where_clause = None
        if metadata_filters:
            where_clause = self._build_where_clause(metadata_filters)
                
        # Search in each collection
        for collection_name in search_collections:
            try:
                collection = self.collections[collection_name]
                
                # Use pre-generated embedding if provided
                if query_embedding is not None:
                    query_results = collection.query(
                        query_embeddings=[query_embedding],
                        n_results=n_results,
                        where=where_clause,
                        include=["metadatas", "documents", "distances"]
                    )
                else:
                    query_results = collection.query(
                        query_texts=[query_text],
                        n_results=n_results,
                        where=where_clause,
                        include=["metadatas", "documents", "distances"]
                    )
                
                # Process query results
                results[collection_name] = {
                    "documents": query_results.get("documents", [[]])[0],
                    "metadatas": self._process_returned_metadatas(query_results.get("metadatas", [[]])[0]),
                    "distances": query_results.get("distances", [[]])[0]
                }
                
                # Add score (inverse of distance) for easier interpretation
                if "distances" in query_results and query_results["distances"]:
                    distances = query_results["distances"][0]
                    results[collection_name]["scores"] = [1.0 - min(d, 1.0) for d in distances]
                        
            except Exception as e:
                logger.error(f"Error searching in collection {collection_name}: {str(e)}")
                results[collection_name] = {"error": str(e)}
        
        # Rest of the method remains the same...
                
        # Compile summary of all results
        all_results = []
        for collection_name, collection_results in results.items():
            if "metadatas" in collection_results and "distances" in collection_results:
                metadatas = collection_results["metadatas"]
                distances = collection_results["distances"]
                documents = collection_results["documents"]
                
                for i in range(len(metadatas)):
                    if i < len(distances) and i < len(documents):
                        result_item = {
                            "collection": collection_name,
                            "metadata": metadatas[i],
                            "distance": distances[i],
                            "score": 1.0 - min(distances[i], 1.0),
                            "content_preview": documents[i][:300] + "..." if len(documents[i]) > 300 else documents[i]
                        }
                        all_results.append(result_item)
        
        # Sort combined results by score
        all_results.sort(key=lambda x: x["score"], reverse=True)
        
        # Add combined results to the output
        results["combined"] = {
            "results": all_results[:n_results]  # Top N results across all collections
        }
        
        # Update metrics
        self.metrics["search_count"] += 1
        search_time = time.time() - start_time
        self.metrics["average_search_time"] = (
            (self.metrics["average_search_time"] * (self.metrics["search_count"] - 1) + search_time) / 
            self.metrics["search_count"]
        )
        
        # Add execution metadata
        results["_execution_metadata"] = {
            "search_time_seconds": search_time,
            "collections_searched": search_collections,
            "query_text": query_text,
            "metadata_filters": metadata_filters
        }
        
        return results
    
    def _process_returned_metadatas(self, metadatas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process returned metadatas to convert stored JSON strings back to Python objects.
        
        Args:
            metadatas: List of metadata dictionaries from ChromaDB
            
        Returns:
            List of processed metadata dictionaries
        """
        processed_metadatas = []
        
        for metadata in metadatas:
            processed_metadata = {}
            
            for key, value in metadata.items():
                # Try to detect and parse JSON strings
                if isinstance(value, str) and (value.startswith('[') or value.startswith('{')):
                    try:
                        processed_metadata[key] = json.loads(value)
                    except json.JSONDecodeError:
                        # Not valid JSON, keep as string
                        processed_metadata[key] = value
                else:
                    processed_metadata[key] = value
                    
            processed_metadatas.append(processed_metadata)
            
        return processed_metadatas
    
    def _build_where_clause(self, metadata_filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a where clause for filtering based on metadata.
        
        Args:
            metadata_filters: Dictionary with metadata filters
            
        Returns:
            Where clause dictionary for ChromaDB
        """
        where_clause = {}
        
        for key, value in metadata_filters.items():
            # Handle different value types
            if isinstance(value, list):
                # For lists, create an '$in' operator
                where_clause[key] = {"$in": value}
            elif isinstance(value, dict) and all(k.startswith('$') for k in value.keys()):
                # Already a query operator, use as-is
                where_clause[key] = value
            else:
                # Simple equality check
                where_clause[key] = value
                
        return where_clause
    
    def search_by_component_type(
        self, 
        query_text: str, 
        component_type: str, 
        n_results: int = 5
    ) -> Dict[str, Any]:
        """
        Search for similar code of a specific component type.
        
        Args:
            query_text: The text to search for
            component_type: Type of component to search for
            n_results: Number of results to return
            
        Returns:
            Dictionary with search results
        """
        # Map component type to collection
        collection_name = self._get_collection_key_for_type(component_type)
        collection_key = self._get_collection_key_for_type(collection_name)
        
        # Define metadata filter
        metadata_filter = {"type": component_type}
        
        # Perform search
        return self.search_similar_code(
            query_text=query_text,
            n_results=n_results,
            collection_names=[collection_key],
            metadata_filters=metadata_filter
        )
    
    def search_by_file_path(
        self, 
        query_text: str, 
        file_path_pattern: str, 
        n_results: int = 5
    ) -> Dict[str, Any]:
        """
        Search for similar code in files matching a pattern.
        
        Args:
            query_text: The text to search for
            file_path_pattern: Pattern to match file paths
            n_results: Number of results to return
            
        Returns:
            Dictionary with search results
        """
        # ChromaDB doesn't support regex in where clauses directly,
        # so we'll need to use a post-processing approach
        
        # First, get more results than requested
        results = self.search_similar_code(
            query_text=query_text,
            n_results=n_results * 5  # Get extra results for filtering
        )
        
        # Filter results by file path pattern
        filtered_results = {}
        
        for collection_name, collection_results in results.items():
            if collection_name == "_execution_metadata" or collection_name == "combined":
                continue
                
            filtered_metadatas = []
            filtered_documents = []
            filtered_distances = []
            
            if "metadatas" in collection_results and "distances" in collection_results:
                metadatas = collection_results["metadatas"]
                distances = collection_results["distances"]
                documents = collection_results["documents"]
                
                for i in range(len(metadatas)):
                    if i < len(distances) and i < len(documents):
                        metadata = metadatas[i]
                        file_path = metadata.get("file_path", "")
                        
                        if file_path_pattern in file_path:
                            filtered_metadatas.append(metadata)
                            filtered_documents.append(documents[i])
                            filtered_distances.append(distances[i])
                            
                            if len(filtered_metadatas) >= n_results:
                                break
                                
            filtered_results[collection_name] = {
                "metadatas": filtered_metadatas[:n_results],
                "documents": filtered_documents[:n_results],
                "distances": filtered_distances[:n_results]
            }
            
        return filtered_results
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get metrics about the vector store."""
        collection_stats = self.get_collection_stats()
        
        return {
            "embeddings_stored": self.metrics["embeddings_stored"],
            "search_count": self.metrics["search_count"],
            "average_search_time": self.metrics["average_search_time"],
            "collections": collection_stats
        }
    
    def search_with_embedding(
    self, 
    query_embedding: List[float],
    n_results: int = 5,
    collection_names: Optional[List[str]] = None,
    metadata_filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Search for similar code using a pre-generated embedding vector.
        
        Args:
            query_embedding: The pre-generated embedding vector
            n_results: Number of results to return per collection
            collection_names: List of collection names to search, or None for all
            metadata_filters: Metadata filters to apply
            
        Returns:
            Dictionary with search results per collection
        """
        start_time = time.time()
        results = {}
        
        # Determine which collections to search
        if collection_names is None:
            search_collections = list(self.collections.keys())
        else:
            search_collections = [name for name in collection_names if name in self.collections]
                
        if not search_collections:
            logger.warning("No valid collections specified for search")
            return {"error": "No valid collections specified"}
                
        # Apply metadata filters if provided
        where_clause = None
        if metadata_filters:
            where_clause = self._build_where_clause(metadata_filters)
                
        # Search in each collection
        for collection_name in search_collections:
            try:
                collection = self.collections[collection_name]
                
                query_results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results,
                    where=where_clause,
                    include=["metadatas", "documents", "distances"]
                )
                
                # Process query results
                results[collection_name] = {
                    "documents": query_results.get("documents", [[]])[0],
                    "metadatas": self._process_returned_metadatas(query_results.get("metadatas", [[]])[0]),
                    "distances": query_results.get("distances", [[]])[0] if "distances" in query_results else []
                }
                    
            except Exception as e:
                logger.error(f"Error searching in collection {collection_name}: {str(e)}")
                results[collection_name] = {"error": str(e)}
                    
        # Update metrics
        elapsed_time = time.time() - start_time
        results["_execution_metadata"] = {
            "search_time_seconds": elapsed_time,
            "collections_searched": search_collections
        }
        
        return results