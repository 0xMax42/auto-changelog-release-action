from tests.support.git_cliff_fixture import GitCliffFixture


def build(repo: GitCliffFixture) -> None:
    repo.commit("chore: bootstrap")
    repo.tag("v1.0.0")
    repo.commit("feat(api): add status endpoint")
    repo.commit("fix: handle empty response")
