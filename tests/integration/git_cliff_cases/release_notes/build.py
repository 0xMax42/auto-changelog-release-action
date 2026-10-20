from tests.support.git_cliff_fixture import GitCliffFixture


def build(repo: GitCliffFixture) -> None:
    repo.commit("chore: bootstrap")
    repo.tag("v1.0.0")
    repo.commit(
        "chore(releasenotes): rollout instructions",
        body="Restart the service after deploying this release.\n\nBack up the database first.",
    )
    repo.commit("fix(core): avoid duplicate processing")
