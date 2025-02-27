from sas_parser import SASParser
from embedding_generator import EmbeddingGenerator
from vector_store import VectorStore
from sas_python_converter import SASPythonConverter  # Import the converter
import numpy as np
import shutil
import os
import argparse
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
    embedding_gen = EmbeddingGenerator(embedding_dim=4096)
    
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

def test_end_to_end_conversion(input_dir, output_dir):
    """
    Test the full end-to-end process: parsing, embedding, storing, and converting
    """
    print(f"\n=== Testing End-to-End Conversion ===")
    print(f"Input directory: {input_dir}")
    print(f"Output directory: {output_dir}")
    
    # Initialize components with explicit embedding dimension
    parser = SASParser()
    embedding_gen = EmbeddingGenerator(embedding_dim=4096)  # Explicit dimension
    vector_store = VectorStore(persist_directory="chroma_db")
    converter = SASPythonConverter(
        vector_store=vector_store,
        output_directory=output_dir,
        embedding_generator=embedding_gen  # Pass the instance
    )
    
    # Process all files in directory
    total_files = 0
    total_components = 0
    all_embeddings = []
    
    print("\nStep 1: Parsing SAS files...")
    for components in parser.parse_directory(input_dir):
        if components:
            total_files += 1
            total_components += len(components)
            
            # Generate embeddings for these components
            print(f"Generating embeddings for {len(components)} components...")
            embeddings = embedding_gen.generate_embeddings(components)
            all_embeddings.extend(embeddings)
    
    print(f"\nParsed {total_files} files with {total_components} components")
    
    print("\nStep 2: Storing embeddings in vector database...")
    vector_store.store_embeddings(all_embeddings)
    print(f"Stored {len(all_embeddings)} embeddings")
    
    print("\nStep 3: Converting SAS to Python...")
    # Convert the directory
    converted_files = converter.convert_directory(input_dir)
    print(f"Converted {len(converted_files)} files to Python")
    
    print("\nConversion complete!")
    print(f"Output Python files are in: {output_dir}")
    
    # Return summary
    return {
        "files_processed": total_files,
        "components_found": total_components,
        "embeddings_generated": len(all_embeddings),
        "python_files_created": len(converted_files)
    }

def main():
    # Set up command line arguments
    parser = argparse.ArgumentParser(description='Test SAS parser, embedding generation, and conversion')
    parser.add_argument('--input', '-i', default='mock_data', help='Input directory containing SAS files')
    parser.add_argument('--output', '-o', default='python_output', help='Output directory for Python files')
    parser.add_argument('--test', '-t', choices=['parser', 'embeddings', 'vector', 'single', 'directory', 'conversion', 'all'], 
                        default='all', help='Which test to run')
    parser.add_argument('--clean', '-c', action='store_true', help='Clean ChromaDB before and after tests')
    
    args = parser.parse_args()
    
    if args.clean:
        cleanup_chromadb()
    
    if args.test in ['parser', 'all']:
        print("\nTesting Parser...")
        test_parser()
    
    if args.test in ['embeddings', 'all']:
        print("\nTesting Embedding Generation...")
        test_embeddings()
    
    if args.test in ['vector', 'all']:
        print("\nTesting Vector Store...")
        test_vector_store()
    
    if args.test in ['single', 'all']:
        print("\nTesting Single Component...")
        test_single_component()
    
    if args.test in ['directory', 'all']:
        print("\nTesting Directory Parsing...")
        test_directory_parsing()
    
    if args.test in ['conversion', 'all']:
        print("\nTesting End-to-End Conversion...")
        test_end_to_end_conversion(args.input, args.output)
    
    if args.clean:
        cleanup_chromadb()

if __name__ == "__main__":
    main()