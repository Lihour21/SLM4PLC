"""
Ollama4PLC RAG Module
=====================

Retrieval-Augmented Generation (RAG) integration for Ollama4PLC.
Uses local Ollama embeddings and vector store to retrieve relevant PLC code examples
from the OSCAT dataset (or any PLC code dataset) to improve ST code generation quality.

This module integrates with the main Ollama4PLC pipeline to provide:
1. Context-aware ST code generation with retrieved examples
2. Semantic search over PLC code libraries
3. Enhanced prompts with relevant code patterns

Dependencies:
    - langchain-chroma
    - langchain-community
    - langchain-core
    - chromadb

Usage:
    from rag_pipeline import Ollama4PLC_RAG

    rag = Ollama4PLC_RAG(
        db_dir="./database/st_db",
        dataset_paths=["./dataset/oscat_plc_code_793.json"],
        embedding_model="nomic-embed-text",
        llm_model="mistral:7b"
    )

    # Generate with RAG context
    result = rag.generate_with_context(
        requirements="Create a motor start/stop control..."
    )
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

# LangChain imports
from langchain_chroma import Chroma
from langchain_community.document_loaders import (
    PyPDFLoader, 
    JSONLoader, 
    DirectoryLoader,
    TextLoader
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.llms import Ollama
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.prompts import PromptTemplate

# Configure logging
logger = logging.getLogger(__name__)


class Ollama4PLC_RAG:
    """
    RAG-enhanced pipeline for Ollama4PLC.

    Provides semantic retrieval of PLC code examples to augment
    the LLM's ST code generation with relevant patterns and best practices.
    """

    def __init__(
        self,
        db_dir: str = "./database/st_db",
        dataset_paths: Optional[List[str]] = None,
        embedding_model: str = "nomic-embed-text",
        llm_model: str = "mistral:7b",
        ollama_base_url: str = "http://localhost:11434",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        top_k: int = 3
    ):
        """
        Initialize the RAG pipeline.

        Args:
            db_dir: Directory to store/load the Chroma vector database
            dataset_paths: List of paths to PLC code datasets (JSON, PDF, ST files, directories)
            embedding_model: Ollama embedding model name (default: nomic-embed-text)
            llm_model: Ollama LLM model name for generation (default: mistral:7b)
            ollama_base_url: Ollama API base URL
            chunk_size: Text splitter chunk size
            chunk_overlap: Text splitter chunk overlap
            top_k: Number of retrieved documents to include in context
        """
        self.db_dir = Path(db_dir).resolve()
        self.dataset_paths = dataset_paths or []
        self.embedding_model = embedding_model
        self.llm_model = llm_model
        self.ollama_base_url = ollama_base_url
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.top_k = top_k

        # Initialize components
        self._embedding = None
        self._vectorstore = None
        self._retriever = None
        self._llm = None
        self._rag_chain = None

        logger.info(f"Ollama4PLC_RAG initialized with db_dir: {self.db_dir}")

    @property
    def embedding(self):
        """Lazy initialization of Ollama embeddings."""
        if self._embedding is None:
            logger.info(f"Initializing Ollama embeddings with model: {self.embedding_model}")
            self._embedding = OllamaEmbeddings(
                model=self.embedding_model,
                base_url=self.ollama_base_url
            )
        return self._embedding

    @property
    def llm(self):
        """Lazy initialization of Ollama LLM."""
        if self._llm is None:
            logger.info(f"Initializing Ollama LLM with model: {self.llm_model}")
            self._llm = Ollama(
                model=self.llm_model,
                base_url=self.ollama_base_url,
                temperature=0.1  # Low temperature for deterministic code generation
            )
        return self._llm

    def _load_directory_documents(self, directory_path: str) -> List[Any]:
        """Load documents from all files in a directory recursively."""
        logger.info(f"Loading documents from directory: {directory_path}")

        # Supported extensions for PLC code
        supported_patterns = [
            "**/*.st",      # Structured Text
            "**/*.iec",     # IEC files
            "**/*.plc",     # PLC files
            "**/*.txt",     # Text documentation
            "**/*.md",      # Markdown documentation
        ]

        all_docs = []
        for pattern in supported_patterns:
            try:
                loader = DirectoryLoader(
                    directory_path,
                    glob=pattern,
                    show_progress=True,
                    use_multithreading=True,
                    loader_cls=TextLoader
                )
                docs = loader.load()
                all_docs.extend(docs)
                logger.info(f"  Loaded {len(docs)} documents with pattern: {pattern}")
            except Exception as e:
                logger.warning(f"  Failed to load pattern {pattern}: {e}")

        return all_docs

    def _load_json_documents(self, json_path: str) -> List[Any]:
        """Load documents from a JSON dataset file (e.g., OSCAT format)."""
        logger.info(f"Loading JSON dataset: {json_path}")

        def metadata_func(record: dict, metadata: dict) -> dict:
            """Extract metadata from JSON records."""
            metadata["input"] = record.get("input", "")
            metadata["output"] = record.get("output", "")
            metadata["instruction"] = record.get("instruction", "")
            metadata["source"] = json_path
            return metadata

        try:
            # Try standard JSON format with instruction/response
            loader = JSONLoader(
                file_path=json_path,
                jq_schema='.[]',
                content_key="instruction",
                metadata_func=metadata_func
            )
            docs = loader.load()
            logger.info(f"  Loaded {len(docs)} documents from JSON")
            return docs
        except Exception as e:
            logger.warning(f"  Standard JSON load failed: {e}")

            # Fallback: Load as raw JSON and create documents manually
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                from langchain_core.documents import Document
                docs = []

                if isinstance(data, list):
                    for i, item in enumerate(data):
                        if isinstance(item, dict):
                            content = item.get("instruction", "") + "\n" + item.get("output", "")
                            docs.append(Document(
                                page_content=content,
                                metadata={
                                    "index": i,
                                    "source": json_path,
                                    **{k: v for k, v in item.items() if k not in ["instruction", "output"]}
                                }
                            ))

                logger.info(f"  Loaded {len(docs)} documents via fallback method")
                return docs
            except Exception as e2:
                logger.error(f"  Fallback JSON load also failed: {e2}")
                return []

    def _load_pdf_documents(self, pdf_path: str) -> List[Any]:
        """Load documents from a PDF file."""
        logger.info(f"Loading PDF: {pdf_path}")
        try:
            loader = PyPDFLoader(pdf_path)
            docs = loader.load()
            logger.info(f"  Loaded {len(docs)} pages from PDF")
            return docs
        except Exception as e:
            logger.error(f"  Failed to load PDF: {e}")
            return []

    def _load_st_file(self, st_path: str) -> List[Any]:
        """Load a single Structured Text file."""
        logger.info(f"Loading ST file: {st_path}")
        try:
            from langchain_core.documents import Document

            with open(st_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Extract program name for metadata
            program_match = __import__('re').search(r'PROGRAM\s+(\w+)', content, __import__('re').IGNORECASE)
            program_name = program_match.group(1) if program_match else "Unknown"

            doc = Document(
                page_content=content,
                metadata={
                    "source": st_path,
                    "program_name": program_name,
                    "file_type": "st"
                }
            )
            logger.info(f"  Loaded ST program: {program_name}")
            return [doc]
        except Exception as e:
            logger.error(f"  Failed to load ST file: {e}")
            return []

    def build_database(self, force_rebuild: bool = False) -> Chroma:
        """
        Build or load the vector database from dataset paths.

        Args:
            force_rebuild: If True, rebuild database even if it exists

        Returns:
            Chroma vector store instance
        """
        # Check if database already exists
        if not force_rebuild and self.db_dir.exists() and any(self.db_dir.iterdir()):
            logger.info(f"Loading existing vector database from: {self.db_dir}")
            self._vectorstore = Chroma(
                embedding_function=self.embedding,
                persist_directory=str(self.db_dir)
            )
            return self._vectorstore

        # Need to build database
        if not self.dataset_paths:
            raise ValueError("No dataset_paths provided. Cannot build database.")

        logger.info("Building new vector database...")

        # Load all documents
        all_docs = []
        for path in self.dataset_paths:
            path_obj = Path(path)

            if not path_obj.exists():
                logger.warning(f"Path does not exist: {path}")
                continue

            if path_obj.is_dir():
                docs = self._load_directory_documents(path)
            elif path_obj.suffix.lower() == ".json":
                docs = self._load_json_documents(path)
            elif path_obj.suffix.lower() == ".pdf":
                docs = self._load_pdf_documents(path)
            elif path_obj.suffix.lower() in [".st", ".iec", ".plc"]:
                docs = self._load_st_file(path)
            else:
                logger.warning(f"Unsupported file type: {path}")
                continue

            all_docs.extend(docs)

        if not all_docs:
            raise ValueError("No documents loaded. Check your dataset paths.")

        logger.info(f"Total documents loaded: {len(all_docs)}")

        # Split documents into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "END_PROGRAM", "END_VAR", "END_IF", ";", " ", ""]
        )

        splits = text_splitter.split_documents(all_docs)
        logger.info(f"Total chunks after splitting: {len(splits)}")

        # Create vector store
        self.db_dir.mkdir(parents=True, exist_ok=True)

        self._vectorstore = Chroma.from_documents(
            documents=splits,
            embedding=self.embedding,
            persist_directory=str(self.db_dir)
        )

        logger.info(f"Vector database built and saved at: {self.db_dir}")
        return self._vectorstore

    def get_retriever(self, search_kwargs: Optional[Dict] = None):
        """
        Get the document retriever from the vector store.

        Args:
            search_kwargs: Additional search parameters for retriever

        Returns:
            Configured retriever instance
        """
        if self._vectorstore is None:
            self.build_database()

        if self._retriever is None:
            kwargs = search_kwargs or {"k": self.top_k}
            self._retriever = self._vectorstore.as_retriever(search_kwargs=kwargs)
            logger.info(f"Retriever configured with top_k={kwargs.get('k', self.top_k)}")

        return self._retriever

    def retrieve_context(self, query: str, k: Optional[int] = None) -> List[str]:
        """
        Retrieve relevant PLC code examples for a given query.

        Args:
            query: The search query (e.g., requirements description)
            k: Number of results to retrieve (default: self.top_k)

        Returns:
            List of retrieved document contents
        """
        retriever = self.get_retriever(search_kwargs={"k": k or self.top_k})
        docs = retriever.invoke(query)

        logger.info(f"Retrieved {len(docs)} documents for query")
        return [doc.page_content for doc in docs]

    def _format_context(self, docs: List[Any]) -> str:
        """Format retrieved documents into context string."""
        return "\n\n---\n\n".join(
            f"[Example {i+1}]\n{doc.page_content}"
            for i, doc in enumerate(docs)
        )

    def generate_st_with_rag(
        self, 
        requirements: str,
        additional_properties: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate ST code using RAG-enhanced prompting.

        Retrieves relevant PLC code examples and includes them in the prompt
        to improve code generation quality.

        Args:
            requirements: Natural language requirements
            additional_properties: Optional LTL properties

        Returns:
            Tuple of (reasoning, generated_st_code)
        """
        logger.info("Generating ST code with RAG enhancement...")

        # Retrieve relevant examples
        try:
            retriever = self.get_retriever()
            retrieved_docs = retriever.invoke(requirements)
            context = self._format_context(retrieved_docs)
            logger.info(f"Retrieved {len(retrieved_docs)} relevant examples")
        except Exception as e:
            logger.warning(f"RAG retrieval failed: {e}. Falling back to standard generation.")
            context = "No relevant examples found in database."

        # Build enhanced prompt
        prompt_template = """
You are an expert PLC programmer following the IEC 61131-3 standard. 
Your PRIMARY TASK is to generate a COMPLETE and VALID Structured Text (ST) file.

CRITICAL REQUIREMENTS FOR RuSTy COMPILER:
- Use ONLY basic ST syntax: IF-THEN-ELSE, assignments (:=), AND, OR, NOT operators
- NO function blocks, NO timers, NO counters, NO advanced features
- Use only BOOL and INT types for simplicity
- Ensure all variables are properly declared
- Make the logic simple and sequential

Here are some relevant PLC code examples from the database to guide your implementation:

{context}

---

Now, generate ST code for the following requirements:

**Requirements:**
{requirements}

{properties_section}

You MUST include all necessary structural elements: PROGRAM MainProgram...END_PROGRAM, VAR_INPUT, VAR_OUTPUT, and VAR.

---REASONING--- 
1. **Objective:** Briefly state the main goal of the program. 
2. **Variable Identification:** List ALL required variables (Name: Type;). 
3. **Logic Formulation:** Describe the core control flow and logic. 

---CODE--- 
```st 
PROGRAM MainProgram
    VAR_INPUT 
        (* Input variables here *) 
    END_VAR 
    VAR_OUTPUT 
        (* Output variables here *) 
    END_VAR 
    VAR 
        (* Internal variables here *) 
    END_VAR 

    (* Implement basic logic here *) 

END_PROGRAM 
```
"""

        properties_section = ""
        if additional_properties:
            properties_section = f"\n**LTL Properties to Satisfy:**\n{additional_properties}"

        prompt = prompt_template.format(
            context=context,
            requirements=requirements,
            properties_section=properties_section
        )

        try:
            # Use direct Ollama API call (consistent with main app)
            import requests

            payload = {
                "model": self.llm_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1}
            }

            response = requests.post(
                f"{self.ollama_base_url}/api/generate",
                json=payload,
                timeout=300,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            full_response = response.json().get("response", "").strip()

            # Extract reasoning and code (same logic as main app)
            reasoning_part = None
            code_part = None

            import re
            code_match = re.search(r'```[sS][tT]?\s*\n(.*?)\n\s*```', full_response, re.DOTALL)
            if code_match:
                code_part = code_match.group(1).strip()

            if "---REASONING---" in full_response and "---CODE---" in full_response:
                try:
                    start_idx = full_response.index("---REASONING---") + len("---REASONING---")
                    end_idx = full_response.index("---CODE---")
                    reasoning_part = full_response[start_idx:end_idx].strip()
                except ValueError:
                    reasoning_part = full_response.split("---REASONING---")[-1].strip()

            return reasoning_part, code_part

        except Exception as e:
            logger.error(f"RAG generation failed: {e}")
            return None, f"Error: RAG generation failed: {e}"

    def chat_interface(self):
        """Interactive chat interface for testing RAG retrieval."""
        print("\n" + "="*50)
        print("🤖 Ollama4PLC RAG Chat Interface")
        print("="*50)
        print("Type your PLC requirements or questions.")
        print("Commands: 'exit' to quit, 'search <query>' to search only")
        print("="*50 + "\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not user_input:
                continue

            if user_input.lower() == "exit":
                print("Goodbye!")
                break

            if user_input.lower().startswith("search "):
                query = user_input[7:]
                print(f"\n🔍 Searching for: {query}")
                results = self.retrieve_context(query)
                for i, result in enumerate(results, 1):
                    print(f"\n--- Result {i} ---")
                    print(result[:500] + "..." if len(result) > 500 else result)
                continue

            print("\n🧠 Generating with RAG context...")
            reasoning, code = self.generate_st_with_rag(user_input)

            if reasoning:
                print(f"\n💭 Reasoning:\n{reasoning}")

            if code:
                print(f"\n📋 Generated ST Code:\n```st\n{code}\n```")
            else:
                print("\n❌ Failed to generate code.")


def main():
    """CLI entry point for building database and testing RAG."""
    import argparse

    parser = argparse.ArgumentParser(description="Ollama4PLC RAG Pipeline")
    parser.add_argument("--build", action="store_true", help="Build the vector database")
    parser.add_argument("--chat", action="store_true", help="Start interactive chat")
    parser.add_argument("--dataset", nargs="+", default=["./dataset/oscat_plc_code_793.json"],
                       help="Path(s) to dataset files or directories")
    parser.add_argument("--db-dir", default="./database/st_db", help="Vector database directory")
    parser.add_argument("--embedding-model", default="nomic-embed-text", help="Ollama embedding model")
    parser.add_argument("--llm-model", default="mistral:7b", help="Ollama LLM model")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama base URL")

    args = parser.parse_args()

    # Initialize RAG
    rag = Ollama4PLC_RAG(
        db_dir=args.db_dir,
        dataset_paths=args.dataset,
        embedding_model=args.embedding_model,
        llm_model=args.llm_model,
        ollama_base_url=args.ollama_url
    )

    if args.build:
        rag.build_database(force_rebuild=True)
        print(f"\n✅ Database built successfully at: {args.db_dir}")

    if args.chat:
        rag.chat_interface()

    if not args.build and not args.chat:
        # Default: build if needed, then chat
        try:
            rag.build_database()
        except ValueError:
            print("No existing database found. Use --build to create one.")
            return
        rag.chat_interface()


if __name__ == "__main__":
    main()
