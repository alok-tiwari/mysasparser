from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field
import requests
import numpy as np
import json
import hashlib
import os
import logging
from tqdm import tqdm
from sas_parser import SASComponent

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('EmbeddingGenerator')

@dataclass
class CodeEmbedding:
    component: SASComponent
    embedding: np.ndarray
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert embedding to dictionary for serialization."""
        return {
            "component_type": self.component.type,
            "component_name": self.component.name,
            "metadata": self.metadata,
            "embedding": self.embedding.tolist() if isinstance(self.embedding, np.ndarray) else self.embedding
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], component: SASComponent) -> 'CodeEmbedding':
        """Create CodeEmbedding from dictionary."""
        return cls(
            component=component,
            embedding=np.array(data["embedding"]) if isinstance(data["embedding"], list) else data["embedding"],
            metadata=data["metadata"]
        )

class EmbeddingGenerator:
    """
    Enhanced generator for SAS code embeddings with support for multiple embedding models,
    caching, and better error handling.
    """
    
    # Supported embedding providers
    PROVIDERS = {
        "ollama": {
            "default_url": "http://localhost:11434",
            "default_model": "llama2"
        },
        "openai": {
            "default_url": "https://api.openai.com/v1",
            "default_model": "text-embedding-ada-002"
        },
        "local": {
            "description": "Uses deterministic embeddings based on content hash"
        }
    }
    
    def __init__(
        self, 
        provider: str = "local", 
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        cache_dir: str = ".embeddings_cache",
        embedding_dim: int = 4096
    ):
        """
        Initialize the embedding generator.
        
        Args:
            provider: The embedding provider ('ollama', 'openai', or 'local')
            api_url: API URL for the provider (if applicable)
            api_key: API key for the provider (if applicable)
            model: Model name to use (provider-specific)
            cache_dir: Directory to cache embeddings
            embedding_dim: Dimension for fallback embeddings
        """
        self.provider = provider.lower()
        self.embedding_dim = embedding_dim
        
        if self.provider not in self.PROVIDERS:
            logger.warning(f"Unsupported provider '{provider}'. Falling back to local embeddings.")
            self.provider = "local"
            
        # Set up provider-specific configuration
        if self.provider == "ollama":
            self.api_url = api_url or self.PROVIDERS["ollama"]["default_url"]
            self.model = model or self.PROVIDERS["ollama"]["default_model"]
            self.test_ollama_connection()
            
        elif self.provider == "openai":
            self.api_url = api_url or self.PROVIDERS["openai"]["default_url"]
            self.api_key = api_key
            self.model = model or self.PROVIDERS["openai"]["default_model"]
            
            if not self.api_key:
                logger.warning("No API key provided for OpenAI. Falling back to local embeddings.")
                self.provider = "local"
            else:
                self.test_openai_connection()
                
        # Set up embedding cache
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cache_hits = 0
        self.cache_misses = 0
        
    def test_ollama_connection(self):
        """Test connection to Ollama API"""
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=5)
            if response.status_code != 200:
                logger.warning(f"Ollama API not responding correctly. Status: {response.status_code}")
                logger.warning("Falling back to local embeddings.")
                self.provider = "local"
            else:
                logger.info(f"Successfully connected to Ollama API using model: {self.model}")
                # Verify model exists
                models = response.json().get("models", [])
                model_names = [m.get("name") for m in models]
                if self.model not in model_names:
                    logger.warning(f"Model '{self.model}' not found in Ollama. Available models: {model_names}")
                    # Try to use an available model or fallback
                    if model_names:
                        self.model = model_names[0]
                        logger.info(f"Using available model: {self.model}")
                    else:
                        logger.warning("No models available in Ollama. Falling back to local embeddings.")
                        self.provider = "local"
        except Exception as e:
            logger.warning(f"Could not connect to Ollama API ({str(e)})")
            logger.warning("Falling back to local embeddings.")
            self.provider = "local"

    def test_openai_connection(self):
        """Test connection to OpenAI API"""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            # Just check models endpoint to verify connection
            response = requests.get(
                f"{self.api_url}/models",
                headers=headers,
                timeout=5
            )
            if response.status_code != 200:
                logger.warning(f"OpenAI API not responding correctly. Status: {response.status_code}")
                logger.warning(f"Message: {response.text}")
                logger.warning("Falling back to local embeddings.")
                self.provider = "local"
            else:
                logger.info(f"Successfully connected to OpenAI API using model: {self.model}")
        except Exception as e:
            logger.warning(f"Could not connect to OpenAI API ({str(e)})")
            logger.warning("Falling back to local embeddings.")
            self.provider = "local"

    def _get_cache_path(self, component: SASComponent) -> str:
        """Get cache file path for a component."""
        # Create a unique identifier based on component content and metadata
        content_hash = hashlib.md5(component.content.encode()).hexdigest()
        component_id = f"{component.type}_{component.name}_{content_hash}"
        return os.path.join(self.cache_dir, f"{component_id}.json")

    def _load_from_cache(self, component: SASComponent) -> Optional[np.ndarray]:
        """Load embedding from cache if available."""
        cache_path = self._get_cache_path(component)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r') as f:
                    data = json.load(f)
                    self.cache_hits += 1
                    return np.array(data["embedding"])
            except Exception as e:
                logger.warning(f"Error loading from cache: {str(e)}")
        
        self.cache_misses += 1
        return None

    def _save_to_cache(self, component: SASComponent, embedding: np.ndarray):
        """Save embedding to cache."""
        cache_path = self._get_cache_path(component)
        try:
            with open(cache_path, 'w') as f:
                json.dump({
                    "component_type": component.type,
                    "component_name": component.name,
                    "embedding": embedding.tolist()
                }, f)
        except Exception as e:
            logger.warning(f"Error saving to cache: {str(e)}")

    def generate_embeddings(self, components: List[SASComponent]) -> List[CodeEmbedding]:
        """Generate embeddings for a list of SAS components."""
        embeddings = []
        
        for component in tqdm(components, desc=f"Generating embeddings ({self.provider})"):
            try:
                # First, try to load from cache
                cached_embedding = self._load_from_cache(component)
                if cached_embedding is not None:
                    logger.debug(f"Using cached embedding for {component.name}")
                    embedding = cached_embedding
                else:
                    # Prepare text for embedding generation
                    text = self._prepare_text(component)
                    
                    # Generate embedding based on provider
                    if self.provider == "ollama":
                        embedding = self._get_ollama_embedding(text)
                    elif self.provider == "openai":
                        embedding = self._get_openai_embedding(text)
                    else:  # local
                        embedding = self._generate_deterministic_embedding(text)
                    
                    # Cache the embedding
                    self._save_to_cache(component, embedding)
                
                # Create metadata for the embedding
                metadata = self._create_metadata(component)
                
                # Create and add the code embedding
                embeddings.append(CodeEmbedding(
                    component=component,
                    embedding=embedding,
                    metadata=metadata
                ))
                
            except Exception as e:
                logger.error(f"Error generating embedding for {component.name}: {str(e)}")
                # Use fallback embedding
                text = self._prepare_text(component)
                embedding = self._generate_deterministic_embedding(text)
                metadata = self._create_metadata(component)
                
                embeddings.append(CodeEmbedding(
                    component=component,
                    embedding=embedding,
                    metadata=metadata
                ))
                
        logger.info(f"Generated {len(embeddings)} embeddings (cache hits: {self.cache_hits}, misses: {self.cache_misses})")
        return embeddings

    def _prepare_text(self, component: SASComponent) -> str:
        """Prepare component text for embedding generation with enhanced context."""
        # Build a rich description of the component
        description = self._get_component_description(component)
        
        # Prepare text with different sections
        text_parts = [
            f"Type: {component.type}",
            f"Name: {component.name}",
            f"Description: {description}"
        ]
        
        # Add metadata if available
        if component.metadata:
            # Filter metadata to include only relevant keys
            relevant_metadata = {k: v for k, v in component.metadata.items() 
                              if k not in ['file_path', 'directory', 'source_file']}
            if relevant_metadata:
                text_parts.append("Metadata:")
                for key, value in relevant_metadata.items():
                    if isinstance(value, (list, dict)):
                        text_parts.append(f"  {key}: {json.dumps(value)}")
                    else:
                        text_parts.append(f"  {key}: {value}")
        
        # Add dependencies if available
        if component.dependencies:
            text_parts.append("Dependencies: " + ", ".join(component.dependencies))
        
        # Add macro variables if available
        if hasattr(component, 'macro_variables') and component.macro_variables:
            text_parts.append("Macro Variables:")
            for var, value in component.macro_variables.items():
                text_parts.append(f"  &{var} = {value}")
        
        # Add content with a character limit to avoid excessive token usage
        content_limit = 8000  # Adjust based on model context size
        content = component.content
        if len(content) > content_limit:
            # If content is too long, include the beginning and end
            half_limit = content_limit // 2
            content = content[:half_limit] + "\n...[content truncated]...\n" + content[-half_limit:]
        
        text_parts.append("Content:")
        text_parts.append(content)
        
        return "\n".join(text_parts)

    def _get_component_description(self, component: SASComponent) -> str:
        """Generate a rich description based on component type and content."""
        if component.type == "PROC":
            return f"SAS procedure {component.name} with parameters and options for data analysis or reporting"
        elif component.type == "DATA":
            return f"DATA step named {component.name} containing data transformations and processing logic"
        elif component.type == "MACRO":
            return f"Macro definition for {component.name} with parameters and reusable SAS logic"
        elif component.type == "LIBNAME":
            return f"Library reference definition for {component.name} pointing to a data source"
        elif component.type == "FILENAME":
            return f"File reference definition for {component.name} pointing to an external file"
        elif component.type == "PROC_SQL":
            return f"SQL procedure containing database queries and data manipulation"
        elif component.type == "FORMAT":
            return f"Format definition for data display or conversion"
        elif component.type.startswith("%"):
            return f"Macro statement {component.type} for SAS macro programming"
        elif component.type == "ODS":
            return f"Output Delivery System configuration for controlling SAS output"
        else:
            return f"SAS component {component.name} of type {component.type}"

    def _create_metadata(self, component: SASComponent) -> Dict[str, Any]:
        """Create rich metadata for the embedding."""
        metadata = {
            "file_path": component.metadata.get("file_path", "unknown"),
            "source_file": component.metadata.get("source_file", "unknown"),
            "directory": component.metadata.get("directory", "unknown"),
            "type": component.type,
            "name": component.name,
            "line_start": component.line_start,
            "line_end": component.line_end,
        }
        
        # Add component type-specific metadata
        if component.type == "PROC":
            metadata["proc_type"] = component.name
            if "proc_options" in component.metadata:
                metadata["proc_options"] = component.metadata["proc_options"]
        elif component.type == "DATA":
            if "operation" in component.metadata:
                metadata["operation"] = component.metadata["operation"]
            if "input_datasets" in component.metadata:
                metadata["input_datasets"] = component.metadata["input_datasets"]
        elif component.type == "MACRO":
            if "parameters" in component.metadata:
                metadata["parameters"] = component.metadata["parameters"]
        elif component.type == "PROC_SQL":
            if "statement_counts" in component.metadata:
                metadata["sql_statement_counts"] = component.metadata["statement_counts"]
            if "referenced_tables" in component.metadata:
                metadata["sql_tables"] = component.metadata["referenced_tables"]
                
        # Add dependency information
        metadata["dependencies"] = component.dependencies
        
        # Add size information
        metadata["content_length"] = len(component.content)
        metadata["line_count"] = component.line_end - component.line_start + 1
        
        return metadata

    def _generate_deterministic_embedding(self, text: str, dim: Optional[int] = None) -> np.ndarray:
        """
        Generate a deterministic embedding based on text content.
        Uses hash of text as seed for reproducibility.
        """
        if dim is None:
            dim = self.embedding_dim
            
        # Use text hash as seed for reproducibility
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
        rng = np.random.RandomState(seed)
        
        # Generate embedding
        embedding = rng.normal(0, 1, dim)
        # Normalize the embedding
        embedding = embedding / np.linalg.norm(embedding)
        
        return embedding

    def _get_ollama_embedding(self, text: str) -> np.ndarray:
        """
        Get embeddings from Ollama API with enhanced error handling.
        """
        try:
            response = requests.post(
                f"{self.api_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=30  # Increased timeout for larger texts
            )
            
            if response.status_code != 200:
                logger.warning(f"Ollama API error: {response.status_code} - {response.text}")
                return self._generate_deterministic_embedding(text)
                
            response_json = response.json()
            if 'embedding' not in response_json:
                logger.warning(f"Unexpected Ollama API response: {response_json}")
                return self._generate_deterministic_embedding(text)
                
            embedding = np.array(response_json['embedding'])
            
            # Ensure the embedding is normalized
            if np.linalg.norm(embedding) > 0:
                embedding = embedding / np.linalg.norm(embedding)
                
            return embedding
            
        except Exception as e:
            logger.warning(f"Error generating Ollama embedding: {str(e)}")
            return self._generate_deterministic_embedding(text)

    def _get_openai_embedding(self, text: str) -> np.ndarray:
        """
        Get embeddings from OpenAI API with enhanced error handling.
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            response = requests.post(
                f"{self.api_url}/embeddings",
                headers=headers,
                json={
                    "model": self.model,
                    "input": text,
                    "encoding_format": "float"
                },
                timeout=30
            )
            
            if response.status_code != 200:
                logger.warning(f"OpenAI API error: {response.status_code} - {response.text}")
                return self._generate_deterministic_embedding(text)
                
            response_json = response.json()
            if 'data' not in response_json or not response_json['data']:
                logger.warning(f"Unexpected OpenAI API response: {response_json}")
                return self._generate_deterministic_embedding(text)
                
            embedding = np.array(response_json['data'][0]['embedding'])
            
            # Ensure the embedding is normalized
            if np.linalg.norm(embedding) > 0:
                embedding = embedding / np.linalg.norm(embedding)
                
            return embedding
            
        except Exception as e:
            logger.warning(f"Error generating OpenAI embedding: {str(e)}")
            return self._generate_deterministic_embedding(text)

    def generate_file_level_embedding(self, components: List[SASComponent], file_path: str) -> CodeEmbedding:
        """
        Generate an embedding for an entire file by combining component embeddings.
        """
        # Filter components that belong to the file
        file_components = [comp for comp in components 
                        if comp.metadata.get("file_path") == file_path]
        
        if not file_components:
            logger.warning(f"No components found for file {file_path}")
            return None
            
        # Generate embeddings for all components if not already done
        component_embeddings = []
        for component in file_components:
            # Check if we have cached embedding
            cached_embedding = self._load_from_cache(component)
            if cached_embedding is not None:
                component_embeddings.append(cached_embedding)
            else:
                # Generate new embedding
                text = self._prepare_text(component)
                if self.provider == "ollama":
                    embedding = self._get_ollama_embedding(text)
                elif self.provider == "openai":
                    embedding = self._get_openai_embedding(text)
                else:  # local
                    embedding = self._generate_deterministic_embedding(text)
                    
                component_embeddings.append(embedding)
                self._save_to_cache(component, embedding)
        
        # Create a combined embedding by averaging
        if component_embeddings:
            combined_embedding = np.mean(component_embeddings, axis=0)
            # Normalize the combined embedding
            if np.linalg.norm(combined_embedding) > 0:
                combined_embedding = combined_embedding / np.linalg.norm(combined_embedding)
        else:
            # Fallback if no embeddings could be generated
            dummy_text = f"File: {os.path.basename(file_path)}"
            combined_embedding = self._generate_deterministic_embedding(dummy_text)
            
        # Create a virtual "file" component
        file_component = SASComponent(
            type="FILE",
            name=os.path.basename(file_path),
            content="",  # Content is combined from all components
            line_start=1,
            line_end=max(comp.line_end for comp in file_components) if file_components else 1,
            metadata={
                "file_path": file_path,
                "source_file": os.path.basename(file_path),
                "directory": os.path.dirname(file_path),
                "component_count": len(file_components),
                "component_types": list(set(comp.type for comp in file_components))
            }
        )
        
        # Create file-level metadata
        file_metadata = {
            "file_path": file_path,
            "source_file": os.path.basename(file_path),
            "directory": os.path.dirname(file_path),
            "component_count": len(file_components),
            "component_types": list(set(comp.type for comp in file_components)),
            "line_count": max(comp.line_end for comp in file_components) if file_components else 0,
            "proc_count": len([comp for comp in file_components if comp.type == "PROC" or comp.type.startswith("PROC_")]),
            "data_step_count": len([comp for comp in file_components if comp.type == "DATA"]),
            "macro_count": len([comp for comp in file_components if comp.type == "MACRO"])
        }
        
        # Create and return the file-level embedding
        return CodeEmbedding(
            component=file_component,
            embedding=combined_embedding,
            metadata=file_metadata
        )

    def generate_batch_embeddings(
        self, 
        components: List[SASComponent],
        batch_size: int = 10,
        include_file_embeddings: bool = True
    ) -> Dict[str, List[CodeEmbedding]]:
        """
        Generate embeddings in batches with progress tracking and optional file-level embeddings.
        """
        results = {
            "component_embeddings": [],
            "file_embeddings": []
        }
        
        # Process components in batches
        total_batches = (len(components) + batch_size - 1) // batch_size
        
        for batch_idx in range(total_batches):
            start_idx = batch_idx * batch_size
            end_idx = min(start_idx + batch_size, len(components))
            batch_components = components[start_idx:end_idx]
            
            logger.info(f"Processing batch {batch_idx+1}/{total_batches} ({len(batch_components)} components)")
            batch_embeddings = self.generate_embeddings(batch_components)
            results["component_embeddings"].extend(batch_embeddings)
            
        # Generate file-level embeddings if requested
        if include_file_embeddings:
            # Get unique file paths
            file_paths = set()
            for component in components:
                if "file_path" in component.metadata:
                    file_paths.add(component.metadata["file_path"])
            
            logger.info(f"Generating file-level embeddings for {len(file_paths)} files")
            for file_path in tqdm(file_paths, desc="File embeddings"):
                file_embedding = self.generate_file_level_embedding(components, file_path)
                if file_embedding:
                    results["file_embeddings"].append(file_embedding)
                    
        return results

    def export_embeddings(self, embeddings: List[CodeEmbedding], output_file: str):
        """
        Export embeddings to a JSON file.
        """
        # Convert embeddings to dictionaries
        embeddings_data = [emb.to_dict() for emb in embeddings]
        
        try:
            with open(output_file, 'w') as f:
                json.dump({
                    "provider": self.provider,
                    "model": getattr(self, "model", "local"),
                    "embedding_count": len(embeddings),
                    "embedding_dimension": self.embedding_dim,
                    "embeddings": embeddings_data
                }, f)
            logger.info(f"Exported {len(embeddings)} embeddings to {output_file}")
        except Exception as e:
            logger.error(f"Error exporting embeddings: {str(e)}")

    def generate_embedding(self, component: SASComponent) -> CodeEmbedding:
        """Generate embedding for a single component."""
        embeddings = self.generate_embeddings([component])
        return embeddings[0] if embeddings else None