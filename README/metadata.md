# In your storage layer (e.g., sas_chunk_store.py)
def prepare_chunks(self, components: List[SASComponent]) -> List[Dict[str, Any]]:
    chunks = []
    for component in components:
        # Safely access metadata - all these fields are guaranteed to exist
        parent_info = component.metadata.get("parent_info", {})
        nested_info = component.metadata.get("nested_info", {})
        
        chunk = {
            "content": component.content,
            "metadata": {
                # Base fields
                "type": component.type,
                "name": component.name,
                "line_start": component.line_start,
                "line_end": component.line_end,
                
                # Parent information (safe access)
                "parent_name": parent_info.get("parent_name"),
                "parent_type": parent_info.get("parent_type"),
                
                # Nested information (safe access)
                "has_nested": nested_info.get("has_nested", False),
                "nested_count": nested_info.get("nested_count", 0),
                "nested_names": nested_info.get("nested_names", []),
                
                # Original indentation
                "original_indentation": component.metadata.get("original_indentation", 0)
            }
        }
        chunks.append(chunk)
    return chunks


def test_vector_store():
    """Test storing SAS components in Lab Vector Store."""
    parser = SASParser()
    chunk_store = SASChunkStore(collection_name="sas-python-collection")
    
    components = parser.parse_file("prd_mock_data/complex_sample.sas")
    
    print("\n=== Vector Store Test Results ===")
    for comp in components:
        print(f"\nComponent: {comp.name}")
        print(f"Parent: {comp.metadata['parent_info']['parent_name']}")
        print(f"Nested components: {comp.metadata['nested_info']['nested_names']}")
