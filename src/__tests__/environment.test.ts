import assert from "node:assert/strict";
import test from "node:test";
import { readActionEnvironment } from "../environment.js";

test("reads GitHub-compatible Actions variables", () => {
  assert.deepEqual(
    readActionEnvironment({
      GITHUB_EVENT_NAME: "schedule",
      GITHUB_REPOSITORY: "actions/auto-changelog-release-action",
    }),
    {
      eventName: "schedule",
      repository: "actions/auto-changelog-release-action",
    },
  );
});

test("accepts Gitea-specific variable names", () => {
  assert.deepEqual(
    readActionEnvironment({
      GITEA_EVENT_NAME: "push",
      GITEA_REPOSITORY: "actions/auto-changelog-release-action",
    }),
    {
      eventName: "push",
      repository: "actions/auto-changelog-release-action",
    },
  );
});

test("runs locally without an Actions environment", () => {
  assert.deepEqual(readActionEnvironment({}), {
    eventName: "local",
    repository: null,
  });
});
