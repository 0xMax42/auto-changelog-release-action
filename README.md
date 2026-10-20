# Auto Changelog & Release

This composite action updates your changelog and publishes releases from the version stored in your repository.

It is mainly intended for internal use, but the behavior is straightforward: the runtime detects whether it is running on GitHub Actions or Gitea Actions and uses the matching API and changelog links automatically.

## What it does

- reads the version from a file in your repository
- optionally bumps that version based on commit message patterns
- detects whether the version changed between commits
- generates or updates `CHANGELOG.md`
- creates and publishes a release when a new version is present

If no release is needed, the action generates the unreleased changelog section locally. By default, it does not commit or push the change.

## Usage

### GitHub

```yaml
name: Release

on:
  push:
    branches:
      - main

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: MP-Log-In/auto-changelog-release-action@v1
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          patch_patterns: |
            ^fix:
            ^chore\(deps\):
```

For normal GitHub usage, pinning to `v1` is the expected setup.

### Gitea

```yaml
name: Auto Changelog & Release

on:
  push:
    branches:
      - "main"

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Release
        uses: https://git.0xmax42.io/actions/auto-changelog-release-action@v1
        with:
          token: ${{ secrets.GITEA_TOKEN }}
          trigger_release_workflows: "true"
          version_file: pyproject.toml
          version_regex: '^version\s*=\s*"([^"]+)"'
```

#### Using with Output Variables

By utilising the outputs of the action, you can avoid using a dedicated (long-lived) user token and react to a release in a subsequent job.

```yaml
name: Auto Changelog & Release

on:
  push:
    branches:
      - "main"

jobs:
  release:
    runs-on: ubuntu-latest
    outputs:
      release_created: ${{ steps.release.outputs.release_created }}
      release_prerelease: ${{ steps.release.outputs.release_prerelease }}
      release_tag: ${{ steps.release.outputs.release_tag }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Release
        id: release
        uses: https://git.0xmax42.io/actions/auto-changelog-release-action@v1
        with:
          token: ${{ secrets.GITEA_TOKEN }}
          allow_non_main_release: "true"
          version_file: pyproject.toml
          version_regex: '^version\s*=\s*"([^"]+)"'

  build-release:
    runs-on: ubuntu-latest
    needs: release

    if: ${{ needs.release.outputs.release_created == 'true' }}

    env:
      RELEASE_TAG: ${{ needs.release.outputs.release_tag }}
      RELEASE_PRERELEASE: ${{ needs.release.outputs.release_prerelease }}

    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ needs.release.outputs.release_tag }}
          fetch-depth: 0

      # Build and publish release artifacts here, using RELEASE_TAG and RELEASE_PRERELEASE as needed
```
---

The inputs are available on Gitea and GitHub. Host-specific behavior is noted below.

The action also exposes outputs on the step that runs it via `steps.<id>.outputs.*`.

## Inputs

| Input | Required | Default | Description |
| --- | --- | --- | --- |
| `token` | no | `""` | Explicit GitHub or Gitea token used for the release API call. Changelog commits, branch pushes, and tag pushes still use the runner's configured repository credentials. A release cannot be published without it. |
| `author_name` | no | `""` | Git author name for commits created by the action. |
| `author_email` | no | `""` | Git author email for commits created by the action. |
| `allow_non_main_release` | no | `"false"` | If `true`, the action may publish releases from branches other than `main`. |
| `version_file` | no | `"VERSION"` | File that contains the project version. This is the source of truth for tags, changelog entries, and releases. |
| `version_regex` | no | `"^(.*)$"` | Regular expression used to extract the version from `version_file`. If you leave it empty, the runtime chooses a default based on the file name. |
| `github_sha_override` | no | `""` | Optional override for the commit SHA used when calculating the commit range. Mostly useful for tests or unusual workflows. |
| `major_patterns` | no | `""` | Newline-separated regular expressions that trigger a major version bump. |
| `minor_patterns` | no | `""` | Newline-separated regular expressions that trigger a minor version bump. |
| `patch_patterns` | no | `""` | Newline-separated regular expressions that trigger a patch version bump. |
| `git_cliff_offline` | no | `"true"` | If `true`, runs `git-cliff` in offline mode and skips remote metadata lookups. |
| `commit_unreleased_changelog` | no | `"false"` | If `true`, commits and pushes an updated unreleased changelog on non-release runs. Generation is unaffected. |
| `trigger_release_workflows` | no | `"false"` | On Gitea hosts supporting the trigger_workflows release API option, if `true`, adds `"trigger_workflows": true` to the release API payload. The input has no effect on GitHub. |

### Unreleased changelog commits

By default, non-release runs generate `CHANGELOG.md` locally without committing or pushing it. To restore the previous behavior, explicitly enable:

```yaml
with:
  commit_unreleased_changelog: "true"
```

**Behavior change:** Previous versions always committed and pushed a changed unreleased changelog. This is now opt-in (`false` by default). Release changelog commits and pushes are unaffected.

## Outputs

| Output | Description |
| --- | --- |
| `release_created` | `true` when this run created the remote release, otherwise `false`. |
| `release_prerelease` | `true` when the resolved version was published as a managed prerelease, otherwise `false`. |
| `release_tag` | The tag derived from the resolved version, for example `v1.2.3`. Empty when no release path was taken. |

When no release is published, the outputs are `release_created=false`, `release_prerelease=false`, and an empty `release_tag`.

## Version file and regex

The version file is the source of truth. Tags, changelog entries, and releases are derived from it.

The action does not assume that your version lives in a specific file format. It only needs:

- a file that contains the version value
- a regex that extracts that value reliably

The default setup is a plain `VERSION` file with one version string per file:

```text
1.10.0
```

That works with the default `version_regex` of `^(.*)$`.

If your version is stored somewhere else, point `version_file` to that file and set a matching regex. For example, for a Poetry project:

```yaml
with:
  version_file: pyproject.toml
  version_regex: 'version\s*=\s*"([^"]+)"'
```

If the regex does not match, the action fails instead of guessing.

### Pre-releases and version suffixes

The action distinguishes between managed pre-releases and ordinary releases that happen to carry a suffix.

- `pre`, `alpha`, and `beta` are treated as managed pre-release labels
- managed pre-releases are recognized for release metadata and special prerelease handling
- other suffixes are preserved, but they are not treated as pre-releases

Examples:

- `1.2.3-pre.4` is treated as a pre-release
- `1.2.3-alpha.2` is treated as a pre-release
- `1.2.3-beta.1` is treated as a pre-release
- `0.1.6-gitea-runner.1.0.4-dev-4-9-g2208e7e` is treated as a normal release version with a preserved suffix

When the action bumps a normal release version with a non-pre-release suffix, it bumps the semantic core and keeps the suffix. For example, `0.1.6-gitea-runner.1.0.4-dev-4-9-g2208e7e` becomes `0.1.7-gitea-runner.1.0.4-dev-4-9-g2208e7e` for a patch bump.

## Bump logic

Automatic version bumps are driven by commit messages in the current push range.

- patterns are evaluated against commit messages
- patterns are newline-separated regular expressions
- major wins over minor, and minor wins over patch
- if no pattern matches, no automatic bump is created
- if all pattern inputs are empty, bumping is effectively disabled

When a bump is triggered, the action updates `version_file`, commits the change, and continues the release flow with the new version.

If no bump is triggered, the action compares the version value across commits. A release is created only when the version actually changed.

## Changelog grouping

The bundled `git-cliff` configuration groups conventional commits into fixed changelog sections such as features, fixes, documentation, and refactors.

There is one special-purpose commit type for manually authored release notes:

- `chore(releasenotes): ...`

Commits matched by that parser are rendered into a dedicated `Release Notes` section at the top of the generated release entry. Unlike normal commit groups, their commit bodies are rendered as prose instead of bullet list items.

That makes them useful for curated notes such as migration hints, operator instructions, or rollout details that should appear exactly as written.

Example:

```text
chore(releasenotes): summarize rollout impact

This release changes the default cache layout.

Clear the old cache directory before the first restart.
```

If a `chore(releasenotes)` commit has no body, the dedicated section is omitted and the normal grouped changelog rendering remains unchanged for all other commits.

## git-cliff offline mode

By default, `git-cliff` runs in offline mode.

This avoids remote metadata lookups in CI environments with placeholder repository URLs, restricted outbound network access, or when you want deterministic changelog rendering without API requests.

```yaml
with:
  git_cliff_offline: true
```

Set `git_cliff_offline: false` if you explicitly want `git-cliff` to perform its remote metadata lookups.

The action maps this to `GIT_CLIFF_OFFLINE` for the internal `git-cliff` invocations used for unreleased and release changelog generation.

## Local development tasks

Install development dependencies with `poetry install --with dev`, then list the
available commands with `poetry run task --list`. Tasks are configured in
`pyproject.toml`:

```bash
poetry run task test
poetry run task test-unit
poetry run task test-integration
poetry run task test-podman
poetry run task compile
poetry run task lint
poetry run task format-check
poetry run task typecheck
```

`test-podman` requires Podman and enables the existing Podman-specific tests.

## Notes

- `actions/checkout` or the Gitea equivalent should fetch full history. `fetch-depth: 0` is the safest default.
- The default release branch is `main` unless you enable `allow_non_main_release`.
- Generated commits use the configured git author. If you do not set `author_name` and `author_email`, the runner's git configuration is used.
- On both GitHub and Gitea, changelog-only commits and pushes use the repository credentials already configured on the runner, not the explicit `token` input.
- On release runs, changelog commits, branch pushes, and tag pushes still use the runner's configured repository credentials. The explicit `token` input is only used when creating the remote release over the API.
- There is currently no implicit fallback from release publication to the platform default token. If you want to use GitHub's default token for release publication, pass `${{ secrets.GITHUB_TOKEN }}` explicitly.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).