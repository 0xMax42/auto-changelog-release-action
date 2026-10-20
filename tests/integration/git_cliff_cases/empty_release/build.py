from tests.support.git_cliff_fixture import GitCliffFixture


def build(repo: GitCliffFixture) -> None:
    repo.commit("feat: initial feature")
    repo.tag("v1.0.0")
    repo.commit("chore(version): bump version to 1.0.1")
