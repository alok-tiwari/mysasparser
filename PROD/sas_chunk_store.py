from typing import List, Dict, Any
from prd_sas_parser import SASComponent
from lab_vector_store import LabVectorStore
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('SASChunkStore')

class SASChunkStore:
    """Prepares and stores SAS components in Lab Vector Store."""
    
    def __init__(self, collection_name: str = "sas-python-collection"):
        """
        Initialize connection to Lab Vector Store.
        
        Args:
            collection_name: Name of the collection to store components
        """
        self.collection_name = collection_name
        try:
            # Initialize Lab Vector Store with configuration
            self.store = LabVectorStore(
                api_key=os.getenv("LAB_VECTOR_STORE_API_KEY"),
                endpoint=os.getenv("LAB_VECTOR_STORE_ENDPOINT"),
                embedding_model=os.getenv("LAB_VECTOR_STORE_MODEL", "default")
            )
            logger.info(f"Successfully connected to Lab Vector Store")
        except Exception as e:
            logger.error(f"Failed to connect to Lab Vector Store: {str(e)}")
            raise

    def _prepare_and_store_chunks(self, components: List[SASComponent]) -> List[Document]:
        """Default chunking strategy for SAS components using RecursiveCharacterTextSplitter."""
        all_chunks = []
        for component in components:
            document = component.content
            
            # Safely get parent and nested info with defaults
            parent_info = component.metadata.get("parent_info", {
                "parent_name": None,
                "parent_type": None
            })
            nested_info = component.metadata.get("nested_info", {
                "has_nested": False,
                "nested_count": 0,
                "nested_names": []
            })

            file_path = component.metadata.get("file_path", "")
            file_name = os.path.basename(file_path) if file_path else "unknown"

            additional_metadata = {
                "type": component.type,
                "name": component.name,
                "line_start": component.line_start,
                "line_end": component.line_end,
                "file_path": file_path,
                "file_name": file_name,
                "parent_name": parent_info.get("parent_name"),  # Safe access
                "parent_type": parent_info.get("parent_type"),  # Safe access
                "has_nested": nested_info.get("has_nested", False),  # Safe access
                "nested_count": nested_info.get("nested_count", 0),  # Safe access
                "nested_names": nested_info.get("nested_names", [])  # Safe access
            }

            logger.info(f"Added metadata looks like: {additional_metadata}")
            chunks = load_and_split(document, additional_metadata)
            logger.info(f"Generated {len(chunks)} chunks for component: {component.name}")
            ids = self.vector_store.add_documents(documents=chunks)
            logger.info(f"Added document IDs to Risklab Vector Store: {ids}")

        return True

    def prepare_chunks(self, components: List[SASComponent]) -> List[Dict[str, Any]]:
        """Convert SAS components to chunks format for Lab Vector Store."""
        chunks = []
        for component in components:
            # Direct access to metadata - will work because parser guarantees structure
            chunk = {
                "content": component.content,
                "metadata": {
                    # Base metadata
                    "type": component.type,
                    "name": component.name,
                    "line_start": component.line_start,
                    "line_end": component.line_end,
                    "file_path": component.metadata["file_path"],
                    "source_file": component.metadata["source_file"],
                    
                    # Direct access to parent/nested info
                    "parent_info": component.metadata["parent_info"],
                    "nested_info": component.metadata["nested_info"],
                    
                    # Original indentation
                    "original_indentation": component.metadata["original_indentation"],
                    
                    # Include rest of metadata
                    **component.metadata
                }
            }
            chunks.append(chunk)
        
        return chunks

    def store_components(self, components: List[SASComponent]) -> bool:
        """
        Store SAS components in Lab Vector Store.
        
        Args:
            components: List of SASComponent objects
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not components:
                logger.warning("No components to store")
                return False
                
            # First try LabVectorStore's direct component storage if available
            if hasattr(self.store, 'store_components'):
                logger.info("Using LabVectorStore direct component storage")
                return self.store.store_components(components, self.collection_name)

            # Otherwise, use chunking and AddCollections
            chunks = self.prepare_chunks(components)
            logger.info(f"Prepared {len(chunks)} chunks for storage")
            
            # Store in Lab Vector Store with collection name
            success = self.store.AddCollections(chunks, self.collection_name)
            if success:
                logger.info(f"Successfully stored {len(chunks)} chunks in collection '{self.collection_name}'")
            return success
            
        except Exception as e:
            logger.error(f"Error storing components: {str(e)}")
            return False

    def get_metrics(self) -> Dict[str, Any]:
        """Get basic metrics about stored components."""
        try:
            return self.store.GetCollectionInfo(self.collection_name)
        except Exception as e:
            logger.error(f"Error getting metrics: {str(e)}")
            return {"error": str(e)} 