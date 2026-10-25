# Auto Changelog & Release — Node.js bootstrap

Minimal TypeScript/Node.js starting point for a possible future rewrite of
`actions/auto-changelog-release-action`. This is **not a runnable GitHub/Gitea
Action yet**: no `action.yml`, release logic, or deployment workflow is included.

## Requirements

- **Node.js 24 LTS** (see `.node-version`)
- npm and Git

## Getting started

```sh
npm install
npm run check
npm run dev
npm start
```

- `dev` executes the TypeScript entry point directly through `tsx`.
- `typecheck` uses TypeScript's strict type checker without emitting files.
- `test` runs the built-in `node:test` API via `tsx`.
- `build` creates a self-contained Node.js ESM bundle at `dist/main.mjs`.
- `start` runs the generated bundle.
- `check` runs type checking, tests, and the build.

`npm install` generates `package-lock.json`; commit it once dependencies are
resolved if reproducible CI installs are desired. No lockfile is shipped in this
bootstrap archive.

## Included dependencies

| Package | Intended purpose |
| --- | --- |
| `@actions/core` | Inputs, outputs, logs and action failure reporting |
| `@actions/github` | GitHub Actions context and GitHub API client |
| `@conventional-changelog/git-client` | Git history, tags and Git commands |
| `conventional-commits-parser` | Peer dependency for parsed conventional commits |
| `conventional-commits-filter` | Peer dependency for revert filtering |

`@actions/github` is **not** a generic, fully Gitea-compatible API client.
Platform-specific release publishing should be designed and tested separately.
The bootstrap only accesses its event context; it does not perform API calls.

## Contents

```text
.
├── .gitignore
├── .node-version
├── package.json
├── tsconfig.json
├── scripts/
│   └── build.mjs
└── src/
    ├── main.ts
    ├── environment.ts
    ├── __tests__/
    │   └── environment.test.ts
    └── git/
        └── mod.ts
```

No repository files are changed and no tags/releases are created by the
bootstrap entry point. `ConventionalGitClient` is initialized but no Git
operation is executed.

## Later integration

When wiring up `action.yml`, decide whether to expose the bundle through a
native `runs.using: node24` action or retain a composite action that explicitly
starts Node. GitHub expects Node 24 for native JavaScript actions; test Gitea
runner support for the selected mechanism independently.

`dist/` is intentionally **not** ignored: action consumers should not need
`npm install` at runtime, so the compiled bundle must be committed when the
Action metadata points to it. Until then, this repository is a normal Node.js
project only.

The existing `action.yml` input/output contract, version semantics, changelog
formatting, scheduled releases, and publishing are intentionally out of scope.
