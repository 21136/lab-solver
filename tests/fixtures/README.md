# Golden fixtures

Three sample lab report `.docx` files for Phase 1.2 regression:

| File | Role |
|------|------|
| `programming_lab.docx` | Programming-focused report |
| `theory_lab.docx` | Theory / analysis report |
| `combined_lab.docx` | Mixed requirements + code |

Regenerate with:

```bash
python tests/generate_fixtures.py
```

Run regression:

```bash
python tests/run_golden_regression.py

# 或统一入口（需 pip install -r requirements-dev.txt）：
python -m pytest
scripts\run-tests.bat
```
