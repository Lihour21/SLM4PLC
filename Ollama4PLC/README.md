# Ollama4PLC 🤖⚙️

> **AI-Powered IEC 61131-3 Structured Text (ST) Code Generation & Formal Verification Pipeline**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Ollama](https://img.shields.io/badge/ollama-local%20LLM-green.svg)](https://ollama.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Ollama4PLC is a complete pipeline that uses **local Large Language Models (via Ollama)** to generate IEC 61131-3 Structured Text (ST) code for Programmable Logic Controllers (PLCs), then compiles it with **RuSTy**, translates it to **SMV** format, and performs formal verification using **nuXmv** and **PLCverif**.

## 🎯 Features

- **🧠 AI Code Generation**: Uses local LLMs (Mistral, Llama, CodeLlama, etc.) via Ollama to generate ST code from natural language requirements
- **🔧 ST Compilation**: Compiles generated ST code to LLVM IR using the RuSTy compiler
- **🔄 SMV Translation**: Automatically translates ST logic to SMV (Symbolic Model Verification) format
- **✅ Formal Verification**: Verifies safety and liveness properties using nuXmv model checker
- **🌐 Web Interface**: Clean Flask-based UI for submitting requirements and viewing results
- **📊 Pipeline Dashboard**: Visual step-by-step progress tracking with detailed logs
- **🔒 Privacy-First**: All processing happens locally — no data leaves your machine
- **📊 Automated Evaluation**: Built-in verification via PLCverif or SMV/nuXmv model checking

## 🏗️ Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   User Input    │────▶│  Ollama (LLM)   │────▶│   ST Code Gen   │
│  (Requirements) │     │  Local Model    │     │  IEC 61131-3    │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                    ┌────────────────────────────────────┼────────────────────────────────────┐
                    │                                    │                                    │
                    ▼                                    ▼                                    ▼
           ┌─────────────────┐                 ┌─────────────────┐                 ┌─────────────────┐
           │  RuSTy Compiler │                 │  SMV Translator │                 │  PLCverif Tool  │
           │  ST → LLVM IR   │                 │  ST → SMV Model │                 │  ST Verification│
           └────────┬────────┘                 └────────┬────────┘                 └─────────────────┘
                    │                                    │
                    ▼                                    ▼
           ┌─────────────────┐                 ┌─────────────────┐
           │   LLVM IR File  │                 │  nuXmv Verifier │
           │   (.ll output)  │                 │  Model Checker  │
           └─────────────────┘                 └────────┬────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │ Verification    │
                                              │ Results (PASS/  │
                                              │ FAIL/Counterex)  │
                                              └─────────────────┘
```

## 📋 Prerequisites

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM | 8GB | 16GB+ |
| CPU | 4 cores | 8+ cores |
| GPU | Optional | NVIDIA with 8GB+ VRAM |
| Disk Space | 20GB | 50GB+ |

### Software Requirements

- **Python** 3.9 or higher
- **Ollama** (local LLM server)
- **RuSTy** (IEC 61131-3 ST compiler)
- **nuXmv** (symbolic model checker)
- **PLCverif** (PLC formal verification tool) — Optional

## 🚀 Quick Start

### Step 1: Install Ollama

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows
winget install Ollama.Ollama
```

Pull a model (we recommend Mistral 7B or CodeLlama for code generation):

```bash
ollama pull mistral:7b
# or
ollama pull codellama:7b
```

### Step 2: Install RuSTy Compiler

```bash
# Clone and build from source (requires Rust toolchain)
git clone https://github.com/PLC-lang/rusty.git
cd rusty
cargo build --release

# The binary will be at: target/release/plc
# Add to your PATH or configure in config.json
```

### Step 3: Install nuXmv

```bash
# Download from official site
wget https://nuxmv.fbk.eu/download/nuXmv-2.0.0-linux64.tar.gz
tar xzf nuXmv-2.0.0-linux64.tar.gz
sudo cp nuXmv-2.0.0-linux64/bin/nuXmv /usr/local/bin/
```

### Step 4: Install PLCverif (Optional)

```bash
# Download from CERN/PLCverif repository
# Follow their installation guide for your platform
```

### Step 5: Install Ollama4PLC

```bash
# Clone the repository
git clone https://github.com/yourusername/ollama4plc.git
cd ollama4plc

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure the application
cp config.example.json config.json
# Edit config.json with your tool paths

# Run the application
python app.py
```

Open your browser and navigate to `http://localhost:8000`

## ⚙️ Configuration

Edit `config.json` to match your system:

```json
{
    "llm_model": "mistral:7b",
    "api_base_url": "http://localhost:11434",
    "api_key": "ollama",
    "plcverif_path": "~/plcverif/plcverif-cli",
    "rusty_path": "~/rusty/target/release/plc",
    "nuxmv_path": "/usr/local/bin/nuXmv",
    "output_dir": "output",
    "timeout": 300
}
```

## 🖥️ Usage

### Web Interface

1. Open `http://localhost:8000` in your browser
2. Enter your PLC requirements in natural language
3. (Optional) Add LTL properties for formal verification
4. Click **"Generate & Verify"**
5. View the complete pipeline results with downloadable ST files

### Example Requirements

```
Create ST code for a simple start/stop motor control.
Inputs: Start_PB, Stop_PB. Outputs: Motor_Run.
Logic: Pressing Start_PB turns on Motor_Run, which stays on until Stop_PB is pressed.
```

### Example LTL Properties

```
(*! LTL G (Motor_Run -> F !Stop_PB) *)
(*! LTL G !(Motor_Run & Stop_PB) *)
```

### API Usage

```python
import requests

response = requests.post('http://localhost:8000/process', data={
    'requirements': 'Create a traffic light controller with 3 states...',
    'plcverif_properties': '(*! LTL G !(Red & Green) *)'
})
```

## 📁 Project Structure

```
ollama4plc/
├── app.py                 # Main Flask application
├── config.json            # Application configuration
├── requirements.txt       # Python dependencies
├── README.md             # This file
├── LICENSE               # MIT License
├── .gitignore            # Git ignore rules
├── templates/            # HTML templates
│   ├── index.html        # Main input form
│   └── results.html      # Results dashboard
├── static/               # Static assets
│   ├── css/
│   │   └── style.css     # Custom styles
│   └── js/
│       └── main.js       # Frontend logic
├── examples/             # Example ST programs
│   ├── motor_control.st
│   ├── traffic_light.st
│   └── conveyor_belt.st
├── tests/                # Unit tests
│   ├── test_generation.py
│   ├── test_compiler.py
│   └── test_verification.py
├── evaluate/             # Evaluation modules
│   ├── plcverif_evaluation.py  # Direct PLCverif verification
│   ├── smv_evaluation.py       # LLM-assisted SMV + nuXmv
│   ├── pretty_summary.py       # Statistics formatting
│   └── README.md
├── docs/                 # Documentation
│   ├── INSTALL.md        # Detailed installation
│   ├── API.md            # API documentation
│   └── TROUBLESHOOTING.md
└── scripts/              # Setup scripts
    ├── install_linux.sh
    ├── install_macos.sh
    └── install_windows.ps1
```

## 🧪 Testing

```bash
# Run all tests
pytest tests/

# Run specific test suite
pytest tests/test_generation.py -v

# Run with coverage
pytest --cov=. tests/
```

## 🛠️ Development

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run linter
flake8 app.py

# Run type checker
mypy app.py

# Format code
black app.py
```

## 🐳 Docker Deployment

```bash
# Build the image
docker build -t ollama4plc .

# Run with Ollama on host network
docker run -p 8000:8000 --network host ollama4plc

# Or use docker-compose
docker-compose up -d
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Ollama](https://ollama.com) — Local LLM runtime
- [RuSTy](https://github.com/PLC-lang/rusty) — IEC 61131-3 ST compiler
- [nuXmv](https://nuxmv.fbk.eu) — Symbolic model checker
- [PLCverif](https://github.com/PLCverif/PLCverif) — PLC formal verification
- [Flask](https://flask.palletsprojects.com) — Web framework

## 📧 Support

- 📖 [Documentation](docs/)
- 🐛 [Issue Tracker](../../issues)
- 💬 [Discussions](../../discussions)

---

**Made with ❤️ for the industrial automation community**
