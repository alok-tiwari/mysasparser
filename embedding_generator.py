from typing import List, Dict, Any
from dataclasses import dataclass
import requests
import numpy as np
from tqdm import tqdm
from sas_parser import SASComponent

@dataclass
class CodeEmbedding:
    component: SASComponent
    embedding: np.ndarray
    metadata: Dict[str, Any]

class EmbeddingGenerator:
    def __init__(self, api_url: str = "http://localhost:11434"):
        self.api_url = api_url
        # Test connection on init
        self.test_connection()

    def test_connection(self):
        """Test connection to Ollama API"""
        try:
            response = requests.get(f"{self.api_url}/api/tags")
            if response.status_code != 200:
                print(f"Warning: Ollama API not responding correctly. Status: {response.status_code}")
                print("Using fallback random embeddings for testing.")
            else:
                print("Successfully connected to Ollama API")
        except Exception as e:
            print(f"Warning: Could not connect to Ollama API ({str(e)})")
            print("Using fallback random embeddings for testing.")

    def generate_embeddings(self, components: List[SASComponent]) -> List[CodeEmbedding]:
        """Generate embeddings for a list of SAS components using Ollama."""
        embeddings = []
        use_fallback = False
        
        # Test first component to determine if we should use fallback
        if components:
            try:
                response = requests.post(
                    f"{self.api_url}/api/embeddings",
                    json={"model": "llama2", "prompt": "test"},
                    timeout=5
                )
                if response.status_code != 200:
                    use_fallback = True
                    print("Using fallback random embeddings (API not available)")
            except Exception:
                use_fallback = True
                print("Using fallback random embeddings (connection failed)")
        
        for component in tqdm(components, desc="Generating embeddings"):
            try:
                # Prepare text for embedding
                text = self._prepare_text(component)
                
                if not use_fallback:
                    # Try to get real embedding
                    response = requests.post(
                        f"{self.api_url}/api/embeddings",
                        json={"model": "llama2", "prompt": text},
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        embedding_data = response.json()
                        if 'embedding' in embedding_data:
                            embedding = np.array(embedding_data['embedding'])
                        else:
                            embedding = self._generate_deterministic_embedding(text)
                    else:
                        embedding = self._generate_deterministic_embedding(text)
                else:
                    # Use deterministic fallback
                    embedding = self._generate_deterministic_embedding(text)
                
                # Create metadata
                metadata = {
                    "file_path": component.metadata.get("file_path", "unknown"),
                    "type": component.type,
                    "name": component.name,
                    "line_start": component.line_start,
                    "line_end": component.line_end,
                    "source_file": component.metadata.get("source_file", "unknown")
                }
                
                embeddings.append(CodeEmbedding(
                    component=component,
                    embedding=embedding,
                    metadata=metadata
                ))
                
            except Exception as e:
                print(f"Warning: Using fallback embedding for {component.name}")
                embedding = self._generate_deterministic_embedding(text)
                metadata = {
                    "file_path": component.metadata.get("file_path", "unknown"),
                    "type": component.type,
                    "name": component.name,
                    "line_start": component.line_start,
                    "line_end": component.line_end,
                    "source_file": component.metadata.get("source_file", "unknown")
                }
                embeddings.append(CodeEmbedding(
                    component=component,
                    embedding=embedding,
                    metadata=metadata
                ))
                
        return embeddings

    def _prepare_text(self, component: SASComponent) -> str:
        """Prepare component text for embedding generation."""
        text_parts = [
            f"Type: {component.type}",
            f"Name: {component.name}",
            "Content:",
            component.content
        ]
        return "\n".join(text_parts)

    def _generate_deterministic_embedding(self, text: str, dim: int = 4096) -> np.ndarray:
        """Generate a deterministic embedding based on text content."""
        # Use text hash as seed for reproducibility
        seed = hash(text) & 0xffffffff  # Ensure positive seed
        rng = np.random.RandomState(seed)
        
        # Generate embedding
        embedding = rng.normal(0, 1, dim)
        # Normalize the embedding
        embedding = embedding / np.linalg.norm(embedding)
        
        return embedding

    def _get_component_description(self, component: SASComponent) -> str:
        """Generate a description based on component type and content."""
        if component.type == "PROC":
            return f"SAS procedure {component.name} with its parameters and options"
        elif component.type == "DATA":
            return f"DATA step named {component.name} containing data transformations"
        elif component.type == "MACRO":
            return f"Macro definition for {component.name} with its parameters and logic"
        return f"SAS component {component.name}"

    def _get_ollama_embedding(self, text: str) -> np.ndarray:
        """Get embeddings from Ollama API."""
        try:
            response = requests.post(
                f"{self.ollama_url}/api/embeddings",
                json={"model": "llama2", "prompt": text}
            )
            response.raise_for_status()
            embedding = np.array(response.json()["embedding"])
            return embedding
        except Exception as e:
            print(f"Error generating embedding: {str(e)}")
            return np.zeros(4096)  # Return zero vector as fallback