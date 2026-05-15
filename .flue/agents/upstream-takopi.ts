import { execFile as execFileCallback } from "node:child_process";
import { readFileSync } from "node:fs";
import { promisify } from "node:util";
import { Octokit } from "@octokit/core";
import type { FlueContext } from "@flue/runtime";
import { local } from "@flue/runtime/node";
import * as v from "valibot";

const execFile = promisify(execFileCallback);

export const triggers = {};

const TRACKING_LABEL = "upstream-takopi";
const AGENT_LABEL = "agent-triage";
const DEFAULT_MODEL = "kimi-coding/kimi-for-coding";

const analysisSchema = v.object({
  relevant: v.boolean(),
  confidence: v.picklist(["low", "medium", "high"]),
  needs_pr: v.boolean(),
  pr_scope: v.picklist(["none", "dependency-only", "code", "docs", "tests"]),
  title: v.string(),
  summary: v.string(),
  affected_areas: v.array(v.string()),
  upstream_changes: v.array(v.string()),
  recommended_changes: v.array(v.string()),
  implementation_plan: v.array(v.string()),
  risk_notes: v.array(v.string()),
});

const implementationSchema = v.object({
  changed: v.boolean(),
  summary: v.string(),
  tests: v.array(v.string()),
  notes: v.array(v.string()),
});

type Analysis = v.InferOutput<typeof analysisSchema>;
type Implementation = v.InferOutput<typeof implementationSchema>;

type Payload = {
  owner?: string;
  repo?: string;
  upstreamOwner?: string;
  upstreamRepo?: string;
  baseRef?: string;
  targetRef?: string;
  createPr?: "auto" | "always" | "never" | "";
  dryRun?: boolean | string;
  force?: boolean | string;
};

type Repo = {
  owner: string;
  repo: string;
};

type UpstreamTarget = {
  ref: string;
  sha: string;
  releaseName?: string;
  releaseBody?: string;
  htmlUrl: string;
};

type Comparison = {
  status: string;
  aheadBy: number;
  behindBy: number;
  htmlUrl: string;
  commits: Array<{ sha: string; message: string; author?: string }>;
  files: Array<{
    filename: string;
    status?: string;
    additions?: number;
    deletions?: number;
    changes?: number;
    patch?: string;
  }>;
};

export default async function ({ init, payload, env }: FlueContext) {
  const runtimeEnv = env as Record<string, string | undefined>;
  const config = normalizePayload(payload as Payload);
  const repo = resolveRepo(config, runtimeEnv);
  const upstream = {
    owner: config.upstreamOwner || "banteg",
    repo: config.upstreamRepo || "takopi",
  };
  const githubToken = getEnv(runtimeEnv, "GITHUB_TOKEN");

  if (!githubToken) {
    throw new Error("GITHUB_TOKEN is required to create issues and pull requests.");
  }

  const octokit = new Octokit({ auth: githubToken });
  const target = await resolveTarget(octokit, upstream, config.targetRef);
  const existingIssue = await findIssueForTarget(octokit, repo, target.ref);

  if (existingIssue && !config.force) {
    return {
      skipped: true,
      reason: `Issue #${existingIssue.number} already tracks ${target.ref}.`,
      issue: existingIssue.html_url,
    };
  }

  const baseRef =
    config.baseRef ||
    (await findPreviousTrackedRef(octokit, repo, target.ref)) ||
    deriveTakopiLowerBound() ||
    target.sha;

  if (baseRef === target.ref || baseRef === target.sha) {
    return {
      skipped: true,
      reason: `No earlier upstream ref found to compare against ${target.ref}.`,
      upstreamRef: target.ref,
    };
  }

  const comparison = await compareUpstream(octokit, upstream, baseRef, target.ref);
  if (comparison.status === "identical") {
    return {
      skipped: true,
      reason: `${upstream.owner}/${upstream.repo} has no changes from ${baseRef} to ${target.ref}.`,
      upstreamRef: target.ref,
    };
  }

  const model = getEnv(runtimeEnv, "FLUE_MODEL") || DEFAULT_MODEL;
  const harness = await init({
    sandbox: local(),
    model,
  });
  const session = await harness.session(`takopi-upstream-${sanitizeRef(target.ref)}`);

  const { data: analysis } = await session.prompt(
    buildAnalysisPrompt({
      repo,
      upstream,
      baseRef,
      target,
      comparison,
    }),
    { result: analysisSchema },
  );

  if (!analysis.relevant && !config.force) {
    return {
      skipped: true,
      reason: `Takopi ${target.ref} was not judged relevant to this Discord transport.`,
      analysis,
    };
  }

  await ensureLabels(octokit, repo);
  const issueBody = buildIssueBody({
    upstream,
    baseRef,
    target,
    comparison,
    analysis,
  });

  if (config.dryRun) {
    return {
      dryRun: true,
      wouldCreateIssue: true,
      wouldCreatePr: shouldCreatePr(config.createPr, analysis),
      analysis,
      issueBody,
    };
  }

  const issue =
    existingIssue ||
    (await createIssue(octokit, repo, {
      title: `Evaluate ${upstream.owner}/${upstream.repo} ${target.ref}: ${analysis.title}`,
      body: issueBody,
      labels: [TRACKING_LABEL, AGENT_LABEL],
    }));

  if (!shouldCreatePr(config.createPr, analysis)) {
    return {
      issue: issue.html_url,
      pr: null,
      analysis,
      reason: "PR creation was disabled or not recommended by the analysis.",
    };
  }

  const baseBranch = await currentBranch();
  const branch = `agent/takopi-${sanitizeRef(target.ref)}`;
  await createWorkingBranch(branch);

  const { data: implementation } = await session.prompt(
    buildImplementationPrompt({
      repo,
      upstream,
      baseRef,
      target,
      issueNumber: issue.number,
      analysis,
    }),
    { result: implementationSchema },
  );

  const changedFiles = await getChangedFiles();
  if (!implementation.changed || changedFiles.length === 0) {
    await commentOnIssue(
      octokit,
      repo,
      issue.number,
      [
        "The automation analyzed this upstream change but did not produce a patch.",
        "",
        `Agent summary: ${implementation.summary}`,
        "",
        ...implementation.notes.map((note) => `- ${note}`),
      ].join("\n"),
    );

    return {
      issue: issue.html_url,
      pr: null,
      analysis,
      implementation,
      changedFiles,
    };
  }

  await commitAndPush(branch, githubToken, target.ref);
  const pr = await createPullRequest(octokit, repo, {
    branch,
    base: baseBranch,
    title: `Adapt to ${upstream.repo} ${target.ref}`,
    body: buildPrBody({
      issueNumber: issue.number,
      upstream,
      baseRef,
      target,
      analysis,
      implementation,
      changedFiles,
    }),
  });

  await commentOnIssue(
    octokit,
    repo,
    issue.number,
    `Opened draft PR #${pr.number}: ${pr.html_url}`,
  );

  return {
    issue: issue.html_url,
    pr: pr.html_url,
    analysis,
    implementation,
    changedFiles,
  };
}

function normalizePayload(payload: Payload): Required<Payload> {
  return {
    owner: payload.owner || "",
    repo: payload.repo || "",
    upstreamOwner: payload.upstreamOwner || "banteg",
    upstreamRepo: payload.upstreamRepo || "takopi",
    baseRef: payload.baseRef || "",
    targetRef: payload.targetRef || "",
    createPr: payload.createPr || "auto",
    dryRun: parseBool(payload.dryRun),
    force: parseBool(payload.force),
  };
}

function parseBool(value: boolean | string | undefined): boolean {
  return value === true || value === "true";
}

function getEnv(env: Record<string, string | undefined>, name: string): string | undefined {
  return env[name] || process.env[name];
}

function resolveRepo(config: Required<Payload>, env: Record<string, string | undefined>): Repo {
  if (config.owner && config.repo) {
    return { owner: config.owner, repo: config.repo };
  }

  const repository = getEnv(env, "GITHUB_REPOSITORY");
  if (!repository) {
    throw new Error("Pass owner/repo in the payload or set GITHUB_REPOSITORY.");
  }

  const [owner, repo] = repository.split("/");
  if (!owner || !repo) {
    throw new Error(`Invalid GITHUB_REPOSITORY: ${repository}`);
  }
  return { owner, repo };
}

async function resolveTarget(
  octokit: Octokit,
  upstream: Repo,
  requestedRef?: string,
): Promise<UpstreamTarget> {
  if (requestedRef) {
    const sha = await commitSha(octokit, upstream, requestedRef);
    return {
      ref: requestedRef,
      sha,
      htmlUrl: `https://github.com/${upstream.owner}/${upstream.repo}/commit/${sha}`,
    };
  }

  try {
    const release = await octokit.request("GET /repos/{owner}/{repo}/releases/latest", {
      owner: upstream.owner,
      repo: upstream.repo,
    });
    const ref = release.data.tag_name;
    const sha = await commitSha(octokit, upstream, ref);
    return {
      ref,
      sha,
      releaseName: release.data.name || ref,
      releaseBody: release.data.body || "",
      htmlUrl: release.data.html_url,
    };
  } catch (error) {
    if (!isNotFound(error)) {
      throw error;
    }
  }

  const tags = await octokit.request("GET /repos/{owner}/{repo}/tags", {
    owner: upstream.owner,
    repo: upstream.repo,
    per_page: 1,
  });
  const tag = tags.data[0];
  if (!tag) {
    throw new Error(`No releases or tags found for ${upstream.owner}/${upstream.repo}.`);
  }
  return {
    ref: tag.name,
    sha: tag.commit.sha,
    htmlUrl: `https://github.com/${upstream.owner}/${upstream.repo}/releases/tag/${tag.name}`,
  };
}

async function commitSha(octokit: Octokit, repo: Repo, ref: string): Promise<string> {
  const commit = await octokit.request("GET /repos/{owner}/{repo}/commits/{ref}", {
    owner: repo.owner,
    repo: repo.repo,
    ref,
  });
  return commit.data.sha;
}

async function compareUpstream(
  octokit: Octokit,
  upstream: Repo,
  baseRef: string,
  targetRef: string,
): Promise<Comparison> {
  const comparison = await octokit.request("GET /repos/{owner}/{repo}/compare/{basehead}", {
    owner: upstream.owner,
    repo: upstream.repo,
    basehead: `${baseRef}...${targetRef}`,
    per_page: 100,
  });

  return {
    status: comparison.data.status,
    aheadBy: comparison.data.ahead_by,
    behindBy: comparison.data.behind_by,
    htmlUrl: comparison.data.html_url,
    commits: comparison.data.commits.slice(0, 50).map((commit) => ({
      sha: commit.sha,
      message: commit.commit.message,
      author: commit.commit.author?.name,
    })),
    files: (comparison.data.files || []).slice(0, 100).map((file) => ({
      filename: file.filename,
      status: file.status,
      additions: file.additions,
      deletions: file.deletions,
      changes: file.changes,
      patch: file.patch,
    })),
  };
}

async function findIssueForTarget(octokit: Octokit, repo: Repo, targetRef: string) {
  const issues = await listTrackingIssues(octokit, repo);
  return issues.find(
    (issue) =>
      !("pull_request" in issue) &&
      typeof issue.body === "string" &&
      issue.body.includes(`upstream-ref: ${targetRef}`),
  );
}

async function findPreviousTrackedRef(
  octokit: Octokit,
  repo: Repo,
  targetRef: string,
): Promise<string | undefined> {
  const issues = await listTrackingIssues(octokit, repo);
  for (const issue of issues) {
    if ("pull_request" in issue || typeof issue.body !== "string") {
      continue;
    }

    const match = issue.body.match(/^upstream-ref:\s*(.+)$/m);
    if (match && match[1] !== targetRef) {
      return match[1].trim();
    }
  }
  return undefined;
}

async function listTrackingIssues(octokit: Octokit, repo: Repo) {
  const response = await octokit.request("GET /repos/{owner}/{repo}/issues", {
    owner: repo.owner,
    repo: repo.repo,
    labels: TRACKING_LABEL,
    state: "all",
    per_page: 50,
    sort: "created",
    direction: "desc",
  });
  return response.data;
}

function deriveTakopiLowerBound(): string | undefined {
  const pyproject = readFileSync("pyproject.toml", "utf8");
  const match = pyproject.match(/"takopi>=([^"]+)"/);
  return match ? `v${match[1]}` : undefined;
}

async function ensureLabels(octokit: Octokit, repo: Repo): Promise<void> {
  await Promise.all([
    ensureLabel(octokit, repo, TRACKING_LABEL, "0366d6", "Tracks upstream Takopi changes"),
    ensureLabel(octokit, repo, AGENT_LABEL, "6f42c1", "Created by automation"),
  ]);
}

async function ensureLabel(
  octokit: Octokit,
  repo: Repo,
  name: string,
  color: string,
  description: string,
): Promise<void> {
  try {
    await octokit.request("POST /repos/{owner}/{repo}/labels", {
      owner: repo.owner,
      repo: repo.repo,
      name,
      color,
      description,
    });
  } catch (error) {
    if (!isValidationError(error)) {
      throw error;
    }
  }
}

async function createIssue(
  octokit: Octokit,
  repo: Repo,
  issue: { title: string; body: string; labels: string[] },
) {
  const response = await octokit.request("POST /repos/{owner}/{repo}/issues", {
    owner: repo.owner,
    repo: repo.repo,
    title: issue.title,
    body: issue.body,
    labels: issue.labels,
  });
  return response.data;
}

async function commentOnIssue(
  octokit: Octokit,
  repo: Repo,
  issueNumber: number,
  body: string,
): Promise<void> {
  await octokit.request("POST /repos/{owner}/{repo}/issues/{issue_number}/comments", {
    owner: repo.owner,
    repo: repo.repo,
    issue_number: issueNumber,
    body,
  });
}

async function createPullRequest(
  octokit: Octokit,
  repo: Repo,
  pr: { branch: string; base: string; title: string; body: string },
) {
  const response = await octokit.request("POST /repos/{owner}/{repo}/pulls", {
    owner: repo.owner,
    repo: repo.repo,
    title: pr.title,
    head: pr.branch,
    base: pr.base,
    body: pr.body,
    draft: true,
  });
  return response.data;
}

function shouldCreatePr(mode: Payload["createPr"], analysis: Analysis): boolean {
  if (mode === "never") {
    return false;
  }
  if (mode === "always") {
    return analysis.relevant;
  }
  return analysis.relevant && analysis.needs_pr && analysis.confidence !== "low";
}

function buildAnalysisPrompt(input: {
  repo: Repo;
  upstream: Repo;
  baseRef: string;
  target: UpstreamTarget;
  comparison: Comparison;
}): string {
  const readme = readFileSync("README.md", "utf8").slice(0, 8000);
  const pyproject = readFileSync("pyproject.toml", "utf8");

  return [
    "You are evaluating upstream Takopi changes for takopi-discord.",
    "",
    "takopi-discord is a Discord transport plugin for Takopi. It maps Discord categories, channels, threads, slash commands, file transfer, voice, and trigger modes onto Takopi projects, branches, sessions, engines, and transport APIs.",
    "",
    "Focus on upstream changes that affect:",
    "- Takopi public or plugin APIs",
    "- transport backend contracts",
    "- runner, model, event, action, resume token, or progress schemas",
    "- settings/config migration behavior",
    "- command/plugin registration",
    "- file transfer or media handling expectations",
    "- docs/spec/invariant changes that imply behavior this transport should mirror",
    "",
    "Do not recommend a PR for unrelated internal refactors, docs unrelated to transports, or features that require human product decisions before implementation.",
    "During this analysis step, do not modify files. Only inspect the repository and upstream context.",
    "",
    `Current repo: ${input.repo.owner}/${input.repo.repo}`,
    `Upstream repo: ${input.upstream.owner}/${input.upstream.repo}`,
    `Compared refs: ${input.baseRef}...${input.target.ref}`,
    `Compare URL: ${input.comparison.htmlUrl}`,
    input.target.releaseName ? `Release: ${input.target.releaseName}` : "",
    input.target.releaseBody ? `Release notes:\n${input.target.releaseBody.slice(0, 6000)}` : "",
    "",
    `pyproject.toml:\n${pyproject}`,
    "",
    `README excerpt:\n${readme}`,
    "",
    "Upstream commits:",
    ...input.comparison.commits.map(
      (commit) => `- ${commit.sha.slice(0, 12)} ${firstLine(commit.message)}`,
    ),
    "",
    "Changed upstream files:",
    ...input.comparison.files.map(
      (file) =>
        `- ${file.status || "modified"} ${file.filename} (+${file.additions || 0}/-${file.deletions || 0})`,
    ),
    "",
    "Relevant upstream patches, truncated:",
    ...input.comparison.files
      .filter((file) => isLikelyRelevantUpstreamFile(file.filename))
      .slice(0, 20)
      .map((file) => `### ${file.filename}\n${(file.patch || "").slice(0, 2500)}`),
    "",
    "Return structured data only. Keep recommendations specific to takopi-discord.",
  ]
    .filter(Boolean)
    .join("\n");
}

function buildImplementationPrompt(input: {
  repo: Repo;
  upstream: Repo;
  baseRef: string;
  target: UpstreamTarget;
  issueNumber: number;
  analysis: Analysis;
}): string {
  return [
    `Implement the relevant adaptation for ${input.repo.owner}/${input.repo.repo}.`,
    "",
    `Upstream: ${input.upstream.owner}/${input.upstream.repo} ${input.baseRef}...${input.target.ref}`,
    `Tracking issue: #${input.issueNumber}`,
    "",
    "Analysis summary:",
    input.analysis.summary,
    "",
    "Recommended changes:",
    ...input.analysis.recommended_changes.map((change) => `- ${change}`),
    "",
    "Implementation plan:",
    ...input.analysis.implementation_plan.map((step) => `- ${step}`),
    "",
    "Constraints:",
    "- Keep the patch focused on the upstream compatibility or feature adaptation.",
    "- Do not modify GitHub workflow or Flue automation files as part of this implementation.",
    "- Add or update tests when behavior changes.",
    "- Run the smallest relevant test command you can.",
    "- Do not push, create issues, create PRs, or use GitHub credentials.",
    "",
    "Return structured data describing what changed and which tests ran.",
  ].join("\n");
}

function buildIssueBody(input: {
  upstream: Repo;
  baseRef: string;
  target: UpstreamTarget;
  comparison: Comparison;
  analysis: Analysis;
}): string {
  return [
    "<!-- upstream-takopi-tracker",
    `upstream-repo: ${input.upstream.owner}/${input.upstream.repo}`,
    `base-ref: ${input.baseRef}`,
    `upstream-ref: ${input.target.ref}`,
    `upstream-sha: ${input.target.sha}`,
    "-->",
    "",
    `Upstream ${input.upstream.owner}/${input.upstream.repo} has changes from \`${input.baseRef}\` to \`${input.target.ref}\` that may matter for this Discord transport.`,
    "",
    `Compare: ${input.comparison.htmlUrl}`,
    `Release: ${input.target.htmlUrl}`,
    "",
    "## Assessment",
    "",
    `- Relevant: ${input.analysis.relevant}`,
    `- Confidence: ${input.analysis.confidence}`,
    `- PR recommended: ${input.analysis.needs_pr}`,
    `- PR scope: ${input.analysis.pr_scope}`,
    "",
    input.analysis.summary,
    "",
    "## Affected Areas",
    "",
    ...input.analysis.affected_areas.map((area) => `- ${area}`),
    "",
    "## Upstream Changes",
    "",
    ...input.analysis.upstream_changes.map((change) => `- ${change}`),
    "",
    "## Recommended Changes",
    "",
    ...input.analysis.recommended_changes.map((change) => `- ${change}`),
    "",
    "## Implementation Plan",
    "",
    ...input.analysis.implementation_plan.map((step) => `- ${step}`),
    "",
    "## Risks",
    "",
    ...input.analysis.risk_notes.map((note) => `- ${note}`),
  ].join("\n");
}

function buildPrBody(input: {
  issueNumber: number;
  upstream: Repo;
  baseRef: string;
  target: UpstreamTarget;
  analysis: Analysis;
  implementation: Implementation;
  changedFiles: string[];
}): string {
  return [
    `Refs #${input.issueNumber}`,
    "",
    `Draft adaptation for ${input.upstream.owner}/${input.upstream.repo} ${input.baseRef}...${input.target.ref}.`,
    "",
    "## Upstream Assessment",
    "",
    input.analysis.summary,
    "",
    "## Implementation",
    "",
    input.implementation.summary,
    "",
    "## Changed Files",
    "",
    ...input.changedFiles.map((file) => `- ${file}`),
    "",
    "## Tests",
    "",
    ...input.implementation.tests.map((test) => `- ${test}`),
    "",
    "## Notes",
    "",
    ...input.implementation.notes.map((note) => `- ${note}`),
  ].join("\n");
}

async function createWorkingBranch(branch: string): Promise<void> {
  await trustedGit(["config", "user.name", "takopi-upstream-agent"]);
  await trustedGit(["config", "user.email", "takopi-upstream-agent@users.noreply.github.com"]);
  await trustedGit(["switch", "-c", branch]);
}

async function getChangedFiles(): Promise<string[]> {
  const { stdout } = await trustedGit(["status", "--short"]);
  return stdout
    .split("\n")
    .map((line) => line.trim())
    .map((line) => line.slice(3))
    .map((line) => line.split(" -> ").at(-1) || line)
    .filter(Boolean);
}

async function commitAndPush(branch: string, githubToken: string, targetRef: string): Promise<void> {
  await trustedGit(["add", "-A"]);
  await trustedGit(["commit", "-m", `chore: adapt to takopi ${targetRef}`]);
  await runTrusted("gh", ["auth", "setup-git", "--hostname", "github.com"], {
    GH_TOKEN: githubToken,
    GITHUB_TOKEN: githubToken,
  });
  await runTrusted("git", ["push", "--set-upstream", "origin", branch], {
    GH_TOKEN: githubToken,
    GITHUB_TOKEN: githubToken,
  });
}

async function currentBranch(): Promise<string> {
  const { stdout } = await trustedGit(["branch", "--show-current"]);
  return stdout.trim() || "main";
}

async function trustedGit(args: string[]) {
  return await runTrusted("git", args);
}

async function runTrusted(
  command: string,
  args: string[],
  extraEnv: Record<string, string> = {},
) {
  return await execFile(command, args, {
    env: { ...process.env, ...extraEnv },
    maxBuffer: 1024 * 1024 * 10,
  });
}

function firstLine(value: string): string {
  return value.split("\n")[0] || "";
}

function sanitizeRef(ref: string): string {
  return ref
    .toLowerCase()
    .replace(/^refs\/tags\//, "")
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function isLikelyRelevantUpstreamFile(filename: string): boolean {
  return [
    "src/takopi/api.py",
    "src/takopi/model.py",
    "src/takopi/runner.py",
    "src/takopi/router.py",
    "src/takopi/settings.py",
    "src/takopi/config_migrations.py",
    "src/takopi/plugins.py",
    "src/takopi/transports.py",
    "src/takopi/commands.py",
    "src/takopi/progress.py",
    "src/takopi/markdown.py",
    "src/takopi/schemas/",
    "src/takopi/runners/",
    "tests/test_runner_contract.py",
    "docs/",
    "mkdocs.yml",
    "CHANGELOG.md",
  ].some((prefix) => filename === prefix || filename.startsWith(prefix));
}

function isNotFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "status" in error && error.status === 404;
}

function isValidationError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "status" in error && error.status === 422;
}
