# RAG (Retrieval-Augmented Generation) Guide

## Overview

The RAG module enhances Ollama4PLC by retrieving relevant PLC code examples from a vector database
to improve the quality and accuracy of generated Structured Text (ST) code.

## How It Works

```
User Requirements ──▶ Semantic Search ──▶ Retrieve Examples ──▶ Enhanced Prompt ──▶ LLM ──▶ Better ST Code
                          │                      │
                          ▼                      ▼
                    Vector Database      PLC Code Examples
                    (Chroma + Ollama     (OSCAT, custom
                     Embeddings)          libraries)
```

## Architecture

### Components

1. **Vector Store (Chroma)**: Stores embedded PLC code chunks
2. **Ollama Embeddings**: `nomic-embed-text` for semantic encoding
3. **Retriever**: Similarity search to find relevant examples
4. **Prompt Enhancer**: Injects retrieved examples into generation prompt

### Data Flow

1. **Indexing Phase** (one-time setup):
   - Load PLC code datasets (JSON, ST files, PDFs)
   - Split into semantic chunks
   - Embed using Ollama `nomic-embed-text`
   - Store in Chroma vector database

2. **Retrieval Phase** (per request):
   - Embed user requirements
   - Search vector store for similar code patterns
   - Retrieve top-k most relevant examples

3. **Generation Phase**:
   - Combine retrieved examples with requirements
   - Send enhanced prompt to LLM
   - Generate contextually informed ST code

## Setup

### 1. Install RAG Dependencies

```bash
pip install -r requirements-rag.txt
```

Or install individually:
```bash
pip install langchain langchain-chroma langchain-community chromadb pypdf
```

### 2. Prepare Your Dataset

The RAG system supports multiple data formats:

#### JSON Dataset (OSCAT format)

```json
[
  {
    "instruction": "Create a motor control with start/stop logic",
    "input": "Inputs: Start, Stop. Outputs: Motor",
    "output": "PROGRAM MotorControl\n  VAR_INPUT\n    Start : BOOL;\n    Stop : BOOL;\n  END_VAR\n  ..."
  }
]
```

#### ST Files Directory

Organize `.st` files in a directory:
```
dataset/
├── motor_control.st
├── traffic_light.st
├── conveyor_belt.st
└── ...
```

#### PDF Documentation

PLC programming manuals or reference guides in PDF format.

### 3. Build the Vector Database

```bash
# Using the CLI
python rag_pipeline.py --build \
  --dataset ./dataset/oscat_plc_code_793.json \
  --db-dir ./database/st_db

# Or programmatically
from rag_pipeline import Ollama4PLC_RAG

rag = Ollama4PLC_RAG(
    db_dir="./database/st_db",
    dataset_paths=["./dataset/oscat_plc_code_793.json"],
    embedding_model="nomic-embed-text"
)
rag.build_database()
```

### 4. Configure RAG in Ollama4PLC

Edit `config.json`:

```json
{
  "llm_model": "mistral:7b",
  "api_base_url": "http://localhost:11434",
  "rag": {
    "enabled": true,
    "db_dir": "./database/st_db",
    "dataset_paths": ["./dataset/oscat_plc_code_793.json"],
    "embedding_model": "nomic-embed-text",
    "top_k": 3
  }
}
```

### 5. Run with RAG

```bash
# Use the RAG-enhanced application
python app_rag.py

# Or use standard app (RAG disabled by default)
python app.py
```

## Configuration Options

### RAG Section in config.json

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | false | Enable/disable RAG |
| `db_dir` | string | "./database/st_db" | Vector database directory |
| `dataset_paths` | list | [] | Paths to datasets |
| `embedding_model` | string | "nomic-embed-text" | Ollama embedding model |
| `top_k` | int | 3 | Number of retrieved examples |
| `chunk_size` | int | 1000 | Text splitter chunk size |
| `chunk_overlap` | int | 200 | Chunk overlap for continuity |

### Recommended Embedding Models

| Model | Size | Speed | Quality | Best For |
|-------|------|-------|---------|----------|
| `nomic-embed-text` | ~500MB | Fast | Good | General PLC code |
| `all-minilm` | ~100MB | Very Fast | Moderate | Quick prototyping |
| `mxbai-embed-large` | ~1GB | Moderate | Excellent | Production use |

## Usage Examples

### Interactive Chat

```bash
python rag_pipeline.py --chat --db-dir ./database/st_db
```

### Search Only

```bash
# In chat mode, type:
search motor control with emergency stop
```

### API Usage

```python
from rag_pipeline import Ollama4PLC_RAG

rag = Ollama4PLC_RAG(db_dir="./database/st_db")
rag.build_database()

# Generate with context
reasoning, code = rag.generate_st_with_rag(
    requirements="Create a conveyor belt control with item counting"
)

# Just search
examples = rag.retrieve_context("motor start stop logic", k=5)
for ex in examples:
    print(ex[:200])
```

## Performance Tips

### Database Optimization

1. **Pre-filter by program type**:
   ```python
   retriever = vectorstore.as_retriever(
       search_kwargs={
           "k": 3,
           "filter": {"file_type": "st"}
       }
   )
   ```

2. **Use MMR (Maximal Marginal Relevance)** for diverse results:
   ```python
   retriever = vectorstore.as_retriever(
       search_type="mmr",
       search_kwargs={"k": 3, "lambda_mult": 0.5}
   )
   ```

### Memory Management

For large datasets (>10,000 programs):

```python
# Use batched indexing
rag = Ollama4PLC_RAG(
    chunk_size=500,  # Smaller chunks
    chunk_overlap=50
)

# Clear memory after building
import gc
gc.collect()
```

## Troubleshooting

### "No documents found in database"

**Cause**: Database not built or empty dataset

**Solution**:
```bash
# Rebuild database
python rag_pipeline.py --build --dataset ./your_dataset.json

# Verify contents
python -c "
from rag_pipeline import Ollama4PLC_RAG
rag = Ollama4PLC_RAG(db_dir='./database/st_db')
rag.build_database()
print(f'Documents: {rag._vectorstore._collection.count()}')
"
```

### "Embedding model not found"

**Cause**: Ollama doesn't have the embedding model

**Solution**:
```bash
ollama pull nomic-embed-text
# or
ollama pull all-minilm
```

### Slow retrieval

**Cause**: Large database or slow embedding model

**Solutions**:
1. Use smaller embedding model: `all-minilm`
2. Reduce `chunk_size` to create fewer chunks
3. Use SSD for database storage
4. Pre-load embedding model into memory

### Poor quality retrieved examples

**Cause**: Mismatch between query and indexed content

**Solutions**:
1. Add more diverse examples to dataset
2. Tune `chunk_size` and `chunk_overlap`
3. Use query expansion:
   ```python
   # Expand simple queries
   expanded_query = f"PLC code for: {requirements}"
   examples = rag.retrieve_context(expanded_query)
   ```

## Advanced Features

### Custom Document Loaders

Add support for additional formats:

```python
from rag_pipeline import Ollama4PLC_RAG

class MyCustomLoader:
    def load(self, path):
        # Your loading logic
        return documents

rag = Ollama4PLC_RAG()
# Extend _load methods in subclass
```

### Hybrid Search

Combine semantic + keyword search:

```python
from langchain.retrievers import BM25Retriever, EnsembleRetriever

# Create BM25 retriever
bm25_retriever = BM25Retriever.from_documents(docs)
bm25_retriever.k = 2

# Create semantic retriever
semantic_retriever = vectorstore.as_retriever(search_kwargs={"k": 2})

# Ensemble
ensemble = EnsembleRetriever(
    retrievers=[bm25_retriever, semantic_retriever],
    weights=[0.5, 0.5]
)
```

### Fine-tuned Embeddings

For domain-specific PLC code:

```bash
# Train custom embedding model (advanced)
# Requires labeled PLC code similarity data
```

## Integration with Main Pipeline

The RAG-enhanced engine (`Ollama4PLC_RAG_Engine`) seamlessly integrates with
all existing Ollama4PLC features:

- ✅ ST code generation with context
- ✅ RuSTy compilation
- ✅ SMV translation
- ✅ nuXmv verification
- ✅ PLCverif verification
- ✅ Web interface
- ✅ Downloadable outputs

Enable RAG by setting `"rag.enabled": true` in `config.json`.
