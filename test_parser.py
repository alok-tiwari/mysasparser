from sas_parser import SASParser
from embedding_generator import EmbeddingGenerator
from vector_store import VectorStore
import numpy as np
import shutil
import os
import tempfile
from pathlib import Path

def test_parser():
    # Test SAS Parser
    parser = SASParser()
    components = parser.parse_file("mock_data/sample.sas")
    
    print("\n=== Parser Test Results ===")
    print(f"Total components found: {len(components)}")
    for comp in components:
        print(f"\nComponent Type: {comp.type}")
        print(f"Name: {comp.name}")
        print(f"Lines: {comp.line_start}-{comp.line_end}")
        print(f"Content preview: {comp.content[:100]}...")

def test_embeddings():
    # Test Embedding Generation
    parser = SASParser()
    embedding_gen = EmbeddingGenerator()
    
    components = parser.parse_file("mock_data/sample.sas")
    embeddings = embedding_gen.generate_embeddings(components)
    
    print("\n=== Embedding Test Results ===")
    print(f"Total embeddings generated: {len(embeddings)}")
    for i, emb in enumerate(embeddings[:2]):  # Show first 2 embeddings
        print(f"\nEmbedding {i+1}:")
        print(f"Shape: {emb.embedding.shape}")
        print(f"Type: {emb.component.type}")
        print(f"Metadata: {emb.metadata}")
        print(f"Non-zero elements: {np.count_nonzero(emb.embedding)}")

def test_vector_store():
    # Test Vector Store
    parser = SASParser()
    embedding_gen = EmbeddingGenerator()
    vector_store = VectorStore(persist_directory="chroma_db")
    
    components = parser.parse_file("mock_data/sample.sas")
    embeddings = embedding_gen.generate_embeddings(components)
    vector_store.store_embeddings(embeddings)
    
    # Test retrieval
    print("\n=== Vector Store Test Results ===")
    for collection_name, collection in vector_store.collections.items():
        count = collection.count()
        print(f"\nCollection '{collection_name}' has {count} entries")
        
        if count > 0:
            # Get a sample entry
            result = collection.get(limit=1)
            print(f"Sample metadata: {result['metadatas'][0]}")

def cleanup_chromadb():
    print("\nCleaning up ChromaDB...")
    # Remove the ChromaDB directory if it exists
    if os.path.exists("chroma_db"):
        shutil.rmtree("chroma_db")
    print("ChromaDB cleaned up")

def test_single_component():
    """Test parsing of a single component to debug issues."""
    print("\n=== Testing Single Component Parsing ===")
    test_content = """
/* Test PROC SQL */
proc sql;
    create table test as
    select * from data;
quit;

/* Test DATA step */
data test;
    set input;
    x = 1;
run;

/* Test Macro */
%macro test(param);
    proc print data=&param;
    run;
%mend test;
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sas', delete=False) as f:
        f.write(test_content)
        test_file = f.name
    
    parser = SASParser()
    components = parser.parse_file(test_file)
    
    print(f"Found {len(components)} components")
    for comp in components:
        print(f"\nComponent Type: {comp.type}")
        print(f"Name: {comp.name}")
        print(f"Lines: {comp.line_start}-{comp.line_end}")
        print(f"Content:\n{comp.content}")
        print(f"Metadata: {comp.metadata}")

def test_directory_parsing():
    """Test parsing all SAS files in mock_data directory."""
    print("\n=== Testing Directory Parsing ===")
    parser = SASParser()
    
    total_components = 0
    component_types = {}
    file_components = {}
    
    # Process each file
    for components in parser.parse_directory("mock_data"):
        if components:  # If any components were found
            file_path = components[0].metadata["source_file"]
            file_components[file_path] = components
            total_components += len(components)
            for comp in components:
                component_types[comp.type] = component_types.get(comp.type, 0) + 1
    
    # Print summary
    print(f"\nTotal files processed: {len(list(Path('mock_data').glob('*.sas')))}")
    print(f"Total components found: {total_components}")
    
    # Print file-by-file breakdown
    print("\nComponents by file:")
    for file_name, components in file_components.items():
        print(f"\n{file_name}:")
        file_type_counts = {}
        for comp in components:
            file_type_counts[comp.type] = file_type_counts.get(comp.type, 0) + 1
        for comp_type, count in file_type_counts.items():
            print(f"  {comp_type}: {count}")
    
    # Print overall type summary
    print("\nTotal components by type:")
    for comp_type, count in sorted(component_types.items()):
        print(f"{comp_type}: {count}")

def main():
    print("Starting tests...")
    
    cleanup_chromadb()
    
    print("\nTesting Single Component...")
    test_single_component()
    
    print("\nTesting Directory Parsing...")
    test_directory_parsing()
    
    print("\nTesting Parser...")
    test_parser()
    
    print("\nTesting Embedding Generation...")
    test_embeddings()
    
    print("\nTesting Vector Store...")
    test_vector_store()
    
    # Clean up after tests
    cleanup_chromadb()

if __name__ == "__main__":
    main() 