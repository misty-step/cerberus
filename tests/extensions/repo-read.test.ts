import assert from "node:assert/strict";
import fs from "node:fs";
import Module from "node:module";
import os from "node:os";
import path from "node:path";
import test from "node:test";

type RegisteredTool = {
	execute: (toolCallId: string, rawParams: unknown, signal?: AbortSignal) => Promise<any>;
};

let repoReadExtensionPromise: Promise<(pi: any) => void> | undefined;

async function loadRepoReadExtension(): Promise<(pi: any) => void> {
	if (!repoReadExtensionPromise) {
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
};
`,
			"utf8",
		);
		fs.writeFileSync(path.join(agentDir, "index.js"), "module.exports = {};\n", "utf8");
		process.env.NODE_PATH = process.env.NODE_PATH
			? `${stubRoot}${path.delimiter}${process.env.NODE_PATH}`
			: stubRoot;
		(Module as any)._initPaths();
		repoReadExtensionPromise = import("../../pi/extensions/repo-read.ts").then((mod) => mod.default);
	}
	return repoReadExtensionPromise;
}

async function createRegisteredTool(): Promise<RegisteredTool> {
	let tool: RegisteredTool | undefined;
	const repoReadExtension = await loadRepoReadExtension();
	repoReadExtension({
		registerTool(definition: RegisteredTool) {
			tool = definition;
		},
	} as any);
	assert.ok(tool, "repo_read should register a tool");
	return tool;
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

function createReviewRunFixture() {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "cerberus-repo-read-"));
	const workspaceRoot = path.join(root, "workspace");
	fs.mkdirSync(workspaceRoot, { recursive: true });
	fs.mkdirSync(path.join(workspaceRoot, "scripts"), { recursive: true });
	fs.mkdirSync(path.join(workspaceRoot, "docs"), { recursive: true });
	fs.writeFileSync(
		path.join(workspaceRoot, "scripts", "run-reviewer.py"),
		["def review():", "    return 'guard'", "    # guard rail", ""].join("\n"),
		"utf8",
	);
	fs.writeFileSync(
		path.join(workspaceRoot, "docs", "notes.md"),
		["line one", "line two", "line three", ""].join("\n"),
		"utf8",
	);
	const diffPath = path.join(root, "pr.diff");
	fs.writeFileSync(
		diffPath,
		[
			"diff --git a/scripts/run-reviewer.py b/scripts/run-reviewer.py",
			"index 1111111..2222222 100644",
			"--- a/scripts/run-reviewer.py",
			"+++ b/scripts/run-reviewer.py",
			"@@ -1 +1,2 @@",
			" def review():",
			"+    return 'guard'",
			"diff --git a/docs/notes.md b/docs/notes.md",
			"new file mode 100644",
			"--- /dev/null",
			"+++ b/docs/notes.md",
			"@@ -0,0 +1,2 @@",
			"+line one",
			"+line two",
			"",
		].join("\n"),
		"utf8",
	);
	const reviewRunPath = path.join(root, "review-run.json");
	fs.writeFileSync(
		reviewRunPath,
		JSON.stringify(
			{
				diff_file: diffPath,
				workspace_root: workspaceRoot,
			},
			null,
			2,
		),
		"utf8",
	);
	return {
		reviewRunPath,
		cleanup() {
			fs.rmSync(root, { recursive: true, force: true });
		},
	};
}

test("list_changed_files returns parsed diff metadata", async () => {
	const tool = await createRegisteredTool();
	const fixture = createReviewRunFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const result = await tool.execute("call-1", { action: "list_changed_files" });
		assert.equal(result.isError, undefined);
		assert.deepEqual(result.details.files, [
			{ path: "scripts/run-reviewer.py", status: "modified", oldPath: undefined, additions: 1, deletions: 0 },
			{ path: "docs/notes.md", status: "added", oldPath: undefined, additions: 2, deletions: 0 },
		]);
		assert.equal(result.details.truncated, false);
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});

test("read_file returns bounded file slices", async () => {
	const tool = await createRegisteredTool();
	const fixture = createReviewRunFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const result = await tool.execute("call-2", {
			action: "read_file",
			path: "docs/notes.md",
			startLine: 2,
			endLine: 3,
		});
		assert.equal(result.isError, undefined);
		assert.deepEqual(result.details, {
			path: "docs/notes.md",
			startLine: 2,
			endLine: 3,
			totalLines: 4,
			content: "line two\nline three",
		});
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});

test("read_diff can filter to one file", async () => {
	const tool = await createRegisteredTool();
	const fixture = createReviewRunFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const result = await tool.execute("call-3", {
			action: "read_diff",
			path: "docs/notes.md",
		});
		assert.equal(result.isError, undefined);
		assert.equal(result.details.files.length, 1);
		assert.equal(result.details.files[0].path, "docs/notes.md");
		assert.match(result.details.files[0].diff, /new file mode 100644/);
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});

test("search_repo scopes hits to the workspace", async () => {
	const tool = await createRegisteredTool();
	const fixture = createReviewRunFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const result = await tool.execute("call-4", {
			action: "search_repo",
			query: "guard",
			limit: 5,
		});
		assert.equal(result.isError, undefined);
		assert.deepEqual(result.details.results, [
			{
				path: "scripts/run-reviewer.py",
				line: 2,
				excerpt: "    return 'guard'",
			},
			{
				path: "scripts/run-reviewer.py",
				line: 3,
				excerpt: "    # guard rail",
			},
		]);
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});

test("repo_read rejects missing envs and escaping paths", async () => {
	const tool = await createRegisteredTool();

	const missing = await tool.execute("call-5", { action: "list_changed_files" });
	assert.equal(missing.isError, true);
	assert.match(String(missing.details.error), /Missing CERBERUS_REVIEW_RUN/);

	const fixture = createReviewRunFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });
	try {
		const escaped = await tool.execute("call-6", {
			action: "read_file",
			path: "../secret.txt",
		});
		assert.equal(escaped.isError, true);
		assert.match(String(escaped.details.error), /path escapes workspace root/);
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});
