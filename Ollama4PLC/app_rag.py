"""
Ollama4PLC with RAG Integration
================================

Enhanced version of Ollama4PLC that includes Retrieval-Augmented Generation (RAG)
for context-aware ST code generation.

This module extends the base Ollama4PLC pipeline with:
- Semantic retrieval of PLC code examples from vector database
- Enhanced prompts with relevant code patterns
- Improved generation quality through RAG context

Usage:
    # Standard mode (no RAG)
    from app_rag import Ollama4PLC
    engine = Ollama4PLC()

    # RAG-enhanced mode
    from app_rag import Ollama4PLC_RAG_Engine
    engine = Ollama4PLC_RAG_Engine(
        db_dir="./database/st_db",
        dataset_paths=["./dataset/oscat_plc_code_793.json"]
    )
"""

import subprocess
import os
import logging
import requests
import re
import json
import time
import shutil
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List
from pathlib import Path
from flask import Flask, request, render_template, jsonify, url_for, redirect, Response

# Import RAG module
from rag_pipeline import Ollama4PLC_RAG

# --- Configuration Loading and Logging Setup ---

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ollama4plc.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Configuration Loading ---
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "llm_model": "mistral:7b",
    "api_base_url": "http://localhost:11434",
    "api_key": "ollama",
    "plcverif_path": "~/ollama4plc-plus/plcverif/plcverif-cli",
    "rusty_path": "~/ollama4plc-plus/rusty/target/release/plc",
    "nuxmv_path": "/usr/local/bin/nuXmv",
    "output_dir": "output",
    "timeout": 300,
    "rag": {
        "enabled": False,
        "db_dir": "./database/st_db",
        "dataset_paths": [],
        "embedding_model": "nomic-embed-text",
        "top_k": 3
    }
}

def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                # Merge with defaults for new RAG section
                if "rag" not in config:
                    config["rag"] = DEFAULT_CONFIG["rag"]
                return config
        logger.info("Config file not found, using default configuration")
        return DEFAULT_CONFIG
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return DEFAULT_CONFIG

config = load_config()

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Environment Setup ---
os.environ["OPENAI_API_BASE_URL"] = config["api_base_url"]
os.environ["OPENAI_MODEL_NAME"] = config["llm_model"]
os.environ["OPENAI_API_KEY"] = config["api_key"]

# --- Utility Functions ---

def check_ollama_server(api_url: str) -> bool:
    """Checks if Ollama server is running."""
    try:
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        logger.info("Ollama server is accessible.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama server not accessible at {api_url}: {e}")
        return False


# =============================================================================
# BASE Ollama4PLC ENGINE (from original app.py)
# =============================================================================

class Ollama4PLC:
    """Base Ollama4PLC engine without RAG."""

    def __init__(self, **kwargs):
        """Initialize the Ollama4PLC system with robust path handling."""
        self.ollama_model = kwargs.get("ollama_model", config["llm_model"])
        self.output_dir = Path(kwargs.get("output_dir", config["output_dir"])).resolve()

        self.rusty_path = self._find_executable(
            kwargs.get("rusty_path", config["rusty_path"]),
            ["plc", "rusty", "rustyc"]
        )

        self.nuxmv_path = self._find_executable(
            kwargs.get("nuxmv_path", config["nuxmv_path"]),
            ["nuxmv", "nuXmv", "nuxmv64", "nuxmv32"]
        )

        self.plcverif_path = self._find_executable(
            kwargs.get("plcverif_path", config["plcverif_path"]),
            ["plcverif-cli", "plcverif", "plcverif.exe"]
        )

        self.api_url = kwargs.get("api_url", config["api_base_url"])
        self.timeout = kwargs.get("timeout", config["timeout"])

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._log_tool_status()
            logger.info("Ollama4PLC Engine Initialized.")
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            raise

    def _find_executable(self, path_candidate, alternative_names=None):
        """Find executable with multiple fallback strategies."""
        if alternative_names is None:
            alternative_names = []

        path = Path(path_candidate).expanduser().resolve()
        if path.is_file():
            logger.info(f"Found executable at provided path: {path}")
            return path

        current_dir = Path.cwd() / Path(path_candidate).name
        if current_dir.is_file():
            logger.info(f"Found executable in current directory: {current_dir}")
            return current_dir

        search_names = alternative_names + [Path(path_candidate).name]
        for alt_name in search_names:
            found_path = shutil.which(alt_name)
            if found_path:
                logger.info(f"Found executable in system PATH: {found_path}")
                return Path(found_path)

        common_locations = [
            Path.home() / "bin",
            Path.home() / ".local" / "bin",
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path.cwd()
        ]

        for location in common_locations:
            for alt_name in search_names:
                test_path = location / alt_name
                if test_path.is_file():
                    logger.info(f"Found executable in common location: {test_path}")
                    return test_path

        logger.warning(f"Executable not found after extensive search: {path_candidate}")
        return path

    def _log_tool_status(self):
        """Log the status of all tools."""
        tools = {
            "RuSTy Compiler": self.rusty_path,
            "nuXmv Verifier": self.nuxmv_path,
            "PLCVerif Tool": self.plcverif_path
        }

        logger.info("🔧 Tool Status Check:")
        for name, path in tools.items():
            if path.is_file():
                try:
                    result = subprocess.run([str(path), "--version"], 
                                          capture_output=True, text=True, timeout=5)
                    status = "✅ WORKING"
                    version_info = f" (Version: {result.stdout.strip()})" if result.stdout else ""
                except:
                    status = "✅ FOUND"
                    version_info = ""
                logger.info(f"   {status} {name}: {path}{version_info}")
            else:
                logger.warning(f"   ❌ MISSING {name}: {path}")

    def generate_st_code(self, requirements: str) -> Tuple[Optional[str], Optional[str]]:
        """Generate ST code using Ollama API."""
        logger.info("Generating ST code with standard prompt...")

        prompt = f"""
        You are an expert PLC programmer following the IEC 61131-3 standard. Your **PRIMARY TASK** is to generate a **COMPLETE and VALID Structured Text (ST) file** from the given requirements.

        CRITICAL REQUIREMENTS FOR RuSTy COMPILER:
        - Use ONLY basic ST syntax: IF-THEN-ELSE, assignments (:=), AND, OR, NOT operators
        - NO function blocks, NO timers, NO counters, NO advanced features
        - Use only BOOL and INT types for simplicity
        - Ensure all variables are properly declared
        - Make the logic simple and sequential

        You **MUST** include all necessary structural elements: **PROGRAM MainProgram...END_PROGRAM**, **VAR_INPUT**, **VAR_OUTPUT**, and **VAR**. The final ST code block must be runnable and include proper variable declarations for all used tags.

        First, you will reason about the solution. Second, you will write the complete code. You must follow the output format exactly.

        **Requirements:**
        {requirements}

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

        (* Simple sequential logic *)

            (* Implement basic logic here *) 

        END_PROGRAM 
        ``` 
        """ 

        try:
            payload = {
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1}
            }

            response = requests.post(
                f"{self.api_url}/api/generate",
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            full_response = response.json().get("response", "").strip()

            reasoning_part = None
            code_part = None

            code_match = re.search(r'```[sS][tT]?\s*
(.*?)
\s*```', full_response, re.DOTALL)
            if code_match:
                code_part = code_match.group(1).strip()
            else:
                logger.error("Failed to find the ST code block.")
                return None, None 

            if "---REASONING---" in full_response and "---CODE---" in full_response:
                try:
                    start_index = full_response.index("---REASONING---") + len("---REASONING---")
                    end_index = full_response.index("---CODE---")
                    reasoning_part = full_response[start_index:end_index].strip()
                except ValueError:
                    reasoning_part = full_response.split("---REASONING---")[-1].strip() 

            return reasoning_part, code_part

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return None, f"Error: Failed to connect to Ollama ({self.api_url}). Details: {e}"
        except Exception as e:
            logger.error(f"Generation error: {e}")
            return None, f"Error: Generation failed due to internal error: {e}"

    def compile_st_code(self, st_code: str, filename: str) -> Optional[str]:
        """Compile ST code using RuSTy to generate LLVM IR."""
        logger.info(f"Compiling ST file: {filename}")
        st_file = self.output_dir / filename
        ir_file = self.output_dir / f"{Path(filename).stem}.ll"

        try:
            cleaned_st_code = self._clean_st_code_for_rusty(st_code)
            st_file.write_text(cleaned_st_code, encoding='utf-8')
            logger.info(f"📝 ST file saved: {st_file}")
        except IOError as e:
            logger.error(f"Failed to write ST file '{st_file}': {e}")
            return f"❌ Error: Failed to write ST file: {e}"

        if not self.rusty_path.is_file():
            logger.error("Cannot compile: RuSTy compiler not found.")
            return f"⚠️ RuSTy compiler not found at {self.rusty_path}. ST file saved to {st_file}."

        cmd = [str(self.rusty_path), "--output", str(ir_file), str(st_file)]

        logger.info(f"Running command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=True
            )

            if ir_file.exists():
                logger.info(f"✅ Successfully compiled ST to LLVM IR: {ir_file}")
                return f"✅ SUCCESS: Compiled to LLVM IR: {ir_file}
Output: {result.stdout.strip()}"

            return f"⚠️ Compilation completed but output file {ir_file} was not found.
Output: {result.stdout.strip()}"

        except subprocess.CalledProcessError as e:
            logger.error(f"Compilation failed with return code {e.returncode}.")
            error_context = self._analyze_compilation_error(e.stderr, e.stdout, st_code)
            return f"❌ Compilation FAILED (code {e.returncode}).
ST file saved to: {st_file}
{error_context}
Stderr:
{e.stderr}
Stdout:
{e.stdout}"

        except subprocess.TimeoutExpired:
            return f"⏰ Compilation timed out after {self.timeout} seconds. ST file saved to: {st_file}"

        except Exception as e:
            return f"❌ Unexpected compilation error: {e}. ST file saved to: {st_file}"

    def _analyze_compilation_error(self, stderr: str, stdout: str, st_code: str) -> str:
        """Analyze compilation errors and provide helpful suggestions."""
        error_lower = stderr.lower() + stdout.lower()

        if "syntax error" in error_lower:
            return "🔍 Issue: Syntax error detected. Check for missing semicolons, parentheses, or incorrect variable declarations."
        elif "undefined" in error_lower:
            return "🔍 Issue: Undefined variable or function. Ensure all variables are declared in VAR sections."
        elif "type mismatch" in error_lower or "type error" in error_lower:
            return "🔍 Issue: Type mismatch. Check variable types in assignments and comparisons."
        elif "expected" in error_lower:
            return "🔍 Issue: Parser expected different syntax. Check ST structure and keywords."

        if "PROGRAM" not in st_code:
            return "🔍 Issue: Missing PROGRAM declaration. ST code must start with 'PROGRAM MainProgram'."
        if "END_PROGRAM" not in st_code:
            return "🔍 Issue: Missing END_PROGRAM. Ensure the program is properly closed."

        return "🔍 Check the ST code structure and variable declarations."

    def _clean_st_code_for_rusty(self, st_code: str) -> str:
        """Clean ST code to improve RuSTy compatibility."""
        cleaned = re.sub(r'\(\*.*?\*\)', '', st_code, flags=re.DOTALL)

        if "PROGRAM" not in cleaned:
            cleaned = "PROGRAM MainProgram
" + cleaned
        if "END_PROGRAM" not in cleaned:
            cleaned += "
END_PROGRAM"

        cleaned = re.sub(r'VAR_\w+\s*END_VAR', '', cleaned, flags=re.IGNORECASE)

        return cleaned

    def translate_to_smv(self, st_code: str, filename: str) -> Optional[str]:
        """Translate ST code to SMV format."""
        logger.info(f"Translating to SMV file: {filename}")
        smv_file = self.output_dir / filename

        try:
            st_code_no_comments = re.sub(r'\(\*.*?\*\)', '', st_code, flags=re.DOTALL)
            st_code_no_comments = re.sub(r'//.*', '', st_code_no_comments)

            variables = set()
            assignments = []

            var_pattern = re.compile(r'^\s*(\w+)\s*:\s*\w+\s*;', re.IGNORECASE)
            assign_pattern = re.compile(r'^\s*(\w+)\s*:=\s*(.*?);', re.IGNORECASE)

            in_var_block = False
            for line in st_code_no_comments.splitlines():
                line = line.strip()
                if not line: continue

                if re.match(r'VAR_INPUT|VAR_OUTPUT|VAR', line, re.IGNORECASE):
                    in_var_block = True
                    continue
                if re.match(r'END_VAR', line, re.IGNORECASE):
                    in_var_block = False
                    continue

                if in_var_block:
                    var_match = var_pattern.match(line)
                    if var_match:
                        variables.add(var_match.group(1).strip())
                else:
                    assign_match = assign_pattern.match(line)
                    if assign_match:
                        lhs = assign_match.group(1).strip()
                        rhs = assign_match.group(2).strip()

                        rhs = re.sub(r'AND', '&', rhs, flags=re.IGNORECASE)
                        rhs = re.sub(r'OR', '|', rhs, flags=re.IGNORECASE)
                        rhs = re.sub(r'NOT', '!', rhs, flags=re.IGNORECASE)
                        rhs = re.sub(r'XOR', 'xor', rhs, flags=re.IGNORECASE)
                        rhs = re.sub(r'TRUE', 'TRUE', rhs, flags=re.IGNORECASE)
                        rhs = re.sub(r'FALSE', 'FALSE', rhs, flags=re.IGNORECASE)

                        assignments.append((lhs, rhs))
                        variables.add(lhs)

            smv_content = ["MODULE main", "VAR"]
            for var in sorted(list(variables)):
                smv_content.append(f"    {var} : boolean;")

            smv_content.append("
ASSIGN")

            for var in sorted(list(variables)):
                smv_content.append(f"    init({var}) := FALSE;")

            for lhs, rhs in assignments:
                smv_content.append(f"    next({lhs}) := {rhs};")

            assigned_vars = {lhs for lhs, rhs in assignments}
            for var in sorted(list(variables)):
                if var not in assigned_vars:
                    smv_content.append(f"    next({var}) := {var};")

            smv_content.append("
-- Comprehensive LTL Properties for Verification")
            smv_content.append("-- Safety Properties (should never happen)")

            for var in sorted(list(variables)):
                smv_content.append(f"LTLSPEC G !({var} & !{var})  -- {var} cannot be both true and false")

            if any('start' in var.lower() for var in variables) and any('stop' in var.lower() for var in variables):
                start_vars = [var for var in variables if 'start' in var.lower()]
                stop_vars = [var for var in variables if 'stop' in var.lower()]
                for start_var in start_vars:
                    for stop_var in stop_vars:
                        smv_content.append(f"LTLSPEC G !({start_var} & {stop_var})  -- {start_var} and {stop_var} should not be active simultaneously")

            smv_content.append("
-- Liveness Properties (should eventually happen)")
            for var in sorted(list(variables)):
                if any(x in var.lower() for x in ['alarm', 'error', 'fault']):
                    smv_content.append(f"LTLSPEC G ({var} -> F !{var})  -- {var} should eventually clear")

            smv_file.write_text("
".join(smv_content), encoding='utf-8')
            logger.info(f"✅ Successfully translated ST to SMV file: {smv_file}")
            return str(smv_file)

        except Exception as e:
            logger.error(f"SMV translation error: {e}")
            fallback_smv = """MODULE main
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

-- Comprehensive LTL Properties for Verification

-- Safety Properties (should never happen)
LTLSPEC G !(state & !state)  -- State cannot be both true and false
LTLSPEC G !(output_signal & !input_signal)  -- Output should not be active without input

-- Liveness Properties (should eventually happen)
LTLSPEC G (state -> F !state)  -- State should eventually change
LTLSPEC G (input_signal -> F !input_signal)  -- Input should eventually change
"""
            smv_file.write_text(fallback_smv, encoding='utf-8')
            return f"⚠️ Used fallback SMV due to translation error: {e}
SMV file: {smv_file}"

    def verify_with_nuxmv(self, smv_file_path: str, properties: Optional[str] = None) -> Optional[str]:
        """Verify the SMV model using nuXmv."""
        logger.info("Verifying SMV model with nuXmv...")
        smv_file = Path(smv_file_path)

        if not smv_file.is_file():
            return f"❌ Error: SMV file not found for verification: {smv_file}"

        if not self.nuxmv_path.is_file():
            return f"⚠️ nuXmv executable not found at {self.nuxmv_path}. Verification skipped. SMV file: {smv_file}"

        smv_with_props_path = self.output_dir / f"{smv_file.stem}_with_props.smv"

        try:
            original_content = smv_file.read_text(encoding='utf-8')

            if properties:
                properties_smv = self._convert_properties_to_smv(properties)
                full_content = original_content + "

" + properties_smv
            else:
                full_content = original_content

            smv_with_props_path.write_text(full_content, encoding='utf-8')

            cmd = [str(self.nuxmv_path), "-int", str(smv_with_props_path)]
            logger.info(f"Running command: {' '.join(cmd)}")

            input_commands = ["go", "check_ltlspec", "quit"]

            result = subprocess.run(
                cmd,
                input="
".join(input_commands),
                capture_output=True,
                text=True,
                timeout=self.timeout * 2
            )

            output = result.stdout + "
" + result.stderr
            analysis = self._analyze_nuxmv_output(output)

            if result.returncode != 0:
                return f"⚠️ nuXmv Execution completed with warnings (return code: {result.returncode}).
{analysis}
Output:
{output.strip()}"

            return f"nuXmv Verification Complete
{analysis}
Output:
{output.strip()}"

        except subprocess.TimeoutExpired:
            return f"⏰ Error: nuXmv verification timed out after {self.timeout * 2} seconds."
        except Exception as e:
            return f"❌ Error during nuXmv verification: {e}"

    def _analyze_nuxmv_output(self, output: str) -> str:
        """Analyze nuXmv output and provide summary."""
        lines = output.split('
')
        analysis = []

        true_count = 0
        false_count = 0

        for i, line in enumerate(lines):
            line = line.strip()
            if "is true" in line:
                true_count += 1
                for j in range(max(0, i-5), i):
                    if "LTLSPEC" in lines[j]:
                        spec = lines[j].strip()
                        analysis.append(f"✅ VERIFIED: {spec}")
                        break
            elif "is false" in line:
                false_count += 1
                for j in range(max(0, i-5), i):
                    if "LTLSPEC" in lines[j]:
                        spec = lines[j].strip()
                        analysis.append(f"❌ VIOLATED: {spec}")
                        break

        summary = f"**Verification Summary:**
"
        summary += f"✅ Verified: {true_count}
"
        summary += f"❌ Violated: {false_count}
"
        summary += f"📊 Total: {true_count + false_count}

"

        if analysis:
            summary += "**Detailed Results:**
" + "
".join(analysis) + "
"

        return summary

    def _convert_properties_to_smv(self, properties: str) -> str:
        """Convert ST-style properties to SMV LTLSPEC format."""
        smv_properties = []

        ltl_pattern = r'\(\*!\s*LTL\s+(.*?)\s*\*\)'
        matches = re.finditer(ltl_pattern, properties, re.DOTALL | re.IGNORECASE)

        for match in matches:
            ltl_expr = match.group(1).strip()
            smv_properties.append(f"LTLSPEC {ltl_expr}")

        if not smv_properties and properties.strip():
            prop_lines = properties.strip().split('
')
            for prop in prop_lines:
                if prop.strip():
                    smv_properties.append(f"LTLSPEC {prop.strip()}")

        return "
".join(smv_properties)

    def verify_with_plcverif(self, st_code: str, properties: str, topic: str) -> Optional[str]:
        """Verify the ST code using plcverif."""
        logger.info(f"Verifying ST code for topic: {topic}")

        if not self.plcverif_path.is_file():
            return f"⚠️ PLCVerif executable not found at {self.plcverif_path}. Verification skipped."

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{topic[:30]}.st"
        st_file_path = self.output_dir / filename

        st_with_props_code = st_code + "

" + properties

        try:
            st_file_path.write_text(st_with_props_code, encoding='utf-8')

            cmd = [str(self.plcverif_path), str(st_file_path)]
            logger.info(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout)

            output = result.stdout + "
" + result.stderr
            if result.returncode != 0 and "error" in output.lower():
                return f"⚠️ PLCVerif completed with warnings.
Output:
{output.strip()}"

            return f"✅ PLCVerif Verification completed.
Output:
{output.strip()}"

        except subprocess.TimeoutExpired:
            return f"⏰ Error: PLCVerif execution timed out after {self.timeout} seconds."
        except Exception as e:
            return f"❌ Error during PLCVerif execution: {e}"

    def process_requirements(self, requirements: str, plcverif_properties: Optional[str] = None) -> Dict[str, Any]:
        """Process user requirements through the full pipeline."""
        topic_slug = "plc_program"
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            first_line = requirements.strip().split('
')[0]
            topic_slug_candidate = re.sub(r'[^a-z0-9\s-]', '', first_line.lower()).strip()
            topic_slug_candidate = re.sub(r'[\s-]+', '_', topic_slug_candidate)[:40].strip('_')
            topic_slug = topic_slug_candidate if topic_slug_candidate else "plc_program"

            base_filename = f"{timestamp}_{topic_slug}"
            st_filename = f"{base_filename}.st"
            smv_filename = f"{base_filename}.smv"

        except Exception:
            st_filename = "program.st"
            smv_filename = "program.smv"

        result = {
            "status": "failed", 
            "error": None,
            "tool_status": {
                "rusty": self.rusty_path.is_file(),
                "nuxmv": self.nuxmv_path.is_file(),
                "plcverif": self.plcverif_path.is_file()
            },
            "steps": {
                "generate": {"success": False, "reasoning": None, "output": None},
                "compile": {"success": False, "output": None},
                "translate": {"success": False, "output": None},
                "verify_nuxmv": {"success": False, "output": None},
                "verify_plcverif": {"success": False, "output": None}
            }
        }

        try:
            reasoning, st_code = self.generate_st_code(requirements)
            result["steps"]["generate"]["reasoning"] = reasoning
            result["steps"]["generate"]["output"] = st_code
            if not st_code or st_code.startswith("Error:"):
                result["error"] = st_code if st_code and st_code.startswith("Error:") else "Failed to generate ST code."
                return result
            result["steps"]["generate"]["success"] = True

            compile_result = self.compile_st_code(st_code, filename=st_filename)
            result["steps"]["compile"]["output"] = compile_result
            if compile_result and "✅ SUCCESS" in compile_result:
                result["steps"]["compile"]["success"] = True
            elif compile_result and "⚠️" in compile_result:
                result["steps"]["compile"]["success"] = False

            smv_file = self.translate_to_smv(st_code, filename=smv_filename)
            result["steps"]["translate"]["output"] = smv_file
            if smv_file and "✅" in smv_file:
                result["steps"]["translate"]["success"] = True
            elif smv_file and "⚠️" in smv_file:
                result["steps"]["translate"]["success"] = True

            if result["steps"]["translate"]["success"] and self.nuxmv_path.is_file():
                if smv_file is not None:
                    verification_result = self.verify_with_nuxmv(smv_file, plcverif_properties)
                    result["steps"]["verify_nuxmv"]["output"] = verification_result
                    if verification_result and "❌" not in verification_result:
                        result["steps"]["verify_nuxmv"]["success"] = True
                    elif verification_result and "⚠️" in verification_result:
                        result["steps"]["verify_nuxmv"]["success"] = True

            if plcverif_properties and self.plcverif_path.is_file():
                plcverif_result = self.verify_with_plcverif(st_code, plcverif_properties, topic_slug)
                result["steps"]["verify_plcverif"]["output"] = plcverif_result
                if plcverif_result and "✅" in plcverif_result:
                    result["steps"]["verify_plcverif"]["success"] = True

            successful_steps = sum(1 for step in result["steps"].values() if step["success"])
            total_steps = len([step for step in result["steps"].values() if step["output"] is not None])

            if successful_steps == total_steps and successful_steps > 0:
                result["status"] = "success"
            elif successful_steps > 0:
                result["status"] = "partial"
            else:
                result["status"] = "failed"

            logger.info(f"Pipeline completed with status: {result['status']}")
            return result

        except Exception as e:
            logger.critical(f"A critical error occurred in the pipeline: {e}", exc_info=True)
            result["error"] = str(e)
            result["status"] = "failed"
            return result


# =============================================================================
# RAG-ENHANCED ENGINE
# =============================================================================

class Ollama4PLC_RAG_Engine(Ollama4PLC):
    """
    Extended Ollama4PLC engine with RAG (Retrieval-Augmented Generation) support.

    This class extends the base Ollama4PLC with semantic retrieval capabilities,
    allowing the LLM to reference relevant PLC code examples during generation.
    """

    def __init__(self, **kwargs):
        """
        Initialize the RAG-enhanced engine.

        Additional kwargs:
            rag_enabled: Enable/disable RAG (default: from config)
            rag_db_dir: Vector database directory
            rag_dataset_paths: List of dataset file paths
            rag_embedding_model: Ollama embedding model name
            rag_top_k: Number of retrieved examples
        """
        # Initialize base engine first
        super().__init__(**kwargs)

        # RAG configuration
        rag_config = config.get("rag", {})

        self.rag_enabled = kwargs.get("rag_enabled", rag_config.get("enabled", False))
        self.rag_db_dir = kwargs.get("rag_db_dir", rag_config.get("db_dir", "./database/st_db"))
        self.rag_dataset_paths = kwargs.get(
            "rag_dataset_paths", 
            rag_config.get("dataset_paths", [])
        )
        self.rag_embedding_model = kwargs.get(
            "rag_embedding_model",
            rag_config.get("embedding_model", "nomic-embed-text")
        )
        self.rag_top_k = kwargs.get("rag_top_k", rag_config.get("top_k", 3))

        # Initialize RAG pipeline if enabled
        self._rag_pipeline = None

        if self.rag_enabled:
            try:
                self._init_rag()
            except Exception as e:
                logger.warning(f"RAG initialization failed: {e}. Falling back to standard generation.")
                self.rag_enabled = False

    def _init_rag(self):
        """Initialize the RAG pipeline."""
        logger.info("Initializing RAG pipeline...")

        self._rag_pipeline = Ollama4PLC_RAG(
            db_dir=self.rag_db_dir,
            dataset_paths=self.rag_dataset_paths,
            embedding_model=self.rag_embedding_model,
            llm_model=self.ollama_model,
            ollama_base_url=self.api_url,
            top_k=self.rag_top_k
        )

        # Build or load database
        if self.rag_dataset_paths:
            self._rag_pipeline.build_database()
        else:
            # Try to load existing database
            if Path(self.rag_db_dir).exists():
                self._rag_pipeline.build_database()
            else:
                logger.warning("No dataset paths provided and no existing database found. RAG disabled.")
                self.rag_enabled = False
                return

        logger.info("✅ RAG pipeline initialized successfully")

    def generate_st_code(self, requirements: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate ST code with optional RAG enhancement.

        If RAG is enabled, retrieves relevant PLC code examples and includes
        them in the prompt for context-aware generation.
        """
        if not self.rag_enabled or self._rag_pipeline is None:
            logger.info("RAG disabled or unavailable. Using standard generation.")
            return super().generate_st_code(requirements)

        logger.info("Generating ST code with RAG enhancement...")

        try:
            reasoning, code = self._rag_pipeline.generate_st_with_rag(requirements)

            # Add RAG metadata to reasoning
            if reasoning:
                reasoning = f"[RAG-Enhanced Generation]\n{reasoning}"

            return reasoning, code

        except Exception as e:
            logger.error(f"RAG generation failed: {e}. Falling back to standard generation.")
            return super().generate_st_code(requirements)

    def get_rag_status(self) -> Dict[str, Any]:
        """Get current RAG pipeline status."""
        status = {
            "enabled": self.rag_enabled,
            "db_dir": self.rag_db_dir,
            "dataset_paths": self.rag_dataset_paths,
            "embedding_model": self.rag_embedding_model,
            "top_k": self.rag_top_k,
            "initialized": self._rag_pipeline is not None
        }

        if self._rag_pipeline and self._rag_pipeline._vectorstore:
            try:
                status["document_count"] = self._rag_pipeline._vectorstore._collection.count()
            except:
                status["document_count"] = "unknown"

        return status


# =============================================================================
# GLOBAL ENGINE INITIALIZATION
# =============================================================================

try:
    if not check_ollama_server(config["api_base_url"]):
        logger.critical("Ollama server check failed. Application will not function.")

    # Determine which engine to use based on RAG config
    rag_config = config.get("rag", {})
    if rag_config.get("enabled", False):
        logger.info("Initializing RAG-enhanced engine...")
        ollama_engine = Ollama4PLC_RAG_Engine(**config)
    else:
        logger.info("Initializing standard engine...")
        ollama_engine = Ollama4PLC(**config)

    ENGINE_STATUS = "Ready"
except Exception as e:
    logger.critical(f"Failed to initialize Ollama4PLC engine: {e}")
    ollama_engine = None
    ENGINE_STATUS = f"Initialization Error: {e}"


# =============================================================================
# FLASK ROUTES
# =============================================================================

@app.route('/', methods=['GET'])
def index():
    """Renders the main input form."""

    status_warning = None
    if ENGINE_STATUS != "Ready":
        status_warning = ENGINE_STATUS

    # Check RAG status
    rag_status = None
    if isinstance(ollama_engine, Ollama4PLC_RAG_Engine):
        rag_status = ollama_engine.get_rag_status()

    default_requirements = (
        "create ST code for a simple start/stop motor control.
"
        "Inputs: Start_PB, Stop_PB. Outputs: Motor_Run.
"
        "Logic: Pressing Start_PB turns on Motor_Run, which stays on until Stop_PB is pressed."
    )
    default_properties = "(*! LTL G (Motor_Run -> F !Stop_PB) *)
(*! LTL G !(Motor_Run & Stop_PB) *)"

    return render_template(
        'index.html',
        status_warning=status_warning,
        default_requirements=default_requirements,
        default_properties=default_properties,
        rag_status=rag_status
    )

@app.route('/process', methods=['POST'])
def process_pipeline():
    """Handles the form submission and runs the pipeline."""

    if ollama_engine is None or ENGINE_STATUS != "Ready":
        return render_template('results.html', 
                            result={
                                "status": "failed", 
                                "error": f"Engine not initialized. {ENGINE_STATUS}", 
                                "original_requirements": "N/A", 
                                "duration": "0s",
                                "tool_status": {
                                    "rusty": False,
                                    "nuxmv": False, 
                                    "plcverif": False
                                }
                            })

    requirements = request.form.get('requirements', '').strip()
    plcverif_properties = request.form.get('plcverif_properties', '').strip()

    if not requirements:
        return redirect(url_for('index'))

    logger.info("Starting pipeline process from web request.")
    start_time = time.time()

    result = ollama_engine.process_requirements(requirements, plcverif_properties)

    duration = time.time() - start_time
    logger.info(f"Web pipeline execution finished in {duration:.2f} seconds.")

    result['original_requirements'] = requirements
    result['original_properties'] = plcverif_properties
    result['duration'] = f"{duration:.2f}s"

    # Add RAG info if applicable
    if isinstance(ollama_engine, Ollama4PLC_RAG_Engine):
        result['rag_status'] = ollama_engine.get_rag_status()

    return render_template('results.html', result=result)

@app.route('/rag_status', methods=['GET'])
def rag_status():
    """Get RAG pipeline status (JSON API)."""
    if ollama_engine is None:
        return jsonify({"error": "Engine not initialized"}), 500

    if isinstance(ollama_engine, Ollama4PLC_RAG_Engine):
        return jsonify(ollama_engine.get_rag_status())
    else:
        return jsonify({
            "enabled": False,
            "message": "RAG not enabled. Use RAG-enhanced engine to enable."
        })

@app.route('/download_st', methods=['POST'])
def download_st():
    """Takes ST code from a POST request and serves it as a downloadable file."""
    st_code = request.form.get('st_code', '')

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"plc_code_{timestamp}.st"

    if not st_code:
        return "Error: No code provided for download.", 400

    response = Response(
        response=st_code,
        status=200,
        mimetype='text/plain'
    )
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


# =============================================================================
# MAIN BLOCK
# =============================================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
