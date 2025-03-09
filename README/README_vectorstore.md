# Vector Store Architecture for SAS Parser

## Overview
This document outlines the vector store embedding collection structure used in the SAS parser for storing and organizing code embeddings. The architecture supports efficient code pattern matching, template identification, and contextual understanding of SAS code components.

## Collection Architecture

### Multiple Collections Approach (Current Design)
The vector store is organized into specialized collections:

1. **Collection Types**:
   - PROC Collection
   - DATA Step Collection
   - SQL Collection
   - Macro Collection
   - Global Collection (for overall context)

2. **Collection Structure**:
   ```
   Collection
   ├── Embeddings (vector representations)
   ├── Metadata
   │   ├── Line numbers
   │   ├── File source
   │   ├── Code type
   │   └── Context information
   ├── Documents (original code)
   └── IDs (unique identifiers)
   ```

3. **Hierarchical Organization**:
   ```
   Vector Store
   ├── PROC Collection
   │   ├── SQL statements
   │   ├── MEANS procedures
   │   └── Other PROC types
   │
   ├── DATA Collection
   │   ├── Data step declarations
   │   ├── Transformations
   │   └── Set operations
   │
   ├── SQL Collection
   │   ├── Select statements
   │   ├── Join operations
   │   └── Where clauses
   │
   └── Macro Collection
       ├── Macro definitions
       ├── Macro calls
       └── Macro variables
   ```

### Single Collection Approach (Challenges)

1. **Structure Issues**:
   ```
   Single Collection
   ├── Mixed Code Types
   │   ├── PROC statements
   │   ├── DATA steps
   │   ├── SQL queries
   │   └── Macros
   ├── Generic Metadata
   └── Undifferentiated Context
   ```

2. **Key Challenges**:
   - Search precision degradation
   - Context mixing between code types
   - Performance bottlenecks
   - Maintenance complexity
   - Scaling difficulties

## Benefits of Current Architecture

1. **Search Efficiency**:
   - Targeted collection searching
   - Better context awareness
   - More precise matching
   - Reduced false positives

2. **Performance**:
   - Smaller search spaces per query
   - Faster response times
   - Optimized memory usage
   - Better resource utilization

3. **Maintenance**:
   - Easy collection-specific updates
   - Clear separation of concerns
   - Simplified version control
   - Better error isolation

4. **Scalability**:
   - Independent collection scaling
   - Flexible growth management
   - Easier performance optimization
   - Better resource allocation

## Search/Query Flow 