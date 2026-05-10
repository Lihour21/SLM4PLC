import os
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader, JSONLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Swapped OpenAI for local Ollama imports
from langchain_community.llms import Ollama
from langchain_community.embeddings import OllamaEmbeddings

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.prompts import PromptTemplate
import json
import sys
from pathlib import Path

# Note: You no longer need the config.py file since there are no API keys required!

def load_directory_documents(directory_path):
    """Load documents from all files in a directory recursively."""
    text_loader = DirectoryLoader(
        directory_path,
        glob="**/*.*",
        show_progress=True,
        use_multithreading=True
    )
    return text_loader.load()

def load_json_documents(json_path):
    """Load documents from a JSON file."""
    def metadata_func(record: dict, metadata: dict) -> dict:
        metadata["input"] = record.get("input")
        metadata["output"] = record.get("output")
        return metadata

    json_loader = JSONLoader(
        file_path=json_path,
        jq_schema='.[]',
        content_key="instruction",
        metadata_func=metadata_func
    )
    return json_loader.load()

def load_pdf_documents(pdf_path):
    """Load documents from a PDF file using PyPDFLoader."""
    pdf_loader = PyPDFLoader(pdf_path)
    return pdf_loader.load()

def generate_database(file_paths, db_dir):
    """
    Generate a vectorstore database locally using Ollama Embeddings.
    """
    # Initialize LOCAL embeddings
    embedding = OllamaEmbeddings(
        model="nomic-embed-text" # Efficient local embedding model
    )
    
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

    all_splits = []
    for file_path in file_paths:
        path = Path(file_path)
        if path.is_dir():
            documents = load_directory_documents(file_path)
        elif path.suffix.lower() == ".json":
            documents = load_json_documents(file_path)
        elif path.suffix.lower() == ".pdf":
            documents = load_pdf_documents(file_path)
        else:
            print(f"Unsupported file type: {file_path}")
            continue

        splits = text_splitter.split_documents(documents)
        all_splits.extend(splits)
    
    if not os.path.exists(db_dir):
        vectorstore = Chroma.from_documents(
            documents=all_splits,
            embedding=embedding,
            persist_directory=db_dir
        )
    else:
        vectorstore = Chroma(
            embedding_function=embedding,
            persist_directory=db_dir
        )
    
    print(f"Database generated and saved at: {db_dir}")
    return vectorstore

def get_rag_model(db_dir):
    """Retrieve and configure the local RAG model."""
    
    # Initialize the local LLM targeting your finetuned model
    llm = Ollama(
        model="codellama-ft-ollama4plc" # Or whichever small model you are using for the final run
    )

    # Initialize local embeddings
    embedding = OllamaEmbeddings(
        model="nomic-embed-text"
    )

    if os.path.exists(db_dir):
        vectorstore = Chroma(
            embedding_function=embedding,
            persist_directory=db_dir
        )
        print(f"Loaded vectorstore from: {db_dir}")
    else:
        raise FileNotFoundError(f"Database not found at {db_dir}")

    retriever = vectorstore.as_retriever()

    prompt = PromptTemplate.from_template(
        """
        You are an expert PLC programmer. Answer the user's question based on the retrieved context.
        Context: \n{context} \n
        Question: \n {question} \n
        Answer:
        """
    )

    rag_chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    return rag_chain

def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

if __name__ == "__main__":
    # Update these paths to match your local Windows/Linux environment
    dataset_directory = "./dataset/oscat_plc_code_793.json"
    db_dir = "./database/st_db"

    # Generate or load the database
    generate_database([dataset_directory], db_dir)
    
    # Load the RAG model
    rag_chain = get_rag_model(db_dir)

    def chat():
        print("Local RAG Chat initialized - type 'exit' to quit")
        while True:
            question = input("You: ")
            if question.lower() == "exit":
                print("Goodbye!")
                break
            
            print("Thinking...")
            answer = rag_chain.invoke(question)
            print(f"Ollama4PLC: {answer}\n")

    chat()
