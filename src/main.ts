import * as core from "@actions/core";
import { context } from "@actions/github";
import { readActionEnvironment } from "./environment.js";
import { createGitClient } from "./git/mod.js";

async function main(): Promise<void> {
  const environment = readActionEnvironment();
  const git = createGitClient(process.cwd());

  core.info("Auto Changelog & Release — Node.js bootstrap");
  core.info(`Event: ${environment.eventName}`);
  core.info(`Repository: ${environment.repository ?? "(not running in Actions)"}`);
  core.debug(`Git client initialized: ${git.constructor.name}`);
  core.debug(`Toolkit context event: ${context.eventName || "(unset)"}`);
  core.info("Bootstrap ready. No version bump, Git write, or release is performed.");
}

main().catch((error: unknown) => {
  core.setFailed(error instanceof Error ? error : String(error));
});
