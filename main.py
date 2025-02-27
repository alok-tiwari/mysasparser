from sas_parser import SASParser
from embedding_generator import EmbeddingGenerator
from vector_store import VectorStore

def main():
    # Initialize components
    parser = SASParser()
    embedding_gen = EmbeddingGenerator()
    vector_store = VectorStore(persist_directory="chroma_db")
    
    # Parse SAS file
    sas_components = parser.parse_file("mock_data/sample.sas")
    print(f"Found {len(sas_components)} components")
    
    # Generate embeddings
    embeddings = embedding_gen.generate_embeddings(sas_components)
    print(f"Generated {len(embeddings)} embeddings")
    
    # Store embeddings
    vector_store.store_embeddings(embeddings)
    print("Embeddings stored in ChromaDB")

if __name__ == "__main__":
    main() 