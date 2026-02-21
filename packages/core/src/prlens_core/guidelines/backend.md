# Backend Code Review Guidelines

## REST & Architecture

- Use proper HTTP verbs (e.g., `POST /users` not `POST /users/create`).
- Keep business logic in service layers — views/controllers should only orchestrate.
- Avoid putting business logic in model `save()` methods or view handlers.
- Avoid boolean flags that alter method behavior; create explicit, separate methods instead.

## Code Structure & Reusability

- Place shared logic in a shared library if it is reused across multiple services.
- Wrap external integrations (e.g., Slack, email, storage) in clean service layers that do not depend on internal app logic.
- Avoid adding executable code in `__init__.py` files — use them only for imports and package exposure.

## Django-Specific Practices (if applicable)

- Use `select_related` / `prefetch_related` to avoid N+1 queries.
- Validate inputs in serializers, not in views or services.
- Use custom domain exceptions instead of generic ones for consistent error handling.
- Organize code modularly by domain (e.g., `users`, `payments`, `notifications`).

## Python Best Practices

- Use type hints in all function and method signatures.
- Avoid wildcard imports (`from module import *`).
- Use `logging` with appropriate levels instead of `print()`.
- Replace magic strings and numbers with named constants or enums.
- Prefer `pathlib.Path` over string-based file paths.
- Use context managers (`with` statements) for files and resources.

## Testing & Maintainability

- Write unit tests for all new service logic.
- Keep tests fast and deterministic; mock all external dependencies.
- Use environment variables for secrets and configuration — never hardcode them.
- Add docstrings and API documentation for new public endpoints and logic.
