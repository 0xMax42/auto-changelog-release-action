import { ConventionalGitClient } from "@conventional-changelog/git-client";

/** Create a Git client for the caller's checked-out repository. */
export function createGitClient(repositoryPath: string): ConventionalGitClient {
  return new ConventionalGitClient(repositoryPath);
}
