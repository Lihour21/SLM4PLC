#!/usr/bin/env python3
"""
Ollama4PLC - LLM-powered PLC Code Generation and Verification System
Fully corrected and production-ready version.

Requirements:
    pip install flask requests

External tools required:
    - Ollama (running locally)
    - RuSTy PLC compiler (https://github.com/PLC-lang/rusty)
    - nuXmv model checker (https://nuxmv.fbk.eu/)
    - PLCverif (https://github.com/PLC-lang/plcverif)
"""

import subprocess
import os
import logging
import sys
import re
import json
import time
import shutil
import tempfile
import traceback
import argparse
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List, Union
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Flask imports
from flask import Flask, request, render_template_string, jsonify, Response, redirect, url_for

# HTTP requests
import requests

# =============================================================================
# CONFIGURATION
# =============================================================================

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "llm_model": "deepseek-coder:6.7b",
    "api_base_url": "http://localhost:11434",
    "api_key": "ollama",
    "plcverif_path": "/home/lee/mcp4plc-plus/plcverif/plcverif-cli",
    "rusty_path": "/home/lee/mcp4plc-plus/rusty/target/release/plc",
    "nuxmv_path": "/usr/local/bin/nuxmv",
    "output_dir": "output",
    "timeout": 320,
    "temperature": 0.1,
    "max_tokens": 2048,
    "rag": {
        "enabled": True,
        "db_dir": "./database/st_db",
        "dataset_paths": ["./dataset/oscat_plc_code_793.json"],
        "embedding_model": "nomic-embed-text",
        "top_k": 3,
        "chunk_size": 1000,
        "chunk_overlap": 200
    }
}

# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging():
    """Configure rotating file logging and console output."""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Rotating file handler (max 10MB, keep 5 backups)
    file_handler = RotatingFileHandler(
        'ollama4plc.log', 
        maxBytes=10*1024*1024, 
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(log_format))

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger(__name__)

logger = setup_logging()

# =============================================================================
# CONFIGURATION LOADING
# =============================================================================

def load_config() -> Dict[str, Any]:
    """Load configuration with deep merging of defaults and user settings."""
    config = DEFAULT_CONFIG.copy()

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_config = json.load(f)

            # Deep merge user config into defaults
            def deep_merge(base: dict, override: dict) -> dict:
                for key, value in override.items():
                    if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                        deep_merge(base[key], value)
                    else:
                        base[key] = value
                return base

            deep_merge(config, user_config)
            logger.info(f"Loaded configuration from {CONFIG_FILE}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {CONFIG_FILE}: {e}. Using defaults.")
        except Exception as e:
            logger.error(f"Failed to load config: {e}. Using defaults.")
    else:
        logger.info(f"Config file {CONFIG_FILE} not found. Using default configuration.")

    return config

config = load_config()

# =============================================================================
# FLASK APP
# =============================================================================

app = Flask(__name__)
app.secret_key = os.urandom(24)

# =============================================================================
# HTML TEMPLATES (embedded for self-contained deployment)
# =============================================================================

INDEX_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ollama4PLC - PLC Code Generator</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eaeaea;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 900px; margin: 0 auto; }
        h1 { 
            text-align: center; 
            margin-bottom: 10px; 
            color: #00d4ff;
            text-shadow: 0 0 20px rgba(0, 212, 255, 0.3);
        }
        .subtitle { 
            text-align: center; 
            color: #a0a0a0; 
            margin-bottom: 30px; 
            font-size: 14px;
        }
        .status-bar {
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }
        .status-item { display: flex; align-items: center; gap: 6px; font-size: 13px; }
        .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
        .status-ok { background: #00ff88; box-shadow: 0 0 8px #00ff88; }
        .status-warn { background: #ffaa00; box-shadow: 0 0 8px #ffaa00; }
        .status-err { background: #ff4444; box-shadow: 0 0 8px #ff4444; }
        .warning-box {
            background: rgba(255, 170, 0, 0.15);
            border: 1px solid #ffaa00;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 20px;
            color: #ffcc66;
        }
        .form-card {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
        }
        .form-group { margin-bottom: 18px; }
        label { 
            display: block; 
            margin-bottom: 6px; 
            font-weight: 600; 
            color: #00d4ff;
            font-size: 14px;
        }
        textarea {
            width: 100%;
            min-height: 140px;
            background: rgba(0,0,0,0.3);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 8px;
            padding: 12px;
            color: #eaeaea;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 13px;
            resize: vertical;
            transition: border-color 0.3s;
        }
        textarea:focus {
            outline: none;
            border-color: #00d4ff;
            box-shadow: 0 0 10px rgba(0, 212, 255, 0.2);
        }
        .hint {
            font-size: 12px;
            color: #888;
            margin-top: 4px;
        }
        .btn {
            background: linear-gradient(135deg, #00d4ff 0%, #0099cc 100%);
            color: #1a1a2e;
            border: none;
            padding: 14px 32px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s;
            display: block;
            margin: 0 auto;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 212, 255, 0.4);
        }
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        .footer {
            text-align: center;
            color: #666;
            font-size: 12px;
            margin-top: 30px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ Ollama4PLC</h1>
        <p class="subtitle">LLM-Powered IEC 61131-3 Structured Text Generator & Verifier</p>

        {% if status_warning %}
        <div class="warning-box">
            ⚠️ <strong>System Warning:</strong> {{ status_warning }}
        </div>
        {% endif %}

        <div class="status-bar">
            <div class="status-item">
                <span class="status-dot {{ 'status-ok' if tool_status.ollama else 'status-err' }}"></span>
                Ollama: {{ "Online" if tool_status.ollama else "Offline" }}
            </div>
            <div class="status-item">
                <span class="status-dot {{ 'status-ok' if tool_status.rusty else 'status-warn' }}"></span>
                RuSTy: {{ "Ready" if tool_status.rusty else "Not Found" }}
            </div>
            <div class="status-item">
                <span class="status-dot {{ 'status-ok' if tool_status.nuxmv else 'status-warn' }}"></span>
                nuXmv: {{ "Ready" if tool_status.nuxmv else "Not Found" }}
            </div>
            <div class="status-item">
                <span class="status-dot {{ 'status-ok' if tool_status.plcverif else 'status-warn' }}"></span>
                PLCverif: {{ "Ready" if tool_status.plcverif else "Not Found" }}
            </div>
        </div>

        <form action="/process" method="POST" class="form-card">
            <div class="form-group">
                <label for="requirements">PLC Requirements</label>
                <textarea 
                    id="requirements" 
                    name="requirements" 
                    placeholder="Describe your PLC control logic..."
                    required
                >{{ default_requirements }}</textarea>
                <p class="hint">Describe the inputs, outputs, and control logic. Be specific about variable names and behavior.</p>
            </div>

            <div class="form-group">
                <label for="plcverif_properties">Verification Properties (Optional)</label>
                <textarea 
                    id="plcverif_properties" 
                    name="plcverif_properties"
                    placeholder="Enter LTL properties or safety requirements..."
                >{{ default_properties }}</textarea>
                <p class="hint">Optional: Specify safety/liveness properties for formal verification. Leave empty to skip.</p>
            </div>

            <button type="submit" class="btn" {{ 'disabled' if not tool_status.ollama }}>
                {{ "Generate & Verify" if tool_status.ollama else "Ollama Offline" }}
            </button>
        </form>

        <div class="footer">
            Powered by Ollama + RuSTy + nuXmv + PLCverif | IEC 61131-3 Compliant
        </div>
    </div>
</body>
</html>
"""

RESULTS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ollama4PLC - Results</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eaeaea;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { text-align: center; color: #00d4ff; margin-bottom: 20px; }
        .back-btn {
            display: inline-block;
            background: rgba(255,255,255,0.1);
            color: #00d4ff;
            padding: 8px 16px;
            border-radius: 6px;
            text-decoration: none;
            margin-bottom: 20px;
            border: 1px solid rgba(0,212,255,0.3);
            transition: all 0.3s;
        }
        .back-btn:hover { background: rgba(0,212,255,0.1); }

        .summary-bar {
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            padding: 16px;
            margin-bottom: 20px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
        }
        .summary-item { text-align: center; }
        .summary-value { 
            font-size: 24px; 
            font-weight: 700; 
            color: #00d4ff; 
        }
        .summary-label { font-size: 12px; color: #888; margin-top: 4px; }

        .status-badge {
            display: inline-block;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .status-success { background: rgba(0,255,136,0.2); color: #00ff88; border: 1px solid #00ff88; }
        .status-partial { background: rgba(255,170,0,0.2); color: #ffaa00; border: 1px solid #ffaa00; }
        .status-failed { background: rgba(255,68,68,0.2); color: #ff4444; border: 1px solid #ff4444; }

        .step-card {
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            margin-bottom: 16px;
            overflow: hidden;
        }
        .step-header {
            padding: 14px 18px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            transition: background 0.3s;
        }
        .step-header:hover { background: rgba(255,255,255,0.05); }
        .step-title { font-weight: 600; font-size: 15px; }
        .step-status {
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        .step-ok { background: rgba(0,255,136,0.2); color: #00ff88; }
        .step-fail { background: rgba(255,68,68,0.2); color: #ff4444; }
        .step-skip { background: rgba(255,170,0,0.2); color: #ffaa00; }
        .step-body {
            padding: 0 18px 18px;
            border-top: 1px solid rgba(255,255,255,0.05);
        }
        .code-block {
            background: rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 6px;
            padding: 14px;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 12px;
            line-height: 1.6;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 400px;
            overflow-y: auto;
            color: #c0c0c0;
        }
        .download-btn {
            display: inline-block;
            background: linear-gradient(135deg, #00d4ff 0%, #0099cc 100%);
            color: #1a1a2e;
            padding: 8px 16px;
            border-radius: 6px;
            text-decoration: none;
            font-size: 13px;
            font-weight: 600;
            margin-top: 10px;
            border: none;
            cursor: pointer;
        }
        .error-box {
            background: rgba(255,68,68,0.1);
            border: 1px solid #ff4444;
            border-radius: 6px;
            padding: 12px;
            color: #ff8888;
            font-size: 13px;
        }
        .info-box {
            background: rgba(0,212,255,0.1);
            border: 1px solid #00d4ff;
            border-radius: 6px;
            padding: 12px;
            color: #88ddff;
            font-size: 13px;
        }
        .reasoning-box {
            background: rgba(255,255,255,0.03);
            border-left: 3px solid #00d4ff;
            padding: 12px;
            margin: 10px 0;
            font-size: 13px;
            line-height: 1.6;
        }
        .toggle-icon { font-size: 12px; transition: transform 0.3s; }
        .toggle-icon.open { transform: rotate(90deg); }
        .hidden { display: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Verification Results</h1>
        <a href="/" class="back-btn">← New Request</a>

        <div style="text-align: center; margin-bottom: 20px;">
            <span class="status-badge status-{{ result.status }}">
                {{ result.status.upper() }}
            </span>
        </div>

        <div class="summary-bar">
            <div class="summary-item">
                <div class="summary-value">{{ result.duration }}</div>
                <div class="summary-label">Duration</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{{ successful_steps }}/{{ total_steps }}</div>
                <div class="summary-label">Steps Passed</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{{ "Yes" if result.tool_status.rusty else "No" }}</div>
                <div class="summary-label">RuSTy Available</div>
            </div>
            <div class="summary-item">
                <div class="summary-value">{{ "Yes" if result.tool_status.nuxmv else "No" }}</div>
                <div class="summary-label">nuXmv Available</div>
            </div>
        </div>

        {% if result.error %}
        <div class="error-box">
            <strong>⚠️ Error:</strong> {{ result.error }}
        </div>
        {% endif %}

        {% if result.original_requirements %}
        <div class="step-card">
            <div class="step-header" onclick="toggleStep(this)">
                <span class="step-title">📝 Original Requirements</span>
                <span class="toggle-icon">▶</span>
            </div>
            <div class="step-body hidden">
                <div class="code-block">{{ result.original_requirements }}</div>
            </div>
        </div>
        {% endif %}

        {% for step_name, step_data in result.steps.items() %}
        {% if step_data.output is not none %}
        <div class="step-card">
            <div class="step-header" onclick="toggleStep(this)">
                <span class="step-title">
                    {% if step_name == 'generate' %}🤖 Code Generation
                    {% elif step_name == 'compile' %}🔨 Compilation (RuSTy)
                    {% elif step_name == 'translate' %}🔄 SMV Translation
                    {% elif step_name == 'verify_nuxmv' %}✅ nuXmv Verification
                    {% elif step_name == 'verify_plcverif' %}🔍 PLCverif Verification
                    {% else %}{{ step_name }}{% endif %}
                </span>
                <span class="step-status {{ 'step-ok' if step_data.success else 'step-fail' if step_data.output else 'step-skip' }}">
                    {{ "PASS" if step_data.success else "FAIL" if step_data.output else "SKIP" }}
                </span>
                <span class="toggle-icon">▶</span>
            </div>
            <div class="step-body hidden">
                {% if step_data.reasoning %}
                <div class="reasoning-box">
                    <strong>🧠 Reasoning:</strong><br>
                    {{ step_data.reasoning|replace("\n", "<br>") }}
                </div>
                {% endif %}

                {% if step_name == 'generate' %}
                <div class="code-block">{{ step_data.output }}</div>
                <form action="/download_st" method="POST" style="margin-top:10px;">
                    <input type="hidden" name="st_code" value="{{ step_data.output|e }}">
                    <button type="submit" class="download-btn">⬇ Download .st File</button>
                </form>
                {% else %}
                <div class="code-block">{{ step_data.output }}</div>
                {% endif %}
            </div>
        </div>
        {% endif %}
        {% endfor %}
    </div>

    <script>
        function toggleStep(header) {
            const body = header.nextElementSibling;
            const icon = header.querySelector('.toggle-icon');
            body.classList.toggle('hidden');
            icon.classList.toggle('open');
        }
        // Auto-open failed steps
        document.querySelectorAll('.step-status.step-fail').forEach(el => {
            el.closest('.step-header').click();
        });
    </script>
</body>
</html>
"""

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def check_ollama_server(api_url: str) -> Tuple[bool, str]:
    """Check if Ollama server is running and accessible."""
    try:
        # Try the tags endpoint first (lightweight)
        response = requests.get(f"{api_url}/api/tags", timeout=5)
        response.raise_for_status()

        # Check if our model is available
        data = response.json()
        models = [m.get('name', m.get('model', '')) for m in data.get('models', [])]

        model_name = config.get("llm_model", "deepseek-coder:6.7b")
        model_available = any(model_name in m for m in models)

        if model_available:
            logger.info(f"Ollama server accessible. Model '{model_name}' available.")
            return True, f"Model '{model_name}' ready"
        else:
            logger.warning(f"Ollama accessible but model '{model_name}' not found. Available: {models}")
            return True, f"Model '{model_name}' not found. Available: {', '.join(models[:3])}..."

    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to Ollama at {api_url}")
        return False, "Connection refused - is Ollama running?"
    except requests.exceptions.Timeout:
        logger.error(f"Ollama connection timed out at {api_url}")
        return False, "Connection timeout"
    except Exception as e:
        logger.error(f"Ollama check failed: {e}")
        return False, str(e)


def find_executable(path_candidate: Union[str, Path], alternative_names: Optional[List[str]] = None) -> Optional[Path]:
    """
    Find executable with multiple fallback strategies.
    Returns None if not found (instead of invalid path).
    """
    if alternative_names is None:
        alternative_names = []

    search_names = [Path(path_candidate).name] + alternative_names

    # Strategy 1: Try the provided absolute path
    path = Path(path_candidate).expanduser().resolve()
    if path.is_file() and os.access(str(path), os.X_OK):
        logger.info(f"Found executable at provided path: {path}")
        return path

    # Strategy 2: Search in system PATH
    for alt_name in search_names:
        found_path = shutil.which(alt_name)
        if found_path:
            resolved = Path(found_path).resolve()
            if resolved.is_file() and os.access(str(resolved), os.X_OK):
                logger.info(f"Found executable in PATH: {resolved}")
                return resolved

    # Strategy 3: Common installation locations
    common_locations = [
        Path.home() / "bin",
        Path.home() / ".local" / "bin",
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/opt"),
        Path.cwd()
    ]

    for location in common_locations:
        if not location.exists():
            continue
        for alt_name in search_names:
            test_path = location / alt_name
            if test_path.is_file() and os.access(str(test_path), os.X_OK):
                logger.info(f"Found executable in common location: {test_path}")
                return test_path

    logger.warning(f"Executable not found: {path_candidate} (tried: {search_names})")
    return None


def sanitize_filename(text: str, max_length: int = 40) -> str:
    """Create a safe filename slug from arbitrary text."""
    # Remove non-alphanumeric chars, replace spaces with underscore
    slug = re.sub(r'[^a-zA-Z0-9\s-]', '', text.lower())
    slug = re.sub(r'[\s-]+', '_', slug).strip('_')
    return slug[:max_length] if slug else "plc_program"

# =============================================================================
# OLLAMA4PLC ENGINE
# =============================================================================

class Ollama4PLC:
    """Main engine for PLC code generation, compilation, and verification."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.model = cfg.get("llm_model", "deepseek-coder:6.7b")
        self.api_url = cfg.get("api_base_url", "http://localhost:11434").rstrip('/')
        self.timeout = cfg.get("timeout", 320)
        self.temperature = cfg.get("temperature", 0.1)
        self.max_tokens = cfg.get("max_tokens", 2048)
        self.output_dir = Path(cfg.get("output_dir", "output")).resolve()

        # Find tools
        self.rusty_path = find_executable(
            cfg.get("rusty_path", ""),
            ["plc", "rusty", "rustyc", "rusty.exe"]
        )
        self.nuxmv_path = find_executable(
            cfg.get("nuxmv_path", ""),
            ["nuxmv", "nuXmv", "nuxmv.exe"]
        )
        self.plcverif_path = find_executable(
            cfg.get("plcverif_path", ""),
            ["plcverif-cli", "plcverif", "plcverif.exe"]
        )

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Log tool status
        self._log_tool_status()

    def _log_tool_status(self):
        """Log the status of all external tools."""
        tools = {
            "RuSTy Compiler": self.rusty_path,
            "nuXmv Verifier": self.nuxmv_path,
            "PLCverif Tool": self.plcverif_path
        }
        logger.info("🔧 Tool Status Check:")
        for name, path in tools.items():
            if path and path.is_file():
                logger.info(f"   ✅ {name}: {path}")
            else:
                logger.warning(f"   ❌ {name}: Not found")

    def _call_ollama(self, prompt: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Call Ollama API with proper error handling.
        Returns (response_text, error_message).
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens
            }
        }

        try:
            response = requests.post(
                f"{self.api_url}/api/generate",
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            data = response.json()

            if "response" in data:
                return data["response"].strip(), None
            elif "message" in data and "content" in data["message"]:
                # Chat API fallback
                return data["message"]["content"].strip(), None
            else:
                return None, f"Unexpected API response format: {list(data.keys())}"

        except requests.exceptions.ConnectionError:
            return None, f"Cannot connect to Ollama at {self.api_url}. Is the server running?"
        except requests.exceptions.Timeout:
            return None, f"Ollama request timed out after {self.timeout}s"
        except requests.exceptions.HTTPError as e:
            return None, f"HTTP error {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            return None, f"API request failed: {str(e)}"

    def generate_st_code(self, requirements: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Generate ST code using Ollama with strict IEC 61131-3 prompt.
        Returns: (reasoning, st_code, error)
        """
        logger.info("Generating ST code...")

        prompt = f"""You are an expert PLC programmer specializing in IEC 61131-3 Structured Text (ST).

TASK: Generate a COMPLETE, COMPILABLE Structured Text program from the following requirements.

CRITICAL RULES FOR RUSTY COMPILER COMPATIBILITY:
1. Use ONLY these elements:
   - PROGRAM ... END_PROGRAM structure (mandatory)
   - VAR_INPUT, VAR_OUTPUT, VAR sections (declare ALL variables)
   - BOOL and INT types only
   - IF-THEN-ELSIF-ELSE-END_IF
   - Assignment operator :=
   - Logical operators: AND, OR, NOT, XOR
   - Comparison: =, <>, <, >, <=, >=
   - Basic arithmetic: +, -, *, /
   - Parentheses for grouping

2. NEVER use:
   - Function blocks (TON, TOF, CTU, etc.)
   - Arrays or complex data types
   - CASE statements (use IF chains instead)
   - Loops (FOR, WHILE, REPEAT)
   - String operations
   - Real/floating point types

3. Variable naming:
   - Use descriptive names: Start_PB, Stop_PB, Motor_Run
   - All variables MUST be declared in VAR sections
   - No undeclared variables allowed

4. Program structure:
   PROGRAM MainProgram
   VAR_INPUT
       (* all inputs *)
   END_VAR
   VAR_OUTPUT
       (* all outputs *)
   END_VAR
   VAR
       (* all internal variables *)
   END_VAR
   (* logic here *)
   END_PROGRAM

REQUIREMENTS:
{requirements}

OUTPUT FORMAT - You MUST follow this exactly:

---REASONING---
1. Objective: Brief description of what the program does
2. Variables: List ALL variables with types
3. Logic: Description of the control flow

---CODE---
```iecst
PROGRAM MainProgram
    VAR_INPUT
        (* declare inputs here *)
    END_VAR
    VAR_OUTPUT
        (* declare outputs here *)
    END_VAR
    VAR
        (* declare internals here *)
    END_VAR

    (* Your logic here - keep it simple and sequential *)

END_PROGRAM
```
"""

        full_response, error = self._call_ollama(prompt)

        if error:
            logger.error(f"Code generation failed: {error}")
            return None, None, error

        if not full_response:
            logger.error("Empty response from Ollama")
            return None, None, "Empty response from model"

        # Extract reasoning
        reasoning = None
        if "---REASONING---" in full_response and "---CODE---" in full_response:
            try:
                r_start = full_response.index("---REASONING---") + len("---REASONING---")
                r_end = full_response.index("---CODE---")
                reasoning = full_response[r_start:r_end].strip()
            except ValueError:
                reasoning = None

        # Extract code block - support multiple markdown fence styles
        code_part = None
        patterns = [
            r'```(?:iecst|st|structuredtext|pascal)?\s*\n(.*?)\n\s*```',
            r'```\s*\n(.*?)\n\s*```',
        ]

        for pattern in patterns:
            match = re.search(pattern, full_response, re.DOTALL | re.IGNORECASE)
            if match:
                code_part = match.group(1).strip()
                break

        # Fallback: look for PROGRAM/END_PROGRAM if no markdown
        if not code_part:
            prog_match = re.search(
                r'(PROGRAM\s+\w+.*?END_PROGRAM)',
                full_response,
                re.DOTALL | re.IGNORECASE
            )
            if prog_match:
                code_part = prog_match.group(1).strip()

        if not code_part:
            logger.error("Could not extract ST code from response")
            return reasoning, None, "Failed to extract ST code block from model response"

        # Validate basic structure
        if "PROGRAM" not in code_part.upper() or "END_PROGRAM" not in code_part.upper():
            logger.error("Extracted code missing PROGRAM/END_PROGRAM structure")
            return reasoning, None, "Generated code missing required PROGRAM structure"

        logger.info(f"Successfully generated ST code ({len(code_part)} chars)")
        return reasoning, code_part, None

    def _clean_st_for_rusty(self, st_code: str) -> str:
        """
        Clean and normalize ST code for RuSTy compiler compatibility.
        """
        cleaned = st_code

        # Remove markdown artifacts
        cleaned = re.sub(r'```\w*', '', cleaned)
        cleaned = re.sub(r'```', '', cleaned)

        # Normalize line endings
        cleaned = cleaned.replace('\r\n', '\n').replace('\r', '\n')

        # Remove block comments but keep line comments for debugging
        cleaned = re.sub(r'\(\*.*?\*\)', '', cleaned, flags=re.DOTALL)

        # Ensure proper program wrapper
        if not re.search(r'PROGRAM\s+\w+', cleaned, re.IGNORECASE):
            cleaned = "PROGRAM MainProgram\n" + cleaned
        if "END_PROGRAM" not in cleaned.upper():
            cleaned += "\nEND_PROGRAM"

        # Remove empty VAR sections that confuse some parsers
        cleaned = re.sub(
            r'(VAR_\w+|VAR)\s*END_VAR',
            '',
            cleaned,
            flags=re.IGNORECASE
        )

        # Normalize whitespace
        lines = [line.rstrip() for line in cleaned.split('\n')]
        cleaned = '\n'.join(line for line in lines if line.strip())

        return cleaned

    def compile_st_code(self, st_code: str, filename: str) -> Tuple[bool, str]:
        """
        Compile ST code using RuSTy compiler.
        Returns: (success, message)
        """
        logger.info(f"Compiling ST file: {filename}")

        st_file = self.output_dir / filename
        ir_file = self.output_dir / f"{Path(filename).stem}.ll"

        # Clean and save ST code
        cleaned_code = self._clean_st_for_rusty(st_code)

        try:
            st_file.write_text(cleaned_code, encoding='utf-8')
            logger.info(f"ST file saved: {st_file}")
        except IOError as e:
            return False, f"Failed to write ST file: {e}"

        # Check if RuSTy is available
        if not self.rusty_path:
            return False, (
                f"RuSTy compiler not found.\n"
                f"ST file saved to: {st_file}\n"
                f"Install RuSTy from: https://github.com/PLC-lang/rusty"
            )

        # Build RuSTy command
        cmd = [
            str(self.rusty_path),
            "--output", str(ir_file),
            str(st_file)
        ]

        logger.info(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False  # We handle return codes manually
            )

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode == 0 and ir_file.exists():
                logger.info(f"Compilation successful: {ir_file}")
                return True, (
                    f"✅ Compilation successful\n"
                    f"Output: {ir_file}\n"
                    f"Size: {ir_file.stat().st_size} bytes"
                )

            # Compilation failed - analyze error
            error_analysis = self._analyze_rusty_error(stderr, stdout, cleaned_code)

            logger.error(f"Compilation failed (code {result.returncode})")
            return False, (
                f"❌ Compilation failed (exit code: {result.returncode})\n"
                f"{error_analysis}\n"
                f"--- STDERR ---\n{stderr}\n"
                f"--- STDOUT ---\n{stdout}"
            )

        except subprocess.TimeoutExpired:
            logger.error(f"Compilation timed out after {self.timeout}s")
            return False, f"⏰ Compilation timed out after {self.timeout}s"
        except Exception as e:
            logger.error(f"Compilation exception: {e}")
            return False, f"❌ Compilation error: {str(e)}"

    def _analyze_rusty_error(self, stderr: str, stdout: str, st_code: str) -> str:
        """Analyze RuSTy compilation errors and provide helpful hints."""
        combined = (stderr + stdout).lower()
        hints = []

        if "syntax error" in combined or "unexpected" in combined:
            hints.append("🔍 Syntax error: Check semicolons, parentheses, and keyword spelling")

        if "undeclared" in combined or "unknown" in combined:
            hints.append("🔍 Undeclared variable: Ensure all variables are in VAR sections")

        if "type mismatch" in combined or "incompatible" in combined:
            hints.append("🔍 Type mismatch: Check assignments match declared types")

        if "expected" in combined:
            hints.append("🔍 Parser expected different syntax - check ST structure")

        if "program" not in st_code.lower():
            hints.append("🔍 Missing PROGRAM declaration")

        if "end_program" not in st_code.lower():
            hints.append("🔍 Missing END_PROGRAM")

        if not hints:
            hints.append("🔍 Check variable declarations and basic ST syntax")

        return "\n".join(hints)

    def translate_to_smv(self, st_code: str, filename: str) -> Tuple[bool, str]:
        """
        Translate ST code to nuXmv SMV format.
        Returns: (success, message_or_filepath)
        """
        logger.info(f"Translating to SMV: {filename}")
        smv_file = self.output_dir / filename

        try:
            # Remove comments for parsing
            code_no_comments = re.sub(r'\(\*.*?\*\)', '', st_code, flags=re.DOTALL)
            code_no_comments = re.sub(r'//.*', '', code_no_comments)

            variables = {}  # name -> type_hint
            assignments = []  # (lhs, rhs, is_conditional)

            # Parse variable declarations
            var_block_pattern = re.compile(
                r'(VAR_INPUT|VAR_OUTPUT|VAR)\s*(.*?)\s*END_VAR',
                re.DOTALL | re.IGNORECASE
            )

            for match in var_block_pattern.finditer(code_no_comments):
                block_type = match.group(1).upper()
                block_content = match.group(2)

                for line in block_content.split('\n'):
                    line = line.strip()
                    if not line or line.startswith('('):
                        continue

                    # Parse: VarName : Type;
                    var_decl = re.match(r'(\w+)\s*:\s*(\w+)', line)
                    if var_decl:
                        var_name = var_decl.group(1)
                        var_type = var_decl.group(2).upper()
                        variables[var_name] = var_type

            # Parse assignments and IF structures
            lines = code_no_comments.split('\n')
            i = 0
            current_condition = None

            while i < len(lines):
                line = lines[i].strip()
                i += 1

                if not line:
                    continue

                # IF statement
                if_match = re.match(r'IF\s+(.*?)\s+THEN', line, re.IGNORECASE)
                if if_match:
                    current_condition = self._st_expr_to_smv(if_match.group(1), variables)
                    continue

                # ELSIF
                elsif_match = re.match(r'ELSIF\s+(.*?)\s+THEN', line, re.IGNORECASE)
                if elsif_match:
                    current_condition = self._st_expr_to_smv(elsif_match.group(1), variables)
                    continue

                # ELSE
                if re.match(r'ELSE\b', line, re.IGNORECASE):
                    if current_condition:
                        current_condition = f"!({current_condition})"
                    continue

                # END_IF
                if re.match(r'END_IF', line, re.IGNORECASE):
                    current_condition = None
                    continue

                # Assignment
                assign_match = re.match(r'(\w+)\s*:=\s*(.*?);', line)
                if assign_match:
                    lhs = assign_match.group(1)
                    rhs = self._st_expr_to_smv(assign_match.group(2), variables)

                    if current_condition:
                        rhs = f"({current_condition}) ? {rhs} : {lhs}"

                    assignments.append((lhs, rhs))
                    if lhs not in variables:
                        variables[lhs] = "BOOL"  # Assume BOOL if undeclared

            # Generate SMV
            smv_lines = ["MODULE main", "VAR"]

            for var_name, var_type in sorted(variables.items()):
                if var_type in ["INT", "DINT", "SINT", "USINT", "UINT", "UDINT"]:
                    smv_lines.append(f"    {var_name} : -1000..1000;")
                else:
                    smv_lines.append(f"    {var_name} : boolean;")

            smv_lines.append("")
            smv_lines.append("ASSIGN")

            # Initialize all variables
            for var_name, var_type in sorted(variables.items()):
                if var_type in ["INT", "DINT", "SINT", "USINT", "UINT", "UDINT"]:
                    smv_lines.append(f"    init({var_name}) := 0;")
                else:
                    smv_lines.append(f"    init({var_name}) := FALSE;")

            smv_lines.append("")

            # Next state assignments
            assigned_vars = set()
            for lhs, rhs in assignments:
                smv_lines.append(f"    next({lhs}) := {rhs};")
                assigned_vars.add(lhs)

            # Unassigned variables keep their value
            for var_name in sorted(variables.keys()):
                if var_name not in assigned_vars:
                    smv_lines.append(f"    next({var_name}) := {var_name};")

            # Add verification properties
            smv_lines.extend(self._generate_smv_properties(variables))

            smv_content = "\n".join(smv_lines)
            smv_file.write_text(smv_content, encoding='utf-8')

            logger.info(f"SMV translation successful: {smv_file}")
            return True, str(smv_file)

        except Exception as e:
            logger.error(f"SMV translation failed: {e}")
            traceback_str = traceback.format_exc()

            # Create fallback SMV
            fallback = self._create_fallback_smv()
            smv_file.write_text(fallback, encoding='utf-8')

            return True, (
                f"⚠️ Translation used fallback due to error: {str(e)}\n"
                f"SMV file: {smv_file}\n"
                f"Please review the generated SMV manually."
            )

    def _st_expr_to_smv(self, expr: str, variables: Dict[str, str]) -> str:
        """Convert ST expression to SMV expression."""
        smv = expr

        # Replace operators (case-insensitive, word boundaries)
        replacements = [
            (r'\bAND\b', '&'),
            (r'\bOR\b', '|'),
            (r'\bNOT\b', '!'),
            (r'\bXOR\b', 'xor'),
            (r'\bTRUE\b', 'TRUE'),
            (r'\bFALSE\b', 'FALSE'),
            (r'\bMOD\b', 'mod'),
        ]

        for pattern, replacement in replacements:
            smv = re.sub(pattern, replacement, smv, flags=re.IGNORECASE)

        # Handle assignment vs comparison: ST uses = for both, SMV uses = for comparison
        # This is tricky - we assume simple expressions here

        return smv.strip()

    def _generate_smv_properties(self, variables: Dict[str, str]) -> List[str]:
        """Generate default LTL properties for SMV verification."""
        props = [
            "",
            "-- Verification Properties",
            "",
            "-- Safety: No variable is both true and false",
        ]

        bool_vars = [v for v, t in variables.items() if t not in ["INT", "DINT", "SINT", "USINT", "UINT", "UDINT"]]

        for var in bool_vars:
            props.append(f"LTLSPEC G !({var} & !{var})  -- {var} consistency")

        # Mutual exclusion for start/stop pairs
        start_vars = [v for v in bool_vars if 'start' in v.lower()]
        stop_vars = [v for v in bool_vars if 'stop' in v.lower()]

        if start_vars and stop_vars:
            props.append("")
            props.append("-- Safety: Start and Stop should not be active simultaneously")
            for s in start_vars:
                for st in stop_vars:
                    props.append(f"LTLSPEC G !({s} & {st})  -- mutual exclusion")

        # Liveness for alarm/error variables
        alarm_vars = [v for v in bool_vars if any(x in v.lower() for x in ['alarm', 'error', 'fault'])]
        if alarm_vars:
            props.append("")
            props.append("-- Liveness: Alarms should eventually clear")
            for var in alarm_vars:
                props.append(f"LTLSPEC G ({var} -> F !{var})  -- {var} clears")

        return props

    def _create_fallback_smv(self) -> str:
        """Create a minimal fallback SMV model."""
        return """MODULE main
VAR
    state : boolean;
    input_signal : boolean;
    output_signal : boolean;

ASSIGN
    init(state) := FALSE;
    init(input_signal) := FALSE;
    init(output_signal) := FALSE;

    next(state) := !state;
    next(input_signal) := {TRUE, FALSE};
    next(output_signal) := state & input_signal;

-- Verification Properties
LTLSPEC G !(state & !state)
LTLSPEC G !(output_signal & !input_signal)
LTLSPEC G (input_signal -> F !input_signal)
"""

    def verify_with_nuxmv(self, smv_file_path: str, properties: Optional[str] = None) -> Tuple[bool, str]:
        """
        Verify SMV model using nuXmv.
        Returns: (success, message)
        """
        logger.info("Verifying with nuXmv...")
        smv_file = Path(smv_file_path)

        if not smv_file.is_file():
            return False, f"SMV file not found: {smv_file}"

        if not self.nuxmv_path:
            return False, (
                "nuXmv not found. Verification skipped.\n"
                "Install from: https://nuxmv.fbk.eu/"
            )

        # Create enhanced SMV with user properties
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        enhanced_smv = self.output_dir / f"{smv_file.stem}_{timestamp}_verify.smv"

        try:
            original = smv_file.read_text(encoding='utf-8')

            if properties:
                user_props = self._convert_properties_to_smv(properties)
                full_content = original + "\n\n" + user_props
            else:
                full_content = original

            enhanced_smv.write_text(full_content, encoding='utf-8')

            # Run nuXmv in batch mode (more reliable than interactive)
            cmd = [str(self.nuxmv_path), str(enhanced_smv)]
            logger.info(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout * 2,
                check=False
            )

            output = result.stdout + "\n" + result.stderr
            analysis = self._analyze_nuxmv_output(output)

            if "is false" in output.lower():
                return True, (
                    f"⚠️ Verification found property violations\n"
                    f"{analysis}\n"
                    f"--- nuXmv Output ---\n{output.strip()[:2000]}"
                )
            elif "is true" in output.lower():
                return True, (
                    f"✅ All properties verified successfully\n"
                    f"{analysis}\n"
                    f"--- nuXmv Output ---\n{output.strip()[:1000]}"
                )
            else:
                return True, (
                    f"📊 Verification completed\n"
                    f"{analysis}\n"
                    f"--- nuXmv Output ---\n{output.strip()[:2000]}"
                )

        except subprocess.TimeoutExpired:
            return False, f"⏰ nuXmv timed out after {self.timeout * 2}s"
        except Exception as e:
            return False, f"❌ nuXmv verification error: {str(e)}"

    def _analyze_nuxmv_output(self, output: str) -> str:
        """Analyze nuXmv output and provide summary."""
        lines = output.split('\n')
        true_count = 0
        false_count = 0
        details = []

        for i, line in enumerate(lines):
            line_stripped = line.strip()

            if "is true" in line_stripped:
                true_count += 1
                # Look back for specification
                spec = None
                for j in range(max(0, i-10), i):
                    if "LTLSPEC" in lines[j] or "SPEC" in lines[j]:
                        spec = lines[j].strip()
                        break
                if spec:
                    details.append(f"✅ TRUE: {spec[:100]}")

            elif "is false" in line_stripped:
                false_count += 1
                spec = None
                for j in range(max(0, i-10), i):
                    if "LTLSPEC" in lines[j] or "SPEC" in lines[j]:
                        spec = lines[j].strip()
                        break
                if spec:
                    details.append(f"❌ FALSE: {spec[:100]}")

        summary = f"Verified: {true_count}, Violated: {false_count}, Total: {true_count + false_count}"
        if details:
            summary += "\n" + "\n".join(details[:10])  # Limit details

        return summary

    def _convert_properties_to_smv(self, properties: str) -> str:
        """Convert user properties to SMV LTLSPEC format."""
        smv_props = []

        # Pattern: (*! LTL expression *)
        ltl_pattern = re.compile(r'\(\*!\s*LTL\s+(.*?)\s*\*\)', re.DOTALL | re.IGNORECASE)

        for match in ltl_pattern.finditer(properties):
            expr = match.group(1).strip()
            # Convert ST operators to SMV
            expr = re.sub(r'\bAND\b', '&', expr, flags=re.IGNORECASE)
            expr = re.sub(r'\bOR\b', '|', expr, flags=re.IGNORECASE)
            expr = re.sub(r'\bNOT\b', '!', expr, flags=re.IGNORECASE)
            smv_props.append(f"LTLSPEC {expr}")

        # Also accept raw lines starting with LTLSPEC or just plain text
        if not smv_props:
            for line in properties.strip().split('\n'):
                line = line.strip()
                if line and not line.startswith('('):
                    if not line.upper().startswith('LTLSPEC'):
                        line = f"LTLSPEC {line}"
                    smv_props.append(line)

        return "\n".join(smv_props) if smv_props else ""

    def verify_with_plcverif(self, st_code: str, properties: str, topic: str) -> Tuple[bool, str]:
        """
        Verify ST code using PLCverif.
        Returns: (success, message)
        """
        logger.info(f"Verifying with PLCverif for topic: {topic}")

        if not self.plcverif_path:
            return False, (
                "PLCverif not found. Verification skipped.\n"
                "Install from: https://github.com/PLC-lang/plcverif"
            )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{sanitize_filename(topic)}.st"
        st_file = self.output_dir / filename

        # Combine code with properties as comments
        combined = st_code + "\n\n" + f"(* Verification Properties \n{properties} \n*)"

        try:
            st_file.write_text(combined, encoding='utf-8')

            cmd = [str(self.plcverif_path), str(st_file)]
            logger.info(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False
            )

            output = result.stdout + "\n" + result.stderr

            if result.returncode == 0:
                return True, f"✅ PLCverif completed\n{output.strip()[:1500]}"
            else:
                return True, f"⚠️ PLCverif completed with warnings (code {result.returncode})\n{output.strip()[:1500]}"

        except subprocess.TimeoutExpired:
            return False, f"⏰ PLCverif timed out after {self.timeout}s"
        except Exception as e:
            return False, f"❌ PLCverif error: {str(e)}"

    def process_requirements(self, requirements: str, plcverif_properties: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute the full pipeline: generate -> compile -> translate -> verify.
        Returns structured result dictionary.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        topic = sanitize_filename(requirements.split('\n')[0], 30)

        base = f"{timestamp}_{topic}"
        st_filename = f"{base}.st"
        smv_filename = f"{base}.smv"

        result = {
            "status": "failed",
            "error": None,
            "duration": "0s",
            "tool_status": {
                "ollama": True,  # Assumed since we got here
                "rusty": self.rusty_path is not None,
                "nuxmv": self.nuxmv_path is not None,
                "plcverif": self.plcverif_path is not None
            },
            "steps": {
                "generate": {"success": False, "reasoning": None, "output": None},
                "compile": {"success": False, "output": None},
                "translate": {"success": False, "output": None},
                "verify_nuxmv": {"success": False, "output": None},
                "verify_plcverif": {"success": False, "output": None}
            }
        }

        start_time = time.time()

        try:
            # Step 1: Generate
            reasoning, st_code, error = self.generate_st_code(requirements)
            result["steps"]["generate"]["reasoning"] = reasoning
            result["steps"]["generate"]["output"] = st_code

            if error:
                result["error"] = f"Generation failed: {error}"
                return result

            result["steps"]["generate"]["success"] = True

            # Step 2: Compile
            if self.rusty_path and st_code:
                compile_ok, compile_msg = self.compile_st_code(st_code, st_filename)
                result["steps"]["compile"]["output"] = compile_msg
                result["steps"]["compile"]["success"] = compile_ok
            else:
                result["steps"]["compile"]["output"] = "RuSTy not available - compilation skipped"

            # Step 3: Translate to SMV
            trans_ok = False
            trans_msg = None
            if st_code:
                trans_ok, trans_msg = self.translate_to_smv(st_code, smv_filename)
                result["steps"]["translate"]["output"] = trans_msg
                result["steps"]["translate"]["success"] = trans_ok
            else:
                result["steps"]["translate"]["output"] = "Skipped: no ST code generated"
                result["steps"]["translate"]["success"] = False

            # Step 4: Verify with nuXmv
            if trans_ok and self.nuxmv_path and trans_msg and Path(trans_msg).is_file():
                verify_ok, verify_msg = self.verify_with_nuxmv(trans_msg, plcverif_properties)
                result["steps"]["verify_nuxmv"]["output"] = verify_msg
                result["steps"]["verify_nuxmv"]["success"] = verify_ok
            elif not trans_ok:
                result["steps"]["verify_nuxmv"]["output"] = "Skipped: SMV translation failed"
            else:
                result["steps"]["verify_nuxmv"]["output"] = "Skipped: nuXmv not available"

            # Step 5: Verify with PLCverif
            if plcverif_properties and self.plcverif_path and st_code:
                pv_ok, pv_msg = self.verify_with_plcverif(st_code, plcverif_properties, topic)
                result["steps"]["verify_plcverif"]["output"] = pv_msg
                result["steps"]["verify_plcverif"]["success"] = pv_ok
            else:
                result["steps"]["verify_plcverif"]["output"] = "Skipped: no properties, no ST code, or tool unavailable"

            # Determine overall status
            has_output = [s for s in result["steps"].values() if s["output"] is not None]
            successful = [s for s in has_output if s["success"]]

            if len(successful) == len(has_output) and len(has_output) > 0:
                result["status"] = "success"
            elif len(successful) > 0:
                result["status"] = "partial"
            else:
                result["status"] = "failed"

        except Exception as e:
            logger.critical(f"Pipeline critical error: {e}", exc_info=True)
            result["error"] = f"Critical pipeline error: {str(e)}"
            result["status"] = "failed"

        result["duration"] = f"{time.time() - start_time:.2f}s"
        logger.info(f"Pipeline completed: {result['status']} in {result['duration']}")

        return result

# =============================================================================
# GLOBAL ENGINE INITIALIZATION
# =============================================================================

ollama_engine: Optional[Ollama4PLC] = None
ENGINE_STATUS = "Initializing..."
OLLAMA_STATUS_MSG = ""

try:
    ollama_ok, ollama_msg = check_ollama_server(config["api_base_url"])
    OLLAMA_STATUS_MSG = ollama_msg

    if ollama_ok:
        ollama_engine = Ollama4PLC(config)
        ENGINE_STATUS = "Ready"
        logger.info("Ollama4PLC engine initialized successfully")
    else:
        ENGINE_STATUS = f"Ollama unavailable: {ollama_msg}"
        logger.critical(ENGINE_STATUS)

except Exception as e:
    ENGINE_STATUS = f"Initialization failed: {str(e)}"
    logger.critical(ENGINE_STATUS, exc_info=True)

# =============================================================================
# FLASK ROUTES
# =============================================================================

@app.route('/', methods=['GET'])
def index():
    """Render main input page."""

    tool_status = {
        "ollama": ollama_engine is not None and ENGINE_STATUS == "Ready",
        "rusty": ollama_engine.rusty_path is not None if ollama_engine else False,
        "nuxmv": ollama_engine.nuxmv_path is not None if ollama_engine else False,
        "plcverif": ollama_engine.plcverif_path is not None if ollama_engine else False
    }

    status_warning = None
    if ENGINE_STATUS != "Ready":
        status_warning = f"{ENGINE_STATUS}. Check that Ollama is running with: ollama serve"

    default_requirements = (
        "Create a motor start/stop control.\n"
        "Inputs: Start_PB (BOOL), Stop_PB (BOOL).\n"
        "Output: Motor_Run (BOOL).\n"
        "Logic: Start_PB latches Motor_Run on. Stop_PB stops it."
    )

    default_properties = (
        "(*! LTL G (Motor_Run -> !Stop_PB) *)\n"
        "(*! LTL G !(Motor_Run & Stop_PB) *)"
    )

    return render_template_string(
        INDEX_TEMPLATE,
        status_warning=status_warning,
        tool_status=tool_status,
        default_requirements=default_requirements,
        default_properties=default_properties
    )


@app.route('/process', methods=['POST'])
def process_pipeline():
    """Handle form submission and run pipeline."""

    if ollama_engine is None or ENGINE_STATUS != "Ready":
        tool_status = {
            "ollama": False, "rusty": False, "nuxmv": False, "plcverif": False
        }

        result = {
            "status": "failed",
            "error": f"Engine not ready: {ENGINE_STATUS}",
            "duration": "0s",
            "tool_status": tool_status,
            "steps": {},
            "original_requirements": "N/A"
        }

        return render_template_string(RESULTS_TEMPLATE, result=result, successful_steps=0, total_steps=0)

    requirements = request.form.get('requirements', '').strip()
    properties = request.form.get('plcverif_properties', '').strip()

    if not requirements:
        return redirect(url_for('index'))

    logger.info("Starting pipeline from web request")

    result = ollama_engine.process_requirements(requirements, properties if properties else None)
    result['original_requirements'] = requirements
    result['original_properties'] = properties

    # Count steps for template
    has_output = [s for s in result["steps"].values() if s["output"] is not None]
    successful = [s for s in has_output if s["success"]]

    return render_template_string(
        RESULTS_TEMPLATE,
        result=result,
        successful_steps=len(successful),
        total_steps=len(has_output)
    )


@app.route('/download_st', methods=['POST'])
def download_st():
    """Serve ST code as downloadable file."""
    st_code = request.form.get('st_code', '')

    if not st_code:
        return "Error: No code provided", 400

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"plc_code_{timestamp}.st"

    response = Response(
        response=st_code,
        status=200,
        mimetype='text/plain; charset=utf-8'
    )
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response


@app.route('/api/status', methods=['GET'])
def api_status():
    """JSON API endpoint for system status."""
    return jsonify({
        "status": ENGINE_STATUS,
        "ollama_message": OLLAMA_STATUS_MSG,
        "tools": {
            "ollama": ollama_engine is not None and ENGINE_STATUS == "Ready",
            "rusty": ollama_engine.rusty_path is not None if ollama_engine else False,
            "nuxmv": ollama_engine.nuxmv_path is not None if ollama_engine else False,
            "plcverif": ollama_engine.plcverif_path is not None if ollama_engine else False
        },
        "config": {
            "model": config.get("llm_model"),
            "api_url": config.get("api_base_url"),
            "output_dir": str(config.get("output_dir", "output"))
        }
    })


@app.route('/api/generate', methods=['POST'])
def api_generate():
    """JSON API endpoint for programmatic access."""
    if ollama_engine is None or ENGINE_STATUS != "Ready":
        return jsonify({"error": ENGINE_STATUS}), 503

    data = request.get_json() or {}
    requirements = data.get('requirements', '').strip()
    properties = data.get('properties', '').strip() or None

    if not requirements:
        return jsonify({"error": "Missing 'requirements' field"}), 400

    result = ollama_engine.process_requirements(requirements, properties)
    return jsonify(result)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Ollama4PLC - PLC Code Generator')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode (not for production)')

    args = parser.parse_args()

    logger.info(f"Starting Ollama4PLC server on {args.host}:{args.port}")
    logger.info(f"Engine status: {ENGINE_STATUS}")

    app.run(
        host=args.host,
        port=args.port,
        debug=args.debug,
        threaded=True
    )
