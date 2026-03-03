import { spawn } from "node:child_process";

import { StringEnum, Type } from "@mariozechner/pi-ai";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

type GhResult = {
	stdout: string;
	stderr: string;
	exitCode: number;
};

type ToolParams = {
	action: "get_pr" | "get_pr_comments" | "get_linked_issues" | "get_issue" | "search_issues";
	prNumber?: number;
	issueNumber?: number;
	query?: string;
	limit?: number;
	includeBodies?: boolean;
};

function splitRepo(repo: string): { owner: string; name: string } {
	const [owner, name] = repo.split("/", 2);
	if (!owner || !name) {
		throw new Error(`Invalid repository identifier: ${repo}`);
	}
	return { owner, name };
}

function runGh(args: string[], signal?: AbortSignal): Promise<GhResult> {
	return new Promise((resolve, reject) => {
		const child = spawn("gh", args, {
			env: process.env,
			stdio: ["ignore", "pipe", "pipe"],
		});
		let stdout = "";
		let stderr = "";

		const timeout = setTimeout(() => {
			child.kill();
		}, 15000);

		const onAbort = () => child.kill();
		signal?.addEventListener("abort", onAbort, { once: true });

		child.stdout.on("data", (chunk) => {
			stdout += chunk.toString();
		});
		child.stderr.on("data", (chunk) => {
			stderr += chunk.toString();
		});
		child.on("error", (error) => {
			clearTimeout(timeout);
			signal?.removeEventListener("abort", onAbort);
			reject(error);
		});
		child.on("close", (exitCode) => {
			clearTimeout(timeout);
			signal?.removeEventListener("abort", onAbort);
			resolve({
				stdout,
				stderr,
				exitCode: exitCode ?? 1,
			});
		});
	});
}

async function ghJson(args: string[], signal?: AbortSignal): Promise<unknown> {
	const result = await runGh(args, signal);
	if (result.exitCode !== 0) {
		const detail = result.stderr.trim() || result.stdout.trim() || "unknown gh failure";
		throw new Error(`gh command failed: ${detail}`);
	}
	try {
		return JSON.parse(result.stdout || "{}");
	} catch (error) {
		throw new Error(`gh returned invalid JSON: ${String(error)}`);
	}
}

function requireGhAuth(): void {
	if (!process.env.GH_TOKEN && !process.env.GITHUB_TOKEN) {
		throw new Error("Missing GH_TOKEN/GITHUB_TOKEN for github_read tool");
	}
}

function requireRepo(): string {
	const repo = process.env.CERBERUS_REPO || "";
	if (!repo) {
		throw new Error("Missing CERBERUS_REPO");
	}
	return repo;
}

function resolvePrNumber(params: ToolParams): number {
	if (params.prNumber && Number.isInteger(params.prNumber) && params.prNumber > 0) {
		return params.prNumber;
	}
	const fromEnv = Number.parseInt(process.env.CERBERUS_PR_NUMBER || "", 10);
	if (Number.isInteger(fromEnv) && fromEnv > 0) {
		return fromEnv;
	}
	throw new Error("Missing pull request number (prNumber or CERBERUS_PR_NUMBER)");
}

export default function githubReadExtension(pi: ExtensionAPI) {
	pi.registerTool({
		name: "github_read",
		label: "GitHub Read",
		description: "Read-only GitHub context fetch (PR, comments, linked issues, issue, issue search).",
		promptSnippet:
			"Fetch live GitHub context for this PR and related issues using read-only API calls.",
		promptGuidelines: [
			"Use this tool before final verdict to gather linked issues and PR discussion context.",
			"Prefer get_linked_issues for acceptance criteria and scope intent.",
			"Keep requests scoped and bounded with limit values.",
		],
		parameters: Type.Object({
			action: StringEnum(["get_pr", "get_pr_comments", "get_linked_issues", "get_issue", "search_issues"] as const),
			prNumber: Type.Optional(Type.Number({ minimum: 1 })),
			issueNumber: Type.Optional(Type.Number({ minimum: 1 })),
			query: Type.Optional(Type.String()),
			limit: Type.Optional(Type.Number({ minimum: 1, maximum: 100 })),
			includeBodies: Type.Optional(Type.Boolean()),
		}),
		async execute(_toolCallId, rawParams, signal) {
			try {
				requireGhAuth();
				const params = rawParams as ToolParams;
				const repo = requireRepo();
				const limit = Math.max(1, Math.min(100, Number(params.limit || 20)));

				if (params.action === "get_pr") {
					const prNumber = resolvePrNumber(params);
					const payload = await ghJson(
						[
							"api",
							`repos/${repo}/pulls/${prNumber}`,
						],
						signal,
					);
					return {
						content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
						details: payload,
					};
				}

				if (params.action === "get_pr_comments") {
					const prNumber = resolvePrNumber(params);
					const issueComments = await ghJson(
						[
							"api",
							`repos/${repo}/issues/${prNumber}/comments?per_page=${limit}`,
						],
						signal,
					);
					const reviewComments = await ghJson(
						[
							"api",
							`repos/${repo}/pulls/${prNumber}/comments?per_page=${limit}`,
						],
						signal,
					);
					const payload = {
						issue_comments: issueComments,
						review_comments: reviewComments,
					};
					return {
						content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
						details: payload,
					};
				}

				if (params.action === "get_linked_issues") {
					const prNumber = resolvePrNumber(params);
					const { owner, name } = splitRepo(repo);
					const query = `
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 50) {
        nodes {
          number
          title
          url
          state
          body
        }
      }
    }
  }
}
`;
					const payload = await ghJson(
						[
							"api",
							"graphql",
							"-f",
							`query=${query}`,
							"-F",
							`owner=${owner}`,
							"-F",
							`name=${name}`,
							"-F",
							`number=${prNumber}`,
						],
						signal,
					);
					const includeBodies = params.includeBodies !== false;
					if (!includeBodies) {
						const data = payload as {
							data?: {
								repository?: {
									pullRequest?: {
										closingIssuesReferences?: {
											nodes?: Array<Record<string, unknown>>;
										};
									};
								};
							};
						};
						const nodes =
							data.data?.repository?.pullRequest?.closingIssuesReferences?.nodes || [];
						for (const node of nodes) {
							delete node.body;
						}
					}

					return {
						content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
						details: payload,
					};
				}

				if (params.action === "get_issue") {
					if (!params.issueNumber || params.issueNumber <= 0) {
						throw new Error("issueNumber is required for get_issue");
					}
					const payload = await ghJson(
						[
							"api",
							`repos/${repo}/issues/${params.issueNumber}`,
						],
						signal,
					);
					return {
						content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
						details: payload,
					};
				}

				if (params.action === "search_issues") {
					const query = (params.query || "").trim();
					if (!query) {
						throw new Error("query is required for search_issues");
					}
					const payload = await ghJson(
						[
							"api",
							"search/issues",
							"-f",
							`q=repo:${repo} ${query}`,
							"-f",
							`per_page=${limit}`,
						],
						signal,
					);
					return {
						content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
						details: payload,
					};
				}

				throw new Error(`Unsupported action: ${params.action}`);
			} catch (error) {
				return {
					content: [{ type: "text", text: `github_read error: ${String(error)}` }],
					details: { error: String(error) },
					isError: true,
				};
			}
		},
	});
}
