# Learnings

## Task 2: VBS ReadAll → ReadLine

- **Date:** 2026-05-26
- **File changed:** ackend/autostart_service.py
- **Lines changed:** 288, 320 — both ile.ReadAll → ile.ReadLine
- **Rationale:** PID file only contains one line (the PID). ReadAll reads the entire file unnecessarily; ReadLine is semantically correct and slightly more efficient.
- **Verification:** grep -c "ReadAll" → 0, grep -c "ReadLine" → 2, ruff check passes.
