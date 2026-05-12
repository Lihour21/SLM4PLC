"""
Ollama4PLC - Evaluation Summary Module

Provides formatted output of compilation and verification statistics.
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional, List


def summary(
    compilation_validation_statistics: Dict[str, Any],
    base_dir: Optional[str] = None,
    input_files: Optional[List[Dict]] = None,
    evaluation_name: str = "Ollama4PLC_Evaluation"
) -> str:
    """
    Print and write the compilation validation statistics to a log file.

    Args:
        compilation_validation_statistics: Dictionary containing compilation and verification statistics.
        base_dir: Directory where log files will be written.
        input_files: Optional list of input file dictionaries for detailed logging.
        evaluation_name: Name identifier for this evaluation run.

    Returns:
        Formatted summary string.
    """
    # Extract values with safe defaults
    total = compilation_validation_statistics.get('total', 0)
    compilation_success = compilation_validation_statistics.get('compilation_success', 0)
    verified = compilation_validation_statistics.get('verified', 0)
    validation_satisfied = compilation_validation_statistics.get('validation_satisfied', 0)
    valid_inputs = compilation_validation_statistics.get('valid_inputs', 0)

    # Avoid division by zero
    total_safe = total if total > 0 else 1
    compilation_safe = compilation_success if compilation_success > 0 else 1

    # Format the output string with enhanced metrics
    output_str = f"""
{'='*60}
{evaluation_name} - Evaluation Summary
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'='*60}

OVERALL STATISTICS:
  Total files evaluated:     {total}
  Valid input files:         {valid_inputs}/{total} ({valid_inputs / total_safe:.1%})

COMPILATION (Syntax Check):
  Passed:                    {compilation_success}/{total} ({compilation_success / total_safe:.1%})
  Failed:                    {total - compilation_success}/{total} ({(total - compilation_success) / total_safe:.1%})

VERIFICATION (Semantic Check):
  Verified:                  {verified}/{compilation_success} ({verified / compilation_safe:.1%})
  Not Verified/Timeout:      {compilation_success - verified}/{compilation_success} ({(compilation_success - verified) / compilation_safe:.1%})

VALIDATION SATISFIED:
  Fully Satisfied:           {validation_satisfied}/{compilation_success} ({validation_satisfied / compilation_safe:.1%})
  Partially Satisfied:       {verified - validation_satisfied}/{compilation_success} ({(verified - validation_satisfied) / compilation_safe:.1%})

{'='*60}
SUMMARY:
  Success Rate:              {validation_satisfied}/{total} ({validation_satisfied / total_safe:.1%})
{'='*60}
"""

    # Print to console
    print(output_str)

    # Write to log file if base_dir provided
    if base_dir:
        os.makedirs(base_dir, exist_ok=True)

        # Main summary file
        summary_file_path = os.path.join(base_dir, "evaluation_summary.txt")
        with open(summary_file_path, "w", encoding="utf-8") as f:
            f.write(output_str)

        # JSON statistics for programmatic access
        json_file_path = os.path.join(base_dir, "evaluation_statistics.json")
        with open(json_file_path, "w", encoding="utf-8") as f:
            json.dump({
                "evaluation_name": evaluation_name,
                "timestamp": datetime.now().isoformat(),
                **compilation_validation_statistics,
                "rates": {
                    "compilation_rate": compilation_success / total_safe,
                    "verification_rate": verified / compilation_safe,
                    "satisfaction_rate": validation_satisfied / compilation_safe,
                    "overall_success_rate": validation_satisfied / total_safe
                }
            }, f, indent=2)

        # Detailed input files log
        if input_files is not None:
            log_file_path = os.path.join(base_dir, "input_files.json")
            with open(log_file_path, "w", encoding="utf-8") as f:
                json.dump(input_files, f, indent=2, default=str)

        print(f"\n📁 Logs written to: {base_dir}")
        print(f"   - evaluation_summary.txt")
        print(f"   - evaluation_statistics.json")
        if input_files:
            print(f"   - input_files.json")

    return output_str


def quick_summary(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate summary statistics from a list of individual evaluation results.

    Args:
        results: List of result dictionaries, each containing at minimum:
            - 'st_file_path': str
            - 'compilation_passed': bool
            - 'verification_passed': Optional[bool]
            - 'properties_satisfied': Optional[int]
            - 'properties_total': Optional[int]

    Returns:
        Statistics dictionary compatible with summary().
    """
    total = len(results)
    compilation_success = sum(1 for r in results if r.get('compilation_passed', False))
    verified = sum(1 for r in results if r.get('verification_passed') is not None)
    validation_satisfied = sum(1 for r in results if r.get('verification_passed', False))
    valid_inputs = sum(1 for r in results if r.get('st_file_path'))

    return {
        "compilation_success": compilation_success,
        "verified": verified,
        "validation_satisfied": validation_satisfied,
        "valid_inputs": valid_inputs,
        "total": total
    }
