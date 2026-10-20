# git-cliff template integration cases

Each subdirectory is automatically discovered by `test_git_cliff_templates.py` and must
contain three files:

- `case.json`: `mode` (`release` or `unreleased`), `host` (`gitea` or `github`),
  and `version` for a release.
- `build.py`: a `build(repo: GitCliffFixture)` function which creates the Git history.
- `expected.md`: the exact expected `CHANGELOG.md` output.

`GitCliffFixture` fixes author/committer identity, timestamps, tag metadata, Git
configuration, and SHA-1 object format. Do not introduce random data or current timestamps.
Release fixtures must include earlier release tags where needed, but must **not** create
an existing tag for the target version: the action renders with `git-cliff -t vVERSION`
before committing the changelog and creating that tag. The tests run only the
`git-cliff` subprocesses with a fixed clock (`2026-01-15 18:00:00` UTC), so the
entire generated Markdown can be compared byte-for-byte without normalization.

The tests use the real `git-cliff` binary, the checked-in template and the production
`--context -> augment_context_json -> --from-context` pipeline. They run offline
and do not publish commits, tags, or releases.

With Git and `faketime` installed on Linux x86_64, check the recorded output locally.
The Taskipy hook prepares the official git-cliff binary pinned in
`versions.gitcliff.env` under `.cache/tools/git-cliff/` if necessary. The test
does not use a system-installed git-cliff:

```bash
poetry run task goldens-check
```

To intentionally regenerate golden files after a template change:

```bash
poetry run task goldens-update
git diff -- tests/integration/git_cliff_cases/
```

Never enable golden updates in CI. Review the complete diff before accepting new output.
