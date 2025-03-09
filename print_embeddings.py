from sas_parser import SASParser
from embedding_generator import EmbeddingGenerator
import argparse
import logging
from pathlib import Path
import glob
import os
import json
import numpy as np
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('print_embeddings')

def reconstruct_from_embedding(embedding: np.ndarray) -> str:
    """
    Reconstruct text content from embedding vector.
    This is a placeholder - implement actual reconstruction based on your embedding model.
    """
    # TODO: Implement actual reconstruction using your embedding model
    # This might involve:
    # 1. Using the model's decoder
    # 2. Finding nearest neighbors in your embedding space
    # 3. Using inverse transformation
    return "Reconstruction not implemented yet"

def print_embeddings(input_dir: str, output_file: str = None):
    """
    Parse SAS files and print their vector embeddings with reconstruction verification.
    
    Args:
        input_dir: Directory containing SAS files
        output_file: Optional file to save embeddings as JSON
    """
    # Initialize components
    parser = SASParser()
    embedding_gen = EmbeddingGenerator(embedding_dim=4096)
    
    # Store all embeddings
    all_embeddings = []
    
    # Process all SAS files
    for sas_file in glob.glob(os.path.join(input_dir, "*.sas")):
        logger.info(f"\nProcessing {sas_file}...")
        
        # Parse file
        components = parser.parse_file(sas_file)
        if not components:
            logger.warning(f"No components found in {sas_file}")
            continue
            
        logger.info(f"Found {len(components)} components")
        
        # Generate embeddings for each component
        for component in components:
            embedding = embedding_gen.generate_embedding(component)
            
            # Get the vector from CodeEmbedding object
            vector = embedding.vector if hasattr(embedding, 'vector') else embedding
            
            # Create embedding info
            embedding_info = {
                'file': sas_file,
                'type': component.type,
                'content': component.content.strip(),
                'embedding': vector.tolist() if isinstance(vector, np.ndarray) else vector,
                'line_start': component.line_start,
                'line_end': component.line_end
            }
            
            all_embeddings.append(embedding_info)
            
            # Print embedding info and verification
            print("\nComponent Information:")
            print(f"File: {sas_file}")
            print(f"Type: {component.type}")
            print(f"Lines: {component.line_start}-{component.line_end}")
            print("\nOriginal Content:")
            print(component.content.strip())
            
            print("\nEmbedding (first 10 dimensions):")
            if isinstance(vector, np.ndarray):
                print(vector[:10])
                
                # Try to reconstruct and verify
                print("\nReconstruction from Embedding:")
                reconstructed = reconstruct_from_embedding(vector)
                print(reconstructed)
                
                # Print similarity score if possible
                try:
                    similarity = embedding_gen.compute_similarity(
                        component.content.strip(),
                        reconstructed
                    )
                    print(f"\nSimilarity Score: {similarity:.4f}")
                except Exception as e:
                    logger.debug(f"Could not compute similarity: {str(e)}")
            else:
                print("Embedding vector not available")
            
            print("-" * 80)
    
    logger.info(f"\nTotal embeddings generated: {len(all_embeddings)}")
    
    # Save to file if specified
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(all_embeddings, f, indent=2)
        logger.info(f"Embeddings saved to {output_file}")

def main():
    parser = argparse.ArgumentParser(description='Print vector embeddings for SAS code')
    parser.add_argument('--input', required=True, help='Input directory containing SAS files')
    parser.add_argument('--output', help='Optional JSON file to save embeddings')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    print_embeddings(args.input, args.output)

if __name__ == '__main__':
    main() 