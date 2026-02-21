# Frontend Code Review Guidelines

## API Handling

- Store API responses in global state (e.g., Redux) only if needed across multiple components.
- Use component-local state (`useState`/`useEffect`) for view-specific or session-specific data.
- Avoid flag-based conditional API logic inside components — extract it to helper functions or hooks.
- Optimize for performance: debounce search inputs, paginate large datasets, cache static responses.

## State Management

- Use global state slices for shared state only.
- Avoid duplicating state between global state and component-local state.
- Encapsulate side effects and data-fetching in reusable custom hooks.

## Component Architecture

- Follow a clean separation of concerns:
  - `components/` — Dumb, reusable UI elements
  - `containers/` — Smart components with data-fetching
  - `hooks/` — Reusable logic for side effects
  - `utils/`, `constants/` — Low-level modules and config

## Do's

- Use constants or enums for repeated value-label pairs (e.g., statuses, categories).
- Keep components small and composable.
- Write tests for custom hooks, logic, and critical UI behaviors.

## Don'ts

- Don't use wildcard imports (e.g., `import * as lib`) — prefer named imports.
- Don't hardcode magic values — define them as constants or enums.
- Don't embed conditional API logic directly in components.
- Don't bloat container components — move logic to hooks or services.

## Value-to-Label Mapping

Use a structured class with static getters for value-label constants:

```js
// Good
class DocumentType {
  static get PASSPORT() {
    return { code: "passport", title: "Passport" };
  }
  static get ALL() {
    return [DocumentType.PASSPORT];
  }
}

// Bad
const DocumentType = {
  PASSPORT: { code: "passport", title: "Passport" },
};
```

Using a class prevents unintentional mutation and supports lazy initialization.

## Syntax & Language Notes

- Use named imports: `import { Button } from "antd";`
- Avoid wildcard imports: `import * as antd from "antd";`
- Do not suggest removing fallback logic (e.g., `|| []`) unless the value is guaranteed non-null.
  Note: JavaScript's `Map.get()` does not support default values like Python's `dict.get()`.
