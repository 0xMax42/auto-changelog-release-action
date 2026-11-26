from tests.support.git_cliff_fixture import GitCliffFixture


def build(repo: GitCliffFixture) -> None:
    repo.commit("chore: bootstrap")
    repo.tag("v2.0.0")
    repo.commit("feat(api): add status endpoint")
    repo.tag("v10.0.0-pre.1")
    repo.commit("fix: handle empty response")
