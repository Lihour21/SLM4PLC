"""
Ollama4PLC - PLCverif Evaluation Module

Evaluates generated ST files using:
1. RuSTy compiler for syntax validation
2. PLCverif for formal property verification

This module integrates with the Ollama4PLC pipeline to provide
automated evaluation of generated PLC code against specified properties.
"""

import os
import sys
import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union

# Add project root to path
parent_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(parent_dir))

from evaluate.pretty_summary import summary, quick_summary

logger = logging.getLogger(__name__)

# Configuration defaults
DEFAULT_COMPILER = "rusty"
PLCVERIF_VERIFIED_THRESHOLD = 0.80
PLCVERIF_PASSED_THRESHOLD = 0.80


class PLCverifEvaluator:
    """
    Evaluator for PLC code using RuSTy compiler and PLCverif tool.

    Provides automated syntax checking and formal property verification
    for IEC 61131-3 Structured Text programs.
    """

    def __init__(
        self,
        compiler: str = DEFAULT_COMPILER,
        rusty_path: Optional[str] = None,
        plcverif_path: Optional[str] = None,
        verified_threshold: float = PLCVERIF_VERIFIED_THRESHOLD,
        passed_threshold: float = PLCVERIF_PASSED_THRESHOLD,
        base_output_dir: str = "./output/evaluation"
    ):
        """
        Initialize the PLCverif evaluator.

        Args:
            compiler: Compiler to use ('rusty' or 'matiec')
            rusty_path: Path to RuSTy compiler executable
            plcverif_path: Path to PLCverif CLI executable
            verified_threshold: Minimum ratio of verified properties (0-1)
            passed_threshold: Minimum ratio of passed properties (0-1)
            base_output_dir: Base directory for evaluation outputs
        """
        self.compiler = compiler
        self.verified_threshold = verified_threshold
        self.passed_threshold = passed_threshold
        self.base_output_dir = Path(base_output_dir).resolve()

        # Resolve tool paths
        self.rusty_path = self._resolve_path(
            rusty_path,
            ["~/rusty/target/release/plc", "./tools/rusty/plc", "rusty"]
        )
        self.plcverif_path = self._resolve_path(
            plcverif_path,
            ["~/plcverif/plcverif-cli", "./tools/plcverif-cli", "plcverif-cli"]
        )

        # Create output directory
        self.base_output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"PLCverifEvaluator initialized:")
        logger.info(f"  Compiler: {self.compiler} ({self.rusty_path})")
        logger.info(f"  PLCverif: {self.plcverif_path}")
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

            # Check PATH
            found = shutil.which(Path(fallback).name)
            if found:
                return Path(found)

        return None

    def check_syntax_rusty(self, st_file_path: str) -> Tuple[bool, str]:
        """
        Check ST file syntax using RuSTy compiler.

        Args:
            st_file_path: Path to .st file

        Returns:
            Tuple of (passed: bool, output: str)
        """
        if not self.rusty_path or not self.rusty_path.exists():
            logger.warning("RuSTy compiler not found, skipping syntax check")
            return True, "RuSTy not available - skipped"

        st_file = Path(st_file_path)
        if not st_file.exists():
            return False, f"File not found: {st_file_path}"

        try:
            cmd = [str(self.rusty_path), "--check", str(st_file)]
            logger.info(f"Running syntax check: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            output = result.stdout + "\n" + result.stderr

            # Check for errors
            if result.returncode != 0 or "error" in output.lower():
                logger.warning(f"Syntax check failed for {st_file_path}")
                return False, output

            logger.info(f"Syntax check passed for {st_file_path}")
            return True, output

        except subprocess.TimeoutExpired:
            logger.error("Syntax check timed out")
            return False, "Timeout"
        except Exception as e:
            logger.error(f"Syntax check error: {e}")
            return False, str(e)

    def verify_with_plcverif(
        self,
        st_file_path: str,
        properties: List[Dict],
        output_folder: str
    ) -> Tuple[Optional[bool], Dict[str, int], str]:
        """
        Verify ST file properties using PLCverif.

        Args:
            st_file_path: Path to .st file
            properties: List of property dictionaries
            output_folder: Folder for evaluation logs

        Returns:
            Tuple of (overall_passed: Optional[bool], stats: dict, log_output: str)
        """
        if not self.plcverif_path or not self.plcverif_path.exists():
            logger.warning("PLCverif not found, skipping verification")
            return None, {}, "PLCverif not available"

        os.makedirs(output_folder, exist_ok=True)

        # Prepare ST file with properties
        try:
            with open(st_file_path, 'r', encoding='utf-8') as f:
                st_content = f.read()
        except Exception as e:
            logger.error(f"Failed to read ST file: {e}")
            return None, {}, str(e)

        # Convert properties to PLCverif-compatible format
        properties_str = self._format_properties(properties)
        st_with_props = st_content + "\n\n(* PLCverif Properties *)\n" + properties_str

        # Write temporary file
        temp_st_path = os.path.join(output_folder, "verification_temp.st")
        with open(temp_st_path, 'w', encoding='utf-8') as f:
            f.write(st_with_props)

        # Run PLCverif
        try:
            cmd = [str(self.plcverif_path), temp_st_path]
            logger.info(f"Running PLCverif: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            output = result.stdout + "\n" + result.stderr

            # Save log
            log_path = os.path.join(output_folder, "plcverif_log.txt")
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(output)

            # Parse results
            stats = self._parse_plcverif_output(output, properties)

            # Determine overall result
            total = stats["total"]
            if total == 0:
                overall = None
            else:
                passed_ratio = stats["success"] / total
                verified_ratio = (stats["success"] + stats["failure"]) / total

                if passed_ratio >= self.passed_threshold:
                    overall = True
                elif verified_ratio < self.verified_threshold:
                    overall = False
                else:
                    overall = None  # Partial - needs review

            return overall, stats, output

        except subprocess.TimeoutExpired:
            logger.error("PLCverif timed out")
            return None, {}, "Timeout"
        except Exception as e:
            logger.error(f"PLCverif error: {e}")
            return None, {}, str(e)

    def _format_properties(self, properties: List[Dict]) -> str:
        """Format properties dictionary into ST comment format."""
        lines = []
        for i, prop in enumerate(properties, 1):
            prop_desc = prop.get("property_description", f"Property {i}")
            lines.append(f"(* Property {i}: {prop_desc} *)")

            prop_data = prop.get("property", {})
            if prop_data.get("job_req") == "assertion":
                lines.append("(*! ASSERT *)")
            elif prop_data.get("job_req") == "pattern":
                pattern_id = prop_data.get("pattern_id", "")
                params = prop_data.get("pattern_params", {})
                param_str = ", ".join(f"{k}={v}" for k, v in params.items())
                lines.append(f"(*! PATTERN {pattern_id} {param_str} *)")

        return "\n".join(lines)

    def _parse_plcverif_output(self, output: str, properties: List[Dict]) -> Dict[str, int]:
        """Parse PLCverif output to extract statistics."""
        stats = {
            "success": 0,
            "failure": 0,
            "not_verified": 0,
            "total": len(properties)
        }

        output_lower = output.lower()

        for prop in properties:
            prop_desc = prop.get("property_description", "")
            # Simple heuristic parsing - can be enhanced based on actual PLCverif output format
            if "satisfied" in output_lower or "verified" in output_lower:
                stats["success"] += 1
            elif "violated" in output_lower or "failed" in output_lower:
                stats["failure"] += 1
            else:
                stats["not_verified"] += 1

        return stats

    def evaluate_single(
        self,
        st_file_path: str,
        properties: List[Dict],
        evaluation_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate a single ST file comprehensively.

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
            "verification": {},
            "overall_passed": False
        }

        # Step 1: Syntax compilation
        logger.info(f"Step 1: Syntax check for {name}")
        compile_passed, compile_output = self.check_syntax_rusty(st_file_path)

        result["compilation"] = {
            "passed": compile_passed,
            "output": compile_output,
            "compiler": self.compiler
        }

        if not compile_passed:
            logger.warning(f"Compilation failed for {name}, skipping verification")
            result["overall_passed"] = False
            return result

        # Step 2: Property verification
        logger.info(f"Step 2: Property verification for {name}")
        verif_passed, verif_stats, verif_output = self.verify_with_plcverif(
            st_file_path, properties, str(output_folder)
        )

        result["verification"] = {
            "passed": verif_passed,
            "statistics": verif_stats,
            "output": verif_output
        }

        # Overall result
        result["overall_passed"] = compile_passed and (verif_passed is True)

        # Save result
        result_path = output_folder / "evaluation_result.json"
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, default=str)

        logger.info(f"Evaluation complete for {name}: {'PASSED' if result['overall_passed'] else 'FAILED'}")
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

        # Initialize statistics
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

            # Evaluate
            result = self.evaluate_single(
                st_path,
                properties,
                evaluation_name=name
            )
            results.append(result)

            # Update statistics
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
    """CLI entry point for PLCverif evaluation."""
    import argparse

    parser = argparse.ArgumentParser(description="Ollama4PLC - PLCverif Evaluation")
    parser.add_argument("--st-file", required=True, help="Path to ST file to evaluate")
    parser.add_argument("--properties", help="Path to JSON file containing properties")
    parser.add_argument("--compiler", default="rusty", choices=["rusty", "matiec"])
    parser.add_argument("--rusty-path", help="Path to RuSTy compiler")
    parser.add_argument("--plcverif-path", help="Path to PLCverif CLI")
    parser.add_argument("--output-dir", default="./output/evaluation", help="Output directory")
    parser.add_argument("--batch", help="Path to JSON file with batch evaluation config")

    args = parser.parse_args()

    # Initialize evaluator
    evaluator = PLCverifEvaluator(
        compiler=args.compiler,
        rusty_path=args.rusty_path,
        plcverif_path=args.plcverif_path,
        base_output_dir=args.output_dir
    )

    if args.batch:
        # Batch evaluation
        with open(args.batch, 'r', encoding='utf-8') as f:
            batch_config = json.load(f)

        stats, results = evaluator.evaluate_batch(
            batch_config.get("input_files", []),
            base_dir=args.output_dir
        )

    else:
        # Single file evaluation
        properties = []
        if args.properties:
            with open(args.properties, 'r', encoding='utf-8') as f:
                properties = json.load(f)

        result = evaluator.evaluate_single(args.st_file, properties)

        print(f"\nEvaluation Result: {'PASSED' if result['overall_passed'] else 'FAILED'}")
        print(f"Output folder: {result['output_folder']}")


if __name__ == "__main__":
    main()
