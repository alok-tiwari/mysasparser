from prd_sas_parser import SASParser
from prd_embedding_generator import EmbeddingGenerator
from sas_chunk_store import SASChunkStore
import numpy as np
import shutil
import os
import argparse
from pathlib import Path
import logging
import sys
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('PRDTestParser')

def test_parser():
    """Test the SAS parser functionality."""
    parser = SASParser()
    components = parser.parse_file("prd_mock_data/sample.sas")
    
    print("\n=== Parser Test Results ===")
    print(f"Total components found: {len(components)}")
    for comp in components:
        print(f"\nComponent Type: {comp.type}")
        print(f"Name: {comp.name}")
        print(f"Lines: {comp.line_start}-{comp.line_end}")
        if 'analysis' in comp.metadata:
            print(f"Complexity: {comp.metadata['analysis']['complexity']}")
            if comp.metadata['analysis']['macro_variables']:
                print(f"Macro variables: {comp.metadata['analysis']['macro_variables']}")

def test_embeddings():
    """Test embedding generation."""
    parser = SASParser()
    embedding_gen = EmbeddingGenerator(embedding_dim=4096)
    
    components = parser.parse_file("prd_mock_data/sample.sas")
    embeddings = embedding_gen.generate_embeddings(components)
    
    print("\n=== Embedding Test Results ===")
    print(f"Total embeddings generated: {len(embeddings)}")
    for i, emb in enumerate(embeddings[:2]):
        print(f"\nEmbedding {i+1}:")
        print(f"Shape: {emb.embedding.shape}")
        print(f"Type: {emb.component.type}")
        print(f"Metadata: {emb.metadata}")
        print(f"Non-zero elements: {np.count_nonzero(emb.embedding)}")

def test_vector_store():
    """Test storing SAS components in Lab Vector Store."""
    parser = SASParser()
    chunk_store = SASChunkStore(collection_name="sas-python-collection")
    
    components = parser.parse_file("prd_mock_data/sample.sas")
    
    print("\n=== Vector Store Test Results ===")
    success = chunk_store.store_components(components)
    
    if success:
        print("Successfully stored components in Lab Vector Store")
        metrics = chunk_store.get_metrics()
        print(f"Vector Store Metrics: {metrics}")
    else:
        print("Failed to store components")

def cleanup_chromadb():
    """Clean up ChromaDB directory."""
    try:
        if os.path.exists("chroma_db"):
            shutil.rmtree("chroma_db")
            print("ChromaDB cleaned up")
    except Exception as e:
        print(f"Warning: ChromaDB cleanup error: {str(e)}")

def test_directory_parsing():
    """Test parsing all SAS files in directory."""
    print("\n=== Testing Directory Parsing ===")
    parser = SASParser()
    
    total_components = 0
    component_types = {}
    
    for components in parser.parse_directory("prd_mock_data"):
        if components:
            total_components += len(components)
            for comp in components:
                component_types[comp.type] = component_types.get(comp.type, 0) + 1
    
    print(f"\nTotal components found: {total_components}")
    print("\nComponent types distribution:")
    for comp_type, count in component_types.items():
        print(f"{comp_type}: {count}")

def main():
    parser = argparse.ArgumentParser(description='Test SAS Parser, Embeddings, and Vector Store')
    parser.add_argument('--input', default='prd_mock_data', help='Input directory containing SAS files')
    parser.add_argument('--clean', action='store_true', help='Clean ChromaDB before running')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        if args.clean:
            cleanup_chromadb()

        # Run tests
        test_parser()
        test_embeddings()
        test_vector_store()
        test_directory_parsing()

    except Exception as e:
        logger.error(f"Critical error: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main() 