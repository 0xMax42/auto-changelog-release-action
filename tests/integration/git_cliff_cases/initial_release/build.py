from tests.support.git_cliff_fixture import GitCliffFixture


def build(repo: GitCliffFixture) -> None:
    repo.commit("chore: bootstrap")
    repo.tag("v0.1.0-pre.1")
    repo.commit("feat(api): add status endpoint")
