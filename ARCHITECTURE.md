# Architecture

This action is a small Python runtime behind a composite action.

It targets both Gitea and GitHub runtimes through one centralized host-resolution path.

## Entry points

- `action.yml` is the public entry point used by workflows.
- `scripts/install-python.sh` ensures Python is available on the runner.
- `python -m auto_changelog_release_action` starts `src/auto_changelog_release_action/__main__.py`.

## Runtime flow

1. `__main__.py` loads the environment and forwards execution to `action_runtime.py`.
2. `action_runtime.py` resolves the runtime host, normalizes server and API URLs, writes action outputs, and coordinates the full run.
3. `git_setup.py` configures the git author for generated commits.
4. `version_bump_flow.py` checks commit messages and may bump the version file.
5. If no bump happened, `version_change_flow.py` compares the version value across commits.
6. `runtime_host.py` is the single source of truth for host detection and URL normalization.
7. `cliff_config.py` creates `cliff.toml` from the host-specific bundled template when needed.
8. `git_cliff_version.py` reads the Renovate-managed `versions.gitcliff.env` from the action's own checkout; `install_git_cliff.py` installs that pinned version.
9. `release_flow.py` runs when the version changed and handles release changelog generation, changelog commit, tag creation, and API release publication.
10. `unreleased_changelog.py` runs when no release is needed and updates the unreleased changelog instead.

## Supporting modules

- `versioning.py` contains shared version parsing, bumping, matching, and replacement logic.
- `changelog_context.py` enriches `git-cliff` JSON context with merge metadata and prerelease carry-over.
- `process_utils.py` provides the shared subprocess and git wrappers.
- `repository.py` splits repository slugs into owner and repo names.
- `actions_io.py` writes values to `GITHUB_OUTPUT` and `GITHUB_ENV`.

## Host model

- Host-specific branching happens once in `runtime_host.py`.
- Downstream modules consume normalized `host`, `server_url`, `api_url`, `repository`, and `ref` values.
- For Gitea, `server_url` is derived from `GITEA_API_URL` when no explicit server URL is provided.
- Changelog rendering stays host-aware through template selection, not through scattered URL conditionals.
- Release publication always uses the resolved API URL plus the explicit `token` action input.
- Repository operations continue to use the runner's configured git credentials.

## Workflow scope

- Repository-contained workflow examples remain under `.gitea/workflows/`.
- The runtime is host-aware, but this repository does not ship `.github/workflows/` examples.

## Design intent

The workflow contract stays in `action.yml`, while the Python modules keep the execution logic testable, reusable, host-aware, and independent from shell wrappers.