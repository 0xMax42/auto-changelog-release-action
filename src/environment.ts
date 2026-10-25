export interface ActionEnvironment {
  readonly eventName: string;
  readonly repository: string | null;
}

/** Resolve common Actions variables without assuming GitHub-only execution. */
export function readActionEnvironment(
  environment: NodeJS.ProcessEnv = process.env,
): ActionEnvironment {
  return {
    eventName: environment.GITHUB_EVENT_NAME ?? environment.GITEA_EVENT_NAME ?? "local",
    repository: environment.GITHUB_REPOSITORY ?? environment.GITEA_REPOSITORY ?? null,
  };
}
