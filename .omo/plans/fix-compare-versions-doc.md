# Fix: _compare_versions docstring inaccuracy

## TL;DR

> **Quick Summary**: Fix the `_compare_versions` docstring which claims "相等返回 0" but actually returns -1 when versions are equal. The runtime behavior is correct (caller uses `> 0` check), but the misleading docstring could confuse future readers.
> 
> **Deliverables**: 1 file change
> - `backend/main.py:466-478` — corrected docstring + explanatory comment
> 
> **Estimated Effort**: Quick
> **Parallel Execution**: N/A (single task)

## Context

`_compare_versions(tag, current)` compares GitHub latest version against local version. When `tag == current` (same version):
- The for-else falls through to `return 1 if len(va) > len(vb) else -1`
- Since `len(va) == len(vb)`, returns `-1` instead of `0`
- Caller checks `_compare_versions(tag, current) > 0` → `-1 > 0` → **False** → no update
- **Runtime behavior is correct**, docstring is misleading

## Work Objectives

### Concrete Deliverable
- `backend/main.py:466-478`: Fix docstring + add explanatory comment

### Definition of Done
- [ ] `backend/main.py` has correct docstring + comment
- [ ] `uv run pytest` still passes (337/337)
- [ ] `uv run ruff check backend/main.py` no new issues

## TODOs

- [x] 1. Fix `_compare_versions` docstring and add comment

  **What to do**:
  - In `backend/main.py:466-478`, update the docstring to accurately say "len(va) == len(vb) 时返回 -1（而非 0），但调用方使用 `> 0` 判断，不影响结果"
  - Add an inline comment: `# NOTE: 相等时返回 -1 而非 0，但调用方用 > 0 判断，结果不受影响`
  - Only edit the `return 1 if len(va) > len(vb) else -1` area

  **Must NOT do**:
  - Do NOT change the return value logic — behavior is correct
  - Do NOT touch any other function

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: none needed

  **Parallelization**: N/A (single task)

  **References**:
  - `backend/main.py:466-478` — the function itself
  - `backend/main.py:457` — caller: `_compare_versions(tag, current) > 0`

  **Acceptance Criteria**:
  - [ ] Docstring corrected: no longer claims "相等返回 0"
  - [ ] Inline comment added explaining why -1 is safe
  - [ ] `uv run ruff check backend/main.py` — no new issues

  **Commit**: YES, groups with nothing else
  - Message: `docs: correct _compare_versions docstring (behavior is correct, doc was misleading)`
  - Files: `backend/main.py`
  - Pre-commit: `uv run ruff check backend/main.py`

## Success Criteria

### Verification Commands
```bash
uv run ruff check backend/main.py
```

### Final Checklist
- [ ] Docstring and comment corrected
- [ ] No lint errors
- [ ] No logic changes
