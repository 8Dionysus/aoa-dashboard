# Validation

This is the on-demand verification route for `aoa-dashboard`. Start with the
smallest command that covers the changed surface; run the full route before
landing repository-wide changes.

## Full repository route

```bash
python3 scripts/validate_organ_contract.py
python3 scripts/validate_default_binding.py
python3 scripts/release_check.py
python3 -m pytest -q
for contract in contracts/*.json; do python3 -m json.tool "$contract" >/dev/null; done
git diff --check
```

The `Repo Validation` GitHub workflow owns the CI projection of this route.
Pytest runs both the unittest classes and the pytest-only functions; a second
unittest discovery run would repeat the same class-based checks.
