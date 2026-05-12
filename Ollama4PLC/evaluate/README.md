# Ollama4PLC Evaluation Modules

## Overview

The `evaluate/` package provides two complementary approaches for validating
generated IEC 61131-3 Structured Text (ST) code:

1. **PLCverif Evaluation** (`plcverif_evaluation.py`) — Direct formal verification
2. **SMV Evaluation** (`smv_evaluation.py`) — LLM-assisted translation + model checking

## Quick Start

### Single File Evaluation

```bash
# Using PLCverif
python -m evaluate.plcverif_evaluation \
  --st-file ./output/program.st \
  --properties ./properties.json \
  --output-dir ./output/evaluation

# Using SMV/nuXmv
python -m evaluate.smv_evaluation \
  --st-file ./output/program.st \
  --properties ./properties.json \
  --ollama-model mistral:7b \
  --output-dir ./output/smv_evaluation
```

### Batch Evaluation

```bash
# Create batch config (see batch_example.json)
python -m evaluate.smv_evaluation \
  --batch ./evaluate/batch_example.json \
  --output-dir ./output/batch_eval
```

### Programmatic Usage

```python
from evaluate import PLCverifEvaluator, SMVEvaluator

# PLCverif approach (direct)
plc_eval = PLCverifEvaluator(
    compiler="rusty",
    rusty_path="~/rusty/target/release/plc",
    plcverif_path="~/plcverif/plcverif-cli"
)

result = plc_eval.evaluate_single(
    st_file_path="./output/program.st",
    properties=[
        {
            "property_description": "Safety property",
            "property": {
                "job_req": "pattern",
                "pattern_id": "pattern-invariant",
                "pattern_params": {"1": "Motor_Speed <= 1000"}
            }
        }
    ]
)

print(f"Passed: {result['overall_passed']}")
print(f"Output: {result['output_folder']}")

# SMV approach (LLM-assisted)
smv_eval = SMVEvaluator(
    ollama_url="http://localhost:11434",
    ollama_model="mistral:7b",
    nuxmv_path="/usr/local/bin/nuXmv"
)

result = smv_eval.evaluate_single(
    st_file_path="./output/program.st",
    properties=[...]
)
```

## Evaluation Approaches Comparison

| Feature | PLCverif | SMV/nuXmv |
|---------|----------|-----------|
| **Method** | Direct ST parsing | ST→SMV translation |
| **LLM Usage** | None | ST-to-SMV translation |
| **Accuracy** | High (direct) | Medium (translation gap) |
| **Speed** | Fast | Slower (LLM + model check) |
| **Properties** | PLCverif JSON patterns | LTL/CTL formulas |
| **Best For** | Production validation | Research/experimentation |

## Property Format

### PLCverif Properties (JSON)

```json
[
  {
    "property_description": "Description of what to verify",
    "property": {
      "job_req": "pattern",
      "pattern_id": "pattern-implication",
      "pattern_params": {
        "1": "condition_expression",
        "2": "consequence_expression"
      },
      "pattern_description": "Human-readable description"
    }
  }
]
```

### SMV Properties (Auto-generated)

The SMV evaluator automatically converts JSON properties to LTLSPEC:
- `pattern-implication` → `LTLSPEC G (p -> q)`
- `pattern-invariant` → `LTLSPEC G (p)`

## Output Structure

```
output/
└── evaluation/
    └── {name}_{timestamp}/
        ├── evaluation_result.json    # Full result data
        ├── plcverif_log.txt        # PLCverif output (if applicable)
        ├── nuxmv_log.txt           # nuXmv output (if applicable)
        ├── translated_model.smv    # Generated SMV model
        └── verification_temp.st    # ST with embedded properties
```

## Configuration

Tools paths are resolved automatically via:
1. Explicit path arguments
2. Common installation locations
3. System PATH

Override in code:
```python
evaluator = PLCverifEvaluator(
    rusty_path="/custom/path/to/rusty",
    plcverif_path="/custom/path/to/plcverif"
)
```

## Integration with Main Pipeline

The evaluation modules can be called from the main Ollama4PLC pipeline
after code generation:

```python
from app import ollama_engine
from evaluate import SMVEvaluator

# Generate code
result = ollama_engine.process_requirements(requirements)
st_code = result["steps"]["generate"]["output"]

# Save to file and evaluate
with open("output/program.st", "w") as f:
    f.write(st_code)

evaluator = SMVEvaluator()
eval_result = evaluator.evaluate_single("output/program.st", properties)
```
