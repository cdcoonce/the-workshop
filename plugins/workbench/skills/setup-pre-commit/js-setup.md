# JS/TS Pre-Commit Setup

## Available Checks

Present these options to the user via AskUserQuestion. Let them select which checks to enable:

- **prettier** — code formatting
- **eslint** — linting (only offer this if an ESLint config already exists in the project: `eslint.config.js`, `eslint.config.mjs`, `eslint.config.cjs`, `.eslintrc.*`)
- **typecheck** — TypeScript type checking (only offer if a `typecheck` script exists in `package.json`)
- **test** — test suite (only offer if a `test` script exists in `package.json`)

## Steps

### 1. Detect package manager

Check for lock files to determine the package manager:

| Lock file           | Package manager |
| ------------------- | --------------- |
| `package-lock.json` | npm             |
| `pnpm-lock.yaml`    | pnpm            |
| `yarn.lock`         | yarn            |
| `bun.lockb`         | bun             |

Default to npm if no lock file is found.

### 2. Install dependencies

Install as devDependencies using the detected package manager:

**Always install**: `husky`

**Conditionally install**:

- `lint-staged` — if prettier or eslint selected
- `prettier` — if prettier selected

(ESLint should already be installed if the user has an ESLint config.)

Example (npm):

```bash
npm install --save-dev husky lint-staged prettier
```

Adapt the command to the detected package manager (`pnpm add -D`, `yarn add -D`, `bun add -D`).

### 3. Initialize Husky

```bash
npx husky init
```

This creates the `.husky/` directory and adds `"prepare": "husky"` to `package.json`.

### 4. Create `.husky/pre-commit`

Write this file (no shebang needed for Husky v9+). Include only the commands for selected checks:

```
npx lint-staged
npm run typecheck
npm run test
```

**Adapt**:

- Replace `npm` with the detected package manager (`pnpm`, `yarn`, `bun`)
- Only include `npx lint-staged` if prettier or eslint were selected
- Only include the `typecheck` line if the user selected typecheck AND the script exists in `package.json`
- Only include the `test` line if the user selected test AND the script exists in `package.json`

### 5. Create `.lintstagedrc`

Only create if prettier or eslint were selected. Configure based on selections:

**Prettier only**:

```json
{
  "*": "prettier --ignore-unknown --write"
}
```

**ESLint only**:

```json
{
  "*.{js,ts,jsx,tsx}": "eslint --fix"
}
```

**Both Prettier and ESLint**:

```json
{
  "*": "prettier --ignore-unknown --write",
  "*.{js,ts,jsx,tsx}": "eslint --fix"
}
```

### 6. Create `.prettierrc` (if needed)

Only create if prettier was selected AND no Prettier config exists in the project (check for `.prettierrc`, `.prettierrc.json`, `.prettierrc.js`, `prettier.config.js`, or a `prettier` key in `package.json`).

Use these defaults:

```json
{
  "useTabs": false,
  "tabWidth": 2,
  "printWidth": 80,
  "singleQuote": false,
  "trailingComma": "es5",
  "semi": true,
  "arrowParens": "always"
}
```

### 7. Verify

Run each command from the pre-commit hook sequentially to confirm everything works:

1. If lint-staged is configured: `npx lint-staged`
2. If typecheck is configured: `npm run typecheck` (adapt to package manager)
3. If test is configured: `npm run test` (adapt to package manager)

### 8. Commit

Stage and commit with message: `Add pre-commit hooks (husky + lint-staged)`

## Notes

- Husky v9+ doesn't need shebangs in hook files
- `prettier --ignore-unknown` skips files Prettier can't parse (images, binaries, etc.)
- The pre-commit runs lint-staged first (fast, staged-only), then full typecheck and tests
