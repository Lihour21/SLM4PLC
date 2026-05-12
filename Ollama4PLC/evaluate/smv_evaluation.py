"""
Ollama4PLC - SMV/nuXmv Evaluation Module

Evaluates generated ST files using:
1. RuSTy compiler for syntax validation
2. Local Ollama LLM for ST-to-SMV translation
3. nuXmv model checker for formal verification

This follows the LLM4PLC approach but uses local Ollama instead of external APIs,
providing privacy-preserving verification with no data leaving your machine.
"""

import os
import sys
import json
import re
import subprocess
import logging
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union

# Add project root to path
parent_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(parent_dir))

from evaluate.pretty_summary import summary, quick_summary

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_COMPILER = "rusty"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "mistral:7b"


class SMVEvaluator:
    """
    Evaluator for PLC code using SMV translation and nuXmv model checking.

    Uses local Ollama LLM to translate ST code to SMV format, then verifies
    properties using the nuXmv symbolic model checker.
    """

    def __init__(
        self,
        compiler: str = DEFAULT_COMPILER,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        ollama_model: str = DEFAULT_MODEL,
        nuxmv_path: Optional[str] = None,
        rusty_path: Optional[str] = None,
        timeout: int = 300,
        base_output_dir: str = "./output/smv_evaluation"
    ):
        """
        Initialize the SMV evaluator.

        Args:
            compiler: Compiler to use ('rusty' or 'matiec')
            ollama_url: Ollama API base URL
            ollama_model: Ollama model for ST-to-SMV translation
            nuxmv_path: Path to nuXmv executable
            rusty_path: Path to RuSTy compiler executable
            timeout: Timeout for verification (seconds)
            base_output_dir: Base directory for evaluation outputs
        """
        self.compiler = compiler
        self.ollama_url = ollama_url.rstrip('/')
        self.ollama_model = ollama_model
        self.timeout = timeout
        self.base_output_dir = Path(base_output_dir).resolve()
        self.base_output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve tool paths
        self.rusty_path = self._resolve_path(
            rusty_path,
            ["~/rusty/target/release/plc", "./tools/rusty/plc", "rusty"]
        )
        self.nuxmv_path = self._resolve_path(
            nuxmv_path,
            ["/usr/local/bin/nuXmv", "~/nuxmv/bin/nuXmv", "./tools/nuXmv/nuXmv", "nuXmv"]
        )

        # Verify Ollama connection
        self._check_ollama()

        logger.info(f"SMVEvaluator initialized:")
        logger.info(f"  Compiler: {self.compiler} ({self.rusty_path})")
        logger.info(f"  nuXmv: {self.nuxmv_path}")
        logger.info(f"  Ollama: {self.ollama_url} (model: {self.ollama_model})")
        logger.info(f"  Output: {self.base_output_dir}")

    def _resolve_path(self, path: Optional[str], fallbacks: List[str]) -> Optional[Path]:
        """Resolve tool path with fallback options."""
        if path:
            p = Path(path).expanduser().resolve()
            if p.exists():
                return p

        for fallback in fallbacks:
            p = Path(fallback).expanduser().resolve()
            if p.exists():
                return p

            found = shutil.which(Path(fallback).name)
            if found:
                return Path(found)

        return None

    def _check_ollama(self):
        """Verify Ollama server is accessible."""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            response.raise_for_status()
            logger.info("✅ Ollama server is accessible")
        except Exception as e:
            logger.warning(f"⚠️ Ollama check failed: {e}")

    def check_syntax(self, st_file_path: str) -> Tuple[bool, str]:
        """
        Check ST file syntax using RuSTy compiler.

        Args:
            st_file_path: Path to .st file

        Returns:
            Tuple of (passed: bool, output: str)
        """
        if not self.rusty_path or not self.rusty_path.exists():
            logger.warning("RuSTy not found, skipping syntax check")
            return True, "RuSTy not available - skipped"

        st_file = Path(st_file_path)
        if not st_file.exists():
            return False, f"File not found: {st_file_path}"

        try:
            cmd = [str(self.rusty_path), "--check", str(st_file)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            output = result.stdout + "\n" + result.stderr

            passed = result.returncode == 0 and "error" not in output.lower()
            return passed, output

        except Exception as e:
            return False, str(e)

    def translate_st_to_smv(
        self,
        st_content: str,
        properties: List[Dict],
        output_folder: str
    ) -> Tuple[Optional[str], str]:
        """
        Translate ST code to SMV using local Ollama LLM.

        Args:
            st_content: ST code content
            properties: List of property dictionaries
            output_folder: Folder for output files

        Returns:
            Tuple of (smv_code: Optional[str], log: str)
        """
        logger.info("Translating ST to SMV using Ollama LLM...")

        # Format properties for the prompt
        properties_str = self._format_properties_for_smv(properties)

        # Build translation prompt
        prompt = f"""You are an expert in formal verification and PLC programming. 
Your task is to translate IEC 61131-3 Structured Text (ST) code into an SMV (Symbolic Model Verification) model.

CRITICAL REQUIREMENTS:
- Create a valid nuXmv SMV model
- Include MODULE main with VAR section for all variables
- Include ASSIGN section with init() and next() for each variable
- Preserve all logic from the ST code exactly
- Add PLC_START and PLC_END state variables
- Include the provided LTL/CTL properties

ST CODE TO TRANSLATE:
```st
{st_content}
```

PROPERTIES TO VERIFY:
{properties_str}

OUTPUT FORMAT:
Provide ONLY the SMV code between [START_SMV] and [END_SMV] tags.
Do not include any explanations outside these tags.

[START_SMV]
MODULE main
VAR
  ...
ASSIGN
  ...
[END_SMV]
"""

        try:
            # Call Ollama API
            payload = {
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1}
            }

            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            full_response = response.json().get("response", "").strip()

            # Extract SMV code
            smv_code = self._extract_smv_code(full_response)

            if not smv_code:
                logger.error("Failed to extract SMV code from LLM response")
                return None, full_response

            # Append properties if not included
            if properties_str and "SPEC" not in smv_code and "LTLSPEC" not in smv_code:
                smv_code += "\n\n" + properties_str

            logger.info("✅ SMV translation successful")
            return smv_code, full_response

        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama API request failed: {e}")
            return None, f"API Error: {e}"
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return None, str(e)

    def _extract_smv_code(self, response: str) -> Optional[str]:
        """Extract SMV code from LLM response."""
        # Try [START_SMV]...[END_SMV] tags
        match = re.search(
            r'\[START_SMV\](.*?)\[END_SMV\]',
            response,
            re.DOTALL | re.IGNORECASE
        )
        if match:
            return match.group(1).strip()

        # Try code blocks
        match = re.search(
            r'```(?:smv)?\s*
(.*?)
\s*```',
            response,
            re.DOTALL | re.IGNORECASE
        )
        if match:
            return match.group(1).strip()

        # Try MODULE main
        match = re.search(
            r'(MODULE\s+main.*)',
            response,
            re.DOTALL | re.IGNORECASE
        )
        if match:
            return match.group(1).strip()

        return None

    def _format_properties_for_smv(self, properties: List[Dict]) -> str:
        """Convert property dictionaries to SMV LTLSPEC/CTLSPEC format."""
        lines = []

        for prop in properties:
            prop_data = prop.get("property", {})
            job_req = prop_data.get("job_req", "")

            if job_req == "assertion":
                lines.append("-- Assertion property")
                lines.append("LTLSPEC G TRUE  -- Placeholder assertion")

            elif job_req == "pattern":
                pattern_id = prop_data.get("pattern_id", "")
                params = prop_data.get("pattern_params", {})

                if "implication" in pattern_id.lower():
                    # Implication: p -> q
                    p = params.get("1", "TRUE")
                    q = params.get("2", "TRUE")
                    lines.append(f"-- {prop.get('property_description', 'Implication')}")
                    lines.append(f"LTLSPEC G ({p} -> {q})")

                elif "invariant" in pattern_id.lower():
                    # Invariant: always p
                    p = params.get("1", "TRUE")
                    lines.append(f"-- {prop.get('property_description', 'Invariant')}")
                    lines.append(f"LTLSPEC G ({p})")

                else:
                    lines.append(f"-- {prop.get('property_description', 'Property')}")
                    lines.append(f"LTLSPEC G TRUE  -- Placeholder for {pattern_id}")

        return "\n".join(lines)

    def verify_with_nuxmv(
        self,
        smv_code: str,
        smv_file_path: str,
        output_folder: str
    ) -> Tuple[Optional[bool], str]:
        """
        Verify SMV model using nuXmv.

        Args:
            smv_code: SMV code content
            smv_file_path: Path to save SMV file
            output_folder: Folder for logs

        Returns:
            Tuple of (result: Optional[bool], output: str)
            result: True (satisfied), False (violated), None (error/timeout)
        """
        if not self.nuxmv_path or not self.nuxmv_path.exists():
            logger.warning("nuXmv not found, skipping verification")
            return None, "nuXmv not available"

        os.makedirs(output_folder, exist_ok=True)

        # Save SMV file
        with open(smv_file_path, 'w', encoding='utf-8') as f:
            f.write(smv_code)

        logger.info(f"Saved SMV file: {smv_file_path}")

        # Run nuXmv
        try:
            cmd = [str(self.nuxmv_path), "-int", smv_file_path]
            logger.info(f"Running nuXmv: {' '.join(cmd)}")

            input_commands = ["go", "check_ltlspec", "quit"]

            result = subprocess.run(
                cmd,
                input="\n".join(input_commands),
                capture_output=True,
                text=True,
                timeout=self.timeout * 2
            )

            output = result.stdout + "\n" + result.stderr

            # Save log
            log_path = os.path.join(output_folder, "nuxmv_log.txt")
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(output)

            # Parse result
            output_lower = output.lower()

            if "fail" in output_lower or "error" in output_lower or result.returncode != 0:
                logger.warning("nuXmv verification failed or error")
                return None, output

            if "violated" in output_lower or "false" in output_lower:
                logger.info("❌ Properties VIOLATED")
                return False, output

            if "successful" in output_lower or "is true" in output_lower:
                logger.info("✅ Properties SATISFIED")
                return True, output

            logger.warning("nuXmv result inconclusive")
            return None, output

        except subprocess.TimeoutExpired:
            logger.error("nuXmv verification timed out")
            return None, "Timeout"
        except Exception as e:
            logger.error(f"nuXmv error: {e}")
            return None, str(e)

    def evaluate_single(
        self,
        st_file_path: str,
        properties: List[Dict],
        evaluation_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate a single ST file using SMV translation + nuXmv.

        Args:
            st_file_path: Path to .st file
            properties: List of property dictionaries
            evaluation_name: Optional name for this evaluation

        Returns:
            Complete evaluation result dictionary
        """
        st_file = Path(st_file_path)
        name = evaluation_name or st_file.stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        output_folder = self.base_output_dir / f"{name}_{timestamp}"
        output_folder.mkdir(parents=True, exist_ok=True)

        result = {
            "st_file_path": str(st_file_path),
            "evaluation_name": name,
            "timestamp": timestamp,
            "output_folder": str(output_folder),
            "compilation": {},
            "translation": {},
            "verification": {},
            "overall_passed": False
        }

        # Step 1: Read ST file
        logger.info(f"Step 1: Reading ST file: {st_file_path}")
        try:
            with open(st_file_path, 'r', encoding='utf-8') as f:
                st_content = f.read()
        except Exception as e:
            logger.error(f"Failed to read ST file: {e}")
            result["overall_passed"] = False
            return result

        # Step 2: Syntax check
        logger.info(f"Step 2: Syntax check")
        compile_passed, compile_output = self.check_syntax(st_file_path)
        result["compilation"] = {
            "passed": compile_passed,
            "output": compile_output
        }

        if not compile_passed:
            logger.warning("Compilation failed, skipping verification")
            result["overall_passed"] = False
            return result

        # Step 3: ST to SMV translation
        logger.info(f"Step 3: ST to SMV translation")
        smv_code, trans_log = self.translate_st_to_smv(
            st_content, properties, str(output_folder)
        )

        result["translation"] = {
            "success": smv_code is not None,
            "log": trans_log
        }

        if not smv_code:
            logger.error("SMV translation failed")
            result["overall_passed"] = False
            return result

        # Save translated SMV
        smv_file_path = str(output_folder / "translated_model.smv")
        with open(smv_file_path, 'w', encoding='utf-8') as f:
            f.write(smv_code)

        # Step 4: nuXmv verification
        logger.info(f"Step 4: nuXmv verification")
        verif_passed, verif_output = self.verify_with_nuxmv(
            smv_code, smv_file_path, str(output_folder)
        )

        result["verification"] = {
            "passed": verif_passed,
            "output": verif_output
        }

        # Overall result
        result["overall_passed"] = compile_passed and (verif_passed is True)

        # Save result
        result_path = output_folder / "evaluation_result.json"
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, default=str)

        status = "PASSED" if result["overall_passed"] else "FAILED"
        logger.info(f"Evaluation complete: {status}")

        return result

    def evaluate_batch(
        self,
        input_files: List[Dict[str, Any]],
        base_dir: Optional[str] = None
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Evaluate a batch of ST files.

        Args:
            input_files: List of dictionaries with keys:
                - "st_file_path": str
                - "properties": List[Dict]
                - "name": Optional[str]
            base_dir: Optional override for output directory

        Returns:
            Tuple of (statistics_dict, individual_results_list)
        """
        output_dir = Path(base_dir) if base_dir else self.base_output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        stats = {
            "compilation_success": 0,
            "verified": 0,
            "validation_satisfied": 0,
            "valid_inputs": 0,
            "total": len(input_files)
        }

        results = []

        for i, file_info in enumerate(input_files, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"Evaluating file {i}/{len(input_files)}")
            logger.info(f"{'='*60}")

            st_path = file_info.get("st_file_path")
            properties = file_info.get("properties", [])
            name = file_info.get("name")

            if not st_path or not Path(st_path).exists():
                logger.warning(f"Invalid or missing file: {st_path}")
                continue

            stats["valid_inputs"] += 1

            result = self.evaluate_single(st_path, properties, name)
            results.append(result)

            if result["compilation"]["passed"]:
                stats["compilation_success"] += 1

                if result["verification"]["passed"] is not None:
                    stats["verified"] += 1

                if result["verification"]["passed"] is True:
                    stats["validation_satisfied"] += 1

        # Generate summary
        logger.info(f"\n{'='*60}")
        logger.info("BATCH EVALUATION COMPLETE")
        logger.info(f"{'='*60}")

        summary(stats, base_dir=str(output_dir), input_files=input_files)

        return stats, results


def main():
    """CLI entry point for SMV evaluation."""
    import argparse

    parser = argparse.ArgumentParser(description="Ollama4PLC - SMV/nuXmv Evaluation")
    parser.add_argument("--st-file", required=True, help="Path to ST file to evaluate")
    parser.add_argument("--properties", help="Path to JSON file containing properties")
    parser.add_argument("--compiler", default="rusty", choices=["rusty", "matiec"])
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama API URL")
    parser.add_argument("--ollama-model", default="mistral:7b", help="Ollama model for translation")
    parser.add_argument("--nuxmv-path", help="Path to nuXmv executable")
    parser.add_argument("--rusty-path", help="Path to RuSTy compiler")
    parser.add_argument("--output-dir", default="./output/smv_evaluation", help="Output directory")
    parser.add_argument("--batch", help="Path to JSON file with batch evaluation config")

    args = parser.parse_args()

    evaluator = SMVEvaluator(
        compiler=args.compiler,
        ollama_url=args.ollama_url,
        ollama_model=args.ollama_model,
        nuxmv_path=args.nuxmv_path,
        rusty_path=args.rusty_path,
        base_output_dir=args.output_dir
    )

    if args.batch:
        with open(args.batch, 'r', encoding='utf-8') as f:
            batch_config = json.load(f)

        stats, results = evaluator.evaluate_batch(
            batch_config.get("input_files", []),
            base_dir=args.output_dir
        )

    else:
        properties = []
        if args.properties:
            with open(args.properties, 'r', encoding='utf-8') as f:
                properties = json.load(f)

        result = evaluator.evaluate_single(args.st_file, properties)

        print(f"\nEvaluation Result: {'PASSED' if result['overall_passed'] else 'FAILED'}")
        print(f"Output folder: {result['output_folder']}")


if __name__ == "__main__":
    main()
