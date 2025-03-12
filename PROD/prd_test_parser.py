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

def test_parser_relationships():
    """Test parent/child relationships and comment handling."""
    # Test with comments
    SASParser.INCLUDE_COMMENTS = True  # Set class variable directly
    parser_with_comments = SASParser()
    components_with_comments = parser_with_comments.parse_file("prd_mock_data/comprehensive_test.sas")
    
    print("\n=== With Comments ===")
    print(f"Total components: {len(components_with_comments)}")
    
    # Test without comments
    SASParser.INCLUDE_COMMENTS = False  # Set class variable directly
    parser_no_comments = SASParser()
    components_no_comments = parser_no_comments.parse_file("prd_mock_data/comprehensive_test.sas")
    
    print("\n=== Without Comments ===")
    print(f"Total components: {len(components_no_comments)}")
    
    # Check relationships
    print("\n=== Relationship Analysis ===")
    for comp in components_no_comments:
        print(f"\nComponent: {comp.type} - {comp.name}")
        print(f"Lines: {comp.line_start}-{comp.line_end}")
        
        # Check parent info
        parent_info = comp.metadata.get('parent_info', {})
        if parent_info.get('parent_name'):
            print(f"Parent: {parent_info['parent_name']} ({parent_info['parent_type']})")
        
        # Check nested info
        nested_info = comp.metadata.get('nested_info', {})
        if nested_info.get('has_nested'):
            print(f"Nested components: {nested_info['nested_names']}")
            print(f"Nested count: {nested_info['nested_count']}")

def test_parent_nested_info():
    """Test parent/nested relationships are correctly captured."""
    parser = SASParser()
    
    # Test with nested macro
    sas_content = """
%macro outer;
    proc sql;
        select * from table;
    quit;
    
    data test;
        set input;
    run;
%mend;
"""
    
    with open("prd_mock_data/nested_test.sas", "w") as f:
        f.write(sas_content)
    
    components = parser.parse_file("prd_mock_data/nested_test.sas")
    
    # Find the macro component
    macro_comp = next(c for c in components if c.type == 'MACRO')
    
    print("\nNested Info:")
    print(f"Macro has nested: {macro_comp.metadata['nested_info']['has_nested']}")
    print(f"Nested count: {macro_comp.metadata['nested_info']['nested_count']}")
    print(f"Nested names: {macro_comp.metadata['nested_info']['nested_names']}")
    
    # Find a nested component
    sql_comp = next(c for c in components if c.type == 'PROC_SQL')
    
    print("\nParent Info:")
    print(f"SQL parent name: {sql_comp.metadata['parent_info']['parent_name']}")
    print(f"SQL parent type: {sql_comp.metadata['parent_info']['parent_type']}")

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
        test_parser_relationships()
        test_parent_nested_info()

    except Exception as e:
        logger.error(f"Critical error: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main() 