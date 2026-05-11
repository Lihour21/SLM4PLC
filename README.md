# SLM4PLC , Ollama4PLC
SLM4PLC is a high-assurance framework for the automated generation and formal verification of IEC 61131-3 Structured Text (ST).

# Local-chatbot

This project leverages SLM4PLC and Chainlit to create a 100% locally running mini-Chatbot.

# Installation and setup

**Setup Ollama:**

setup ollama on linux
```bash
curl -fsSL [https://ollama.com/install.sh](https://ollama.com/install.sh) | sh
```
pull the deepseek-coder:6.7b, codellama:7b, mistral:7b, phi3:3.8b, gemma4:e4b
```
ollama pull deepseek-coder:6.7b
```
Install Dependencies: Ensure you have Python 3.11 or later installed.
```
pip install pydantic==2.10.1 chainlit ollama
```
Run the app:

Run the chainlit app as follows:
```
chainlit run app.py -w
```
