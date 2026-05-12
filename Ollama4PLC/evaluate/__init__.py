"""
Ollama4PLC - Evaluation Package

Provides automated evaluation capabilities for generated PLC code:
- plcverif_evaluation: Direct property verification using PLCverif
- smv_evaluation: SMV translation + nuXmv model checking via local LLM
- pretty_summary: Formatted statistics output

Usage:
    from evaluate import PLCverifEvaluator, SMVEvaluator

    # PLCverif approach
    plc_eval = PLCverifEvaluator()
    result = plc_eval.evaluate_single("program.st", properties)

    # SMV/nuXmv approach
    smv_eval = SMVEvaluator()
    result = smv_eval.evaluate_single("program.st", properties)
"""

from .plcverif_evaluation import PLCverifEvaluator
from .smv_evaluation import SMVEvaluator
from .pretty_summary import summary, quick_summary

__all__ = [
    "PLCverifEvaluator",
    "SMVEvaluator", 
    "summary",
    "quick_summary"
]
