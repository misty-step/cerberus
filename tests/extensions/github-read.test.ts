import assert from "node:assert/strict";
import fs from "node:fs";
import Module from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";

type RegisteredTool = {
	execute: (toolCallId: string, rawParams: unknown, signal?: AbortSignal) => Promise<any>;
};

let githubReadExtensionPromise: Promise<(pi: any) => void> | undefined;

async function loadGithubReadExtension(): Promise<(pi: any) => void> {
	if (!githubReadExtensionPromise) {
		const stubRoot = fs.mkdtempSync(path.join(os.tmpdir(), "cerberus-nodepath-"));
		const piAiDir = path.join(stubRoot, "@mariozechner", "pi-ai");
		const agentDir = path.join(stubRoot, "@mariozechner", "pi-coding-agent");
		fs.mkdirSync(piAiDir, { recursive: true });
		fs.mkdirSync(agentDir, { recursive: true });
		fs.writeFileSync(
			path.join(piAiDir, "index.js"),
			`exports.StringEnum = (values) => values;
exports.Type = {
  Object: (value) => value,
  Optional: (value) => value,
  Number: (value) => value,
  String: () => "string",
  Boolean: () => "boolean",
};
`,
			"utf8",
		);
		fs.writeFileSync(path.join(agentDir, "index.js"), "module.exports = {};\n", "utf8");
		process.env.NODE_PATH = process.env.NODE_PATH
			? `${stubRoot}${path.delimiter}${process.env.NODE_PATH}`
			: stubRoot;
		(Module as any)._initPaths();
		githubReadExtensionPromise = import("../../pi/extensions/github-read.ts").then((mod) => mod.default);
	}
	return githubReadExtensionPromise;
}

async function createRegisteredTool(): Promise<RegisteredTool> {
	let tool: RegisteredTool | undefined;
	const githubReadExtension = await loadGithubReadExtension();
	githubReadExtension({
		registerTool(definition: RegisteredTool) {
			tool = definition;
		},
	} as any);
	assert.ok(tool, "github_read should register a tool");
	return tool;
}

function createFakeGh() {
	const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cerberus-gh-"));
	const logFile = path.join(dir, "gh-calls.ndjson");
	const ghPath = path.join(dir, "gh");
	fs.writeFileSync(
		ghPath,
		`#!/usr/bin/env node
const fs = require("node:fs");
const args = process.argv.slice(2);
if (process.env.GH_LOG_FILE) {
  fs.appendFileSync(process.env.GH_LOG_FILE, JSON.stringify(args) + "\\n", "utf8");
}
const sleepMs = Number(process.env.GH_SLEEP_MS || "0");
const run = () => {
  if (process.env.GH_STDERR) {
    process.stderr.write(process.env.GH_STDERR);
  }
  const exitCode = Number(process.env.GH_EXIT_CODE || "0");
  if (exitCode !== 0) {
    process.exit(exitCode);
  }
  const joined = args.join(" ");
  let output = process.env.GH_DEFAULT_OUTPUT ?? '{"ok":true}';
  if (joined.includes("graphql")) {
    output = process.env.GH_GRAPHQL_OUTPUT ?? '{"data":{}}';
  } else if (joined.includes("/issues/") && joined.includes("/comments")) {
    output = process.env.GH_ISSUE_COMMENTS_OUTPUT ?? "[]";
  } else if (joined.includes("/pulls/") && joined.includes("/comments")) {
    output = process.env.GH_REVIEW_COMMENTS_OUTPUT ?? "[]";
  } else if (joined.includes("/pulls/")) {
    output = process.env.GH_PULL_OUTPUT ?? '{"number":1}';
  } else if (joined.includes("/issues/")) {
    output = process.env.GH_ISSUE_OUTPUT ?? '{"number":1}';
  } else if (joined.includes("search/issues")) {
    output = process.env.GH_SEARCH_OUTPUT ?? '{"items":[]}';
  }
  process.stdout.write(output);
};
if (sleepMs > 0) {
  setTimeout(run, sleepMs);
} else {
  run();
}
`,
		"utf8",
	);
	fs.chmodSync(ghPath, 0o755);
	return {
		dir,
		logFile,
		cleanup() {
			fs.rmSync(dir, { recursive: true, force: true });
		},
	};
}

function readCalls(logFile: string): string[][] {
	if (!fs.existsSync(logFile)) {
		return [];
	}
	return fs
		.readFileSync(logFile, "utf8")
		.trim()
		.split("\n")
		.filter(Boolean)
		.map((line) => JSON.parse(line));
}

function withEnv(overrides: Record<string, string | undefined>) {
	const previous = new Map<string, string | undefined>();
	for (const [key, value] of Object.entries(overrides)) {
		previous.set(key, process.env[key]);
		if (value === undefined) {
			delete process.env[key];
		} else {
			process.env[key] = value;
		}
	}
	return () => {
		for (const [key, value] of previous.entries()) {
			if (value === undefined) {
				delete process.env[key];
			} else {
				process.env[key] = value;
			}
		}
	};
}

test("get_pr uses env fallback and returns parsed payload", async () => {
	const tool = await createRegisteredTool();
	const fakeGh = createFakeGh();
	const restoreEnv = withEnv({
		PATH: `${fakeGh.dir}:${process.env.PATH || ""}`,
		GH_LOG_FILE: fakeGh.logFile,
		GH_TOKEN: "token",
		CERBERUS_REPO: "misty-step/cerberus",
		CERBERUS_PR_NUMBER: "316",
		GH_PULL_OUTPUT: '{"number":316,"title":"Inject acceptance criteria"}',
	});

	try {
		const result = await tool.execute("call-1", { action: "get_pr" });
		assert.equal(result.isError, undefined);
		assert.equal(result.details.number, 316);
		assert.equal(result.details.title, "Inject acceptance criteria");
		assert.deepEqual(readCalls(fakeGh.logFile), [["api", "repos/misty-step/cerberus/pulls/316"]]);
	} finally {
		restoreEnv();
		fakeGh.cleanup();
	}
});

test("get_pr_comments merges issue and review comments", async () => {
	const tool = await createRegisteredTool();
	const fakeGh = createFakeGh();
	const restoreEnv = withEnv({
		PATH: `${fakeGh.dir}:${process.env.PATH || ""}`,
		GH_LOG_FILE: fakeGh.logFile,
		GH_TOKEN: "token",
		CERBERUS_REPO: "misty-step/cerberus",
		GH_ISSUE_COMMENTS_OUTPUT: '[{"id":1,"body":"issue"}]',
		GH_REVIEW_COMMENTS_OUTPUT: '[{"id":2,"body":"review"}]',
	});

	try {
		const result = await tool.execute("call-2", { action: "get_pr_comments", prNumber: 319, limit: 3 });
		assert.equal(result.isError, undefined);
		assert.deepEqual(result.details, {
			issue_comments: [{ id: 1, body: "issue" }],
			review_comments: [{ id: 2, body: "review" }],
		});
		assert.deepEqual(readCalls(fakeGh.logFile), [
			["api", "repos/misty-step/cerberus/issues/319/comments?per_page=3"],
			["api", "repos/misty-step/cerberus/pulls/319/comments?per_page=3"],
		]);
	} finally {
		restoreEnv();
		fakeGh.cleanup();
	}
});

test("get_linked_issues truncates limit and strips bodies when requested", async () => {
	const tool = await createRegisteredTool();
	const fakeGh = createFakeGh();
	const restoreEnv = withEnv({
		PATH: `${fakeGh.dir}:${process.env.PATH || ""}`,
		GH_LOG_FILE: fakeGh.logFile,
		GH_TOKEN: "token",
		CERBERUS_REPO: "misty-step/cerberus",
		GH_GRAPHQL_OUTPUT:
			'{"data":{"repository":{"pullRequest":{"closingIssuesReferences":{"nodes":[{"number":310,"title":"AC","url":"https://example.com","state":"OPEN","body":"drop me"}]}}}}}',
	});

	try {
		const result = await tool.execute("call-3", {
			action: "get_linked_issues",
			prNumber: 316,
			limit: 2.9,
			includeBodies: false,
		});
		const nodes = result.details.data.repository.pullRequest.closingIssuesReferences.nodes;
		assert.deepEqual(nodes, [
			{
				number: 310,
				title: "AC",
				url: "https://example.com",
				state: "OPEN",
			},
		]);
		const [call] = readCalls(fakeGh.logFile);
		assert.ok(call.includes("graphql"));
		assert.ok(call.includes("owner=misty-step"));
		assert.ok(call.includes("name=cerberus"));
		assert.ok(call.includes("number=316"));
		assert.ok(call.includes("limit=2"));
	} finally {
		restoreEnv();
		fakeGh.cleanup();
	}
});

test("search_issues scopes queries to the current repo", async () => {
	const tool = await createRegisteredTool();
	const fakeGh = createFakeGh();
	const restoreEnv = withEnv({
		PATH: `${fakeGh.dir}:${process.env.PATH || ""}`,
		GH_LOG_FILE: fakeGh.logFile,
		GH_TOKEN: "token",
		CERBERUS_REPO: "misty-step/cerberus",
		GH_SEARCH_OUTPUT: '{"items":[{"number":1,"title":"Issue"}]}',
	});

	try {
		const result = await tool.execute("call-4", {
			action: "search_issues",
			query: "label:bug state:open",
			limit: 5,
		});
		assert.equal(result.details.items[0].number, 1);
		const [call] = readCalls(fakeGh.logFile);
		assert.ok(call.includes("search/issues"));
		assert.ok(call.includes("q=repo:misty-step/cerberus label:bug state:open"));
		assert.ok(call.includes("per_page=5"));
	} finally {
		restoreEnv();
		fakeGh.cleanup();
	}
});

test("github_read rejects missing envs and invalid semantic inputs", async () => {
	const tool = await createRegisteredTool();
	const fakeGh = createFakeGh();
	const restoreEnv = withEnv({
		PATH: `${fakeGh.dir}:${process.env.PATH || ""}`,
		GH_LOG_FILE: fakeGh.logFile,
		GH_TOKEN: undefined,
		GITHUB_TOKEN: undefined,
		CERBERUS_REPO: undefined,
		CERBERUS_PR_NUMBER: undefined,
	});

	try {
		const missingAuth = await tool.execute("call-5", { action: "get_pr", prNumber: 316 });
		assert.equal(missingAuth.isError, true);
		assert.match(String(missingAuth.details.error), /Missing GH_TOKEN\/GITHUB_TOKEN/);

		process.env.GH_TOKEN = "token";
		const missingRepo = await tool.execute("call-6", { action: "get_pr", prNumber: 316 });
		assert.equal(missingRepo.isError, true);
		assert.match(String(missingRepo.details.error), /Missing CERBERUS_REPO/);

		process.env.CERBERUS_REPO = "misty-step/cerberus";
		const missingPr = await tool.execute("call-7", { action: "get_pr" });
		assert.equal(missingPr.isError, true);
		assert.match(String(missingPr.details.error), /Missing pull request number/);

		const missingIssue = await tool.execute("call-8", { action: "get_issue" });
		assert.equal(missingIssue.isError, true);
		assert.match(String(missingIssue.details.error), /issueNumber is required/);

		const crossRepoSearch = await tool.execute("call-9", {
			action: "search_issues",
			query: "repo:other/repo is:open",
		});
		assert.equal(crossRepoSearch.isError, true);
		assert.match(String(crossRepoSearch.details.error), /must not override repository scope/);
	} finally {
		restoreEnv();
		fakeGh.cleanup();
	}
});

test("github_read surfaces gh transport failures, invalid JSON, and aborts", async () => {
	const tool = await createRegisteredTool();
	const fakeGh = createFakeGh();
	const restoreEnv = withEnv({
		PATH: `${fakeGh.dir}:${process.env.PATH || ""}`,
		GH_LOG_FILE: fakeGh.logFile,
		GH_TOKEN: "token",
		CERBERUS_REPO: "misty-step/cerberus",
	});

	try {
		process.env.GH_EXIT_CODE = "1";
		process.env.GH_STDERR = "boom\n";
		const failed = await tool.execute("call-10", { action: "get_pr", prNumber: 316 });
		assert.equal(failed.isError, true);
		assert.match(String(failed.details.error), /gh command failed: boom/);

		process.env.GH_EXIT_CODE = "0";
		process.env.GH_STDERR = "";
		process.env.GH_PULL_OUTPUT = "{";
		const invalidJson = await tool.execute("call-11", { action: "get_pr", prNumber: 316 });
		assert.equal(invalidJson.isError, true);
		assert.match(String(invalidJson.details.error), /gh returned invalid JSON/);

		process.env.GH_PULL_OUTPUT = '{"number":316}';
		process.env.GH_SLEEP_MS = "5000";
		const controller = new AbortController();
		setTimeout(() => controller.abort(), 50);
		const aborted = await tool.execute("call-12", { action: "get_pr", prNumber: 316 }, controller.signal);
		assert.equal(aborted.isError, true);
		assert.match(String(aborted.details.error), /gh command failed: unknown gh failure/);
	} finally {
		restoreEnv();
		fakeGh.cleanup();
	}
});
