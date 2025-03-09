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

    def _prepare_default_chunks(self, components: List[SASComponent]) -> List[Dict[str, Any]]:
        """Default chunking strategy if LabVectorStore doesn't provide one."""
        chunks = []
        for component in components:
            chunk = {
                "content": component.content,
                "metadata": {
                    "type": component.type,
                    "name": component.name,
                    "line_start": component.line_start,
                    "line_end": component.line_end,
                    "file_path": component.metadata.get("file_path", ""),
                    "source_file": component.metadata.get("source_file", ""),
                    **component.metadata
                }
            }
            chunks.append(chunk)
        return chunks

    def prepare_chunks(self, components: List[SASComponent]) -> List[Dict[str, Any]]:
        """
        Prepare chunks using LabVectorStore's chunking method if available,
        otherwise use default chunking.
        """
        try:
            # Check if LabVectorStore provides chunking
            if hasattr(self.store, 'prepare_chunks'):
                logger.info("Using LabVectorStore chunking method")
                return self.store.prepare_chunks(components)
            else:
                logger.info("Using default chunking method")
                return self._prepare_default_chunks(components)
        except Exception as e:
            logger.warning(f"Error in LabVectorStore chunking, falling back to default: {str(e)}")
            return self._prepare_default_chunks(components)

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