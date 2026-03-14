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

function createWeirdPathDiffFixture() {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "cerberus-repo-read-weird-"));
	const workspaceRoot = path.join(root, "workspace");
	const weirdDir = path.join(workspaceRoot, "docs", "foo b");
	fs.mkdirSync(weirdDir, { recursive: true });
	fs.writeFileSync(path.join(weirdDir, "bar.md"), "odd path\n", "utf8");
	const diffPath = path.join(root, "pr.diff");
	fs.writeFileSync(
		diffPath,
		[
			"diff --git a/docs/foo b/bar.md b/docs/foo b/bar.md",
			"index 1111111..2222222 100644",
			"--- a/docs/foo b/bar.md",
			"+++ b/docs/foo b/bar.md",
			"@@ -1 +1 @@",
			"-before",
			"+after",
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

function createRenameDiffFixture(oldPath = "docs/old.md", newPath = "docs/new.md") {
	const root = fs.mkdtempSync(path.join(os.tmpdir(), "cerberus-repo-read-rename-"));
	const workspaceRoot = path.join(root, "workspace");
	fs.mkdirSync(path.join(workspaceRoot, path.dirname(newPath)), { recursive: true });
	fs.writeFileSync(path.join(workspaceRoot, newPath), "renamed\n", "utf8");
	const diffPath = path.join(root, "pr.diff");
	fs.writeFileSync(
		diffPath,
		[
			`diff --git a/${oldPath} b/${newPath}`,
			"similarity index 100%",
			`rename from ${oldPath}`,
			`rename to ${newPath}`,
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

test("read_file rejects start lines beyond the file length", async () => {
	const tool = await createRegisteredTool();
	const fixture = createReviewRunFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const result = await tool.execute("call-2b", {
			action: "read_file",
			path: "docs/notes.md",
			startLine: 10,
		});
		assert.equal(result.isError, true);
		assert.match(String(result.details.error), /startLine 10 exceeds file length \(4 lines\)/);
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

test("list_changed_files and read_diff handle paths containing b-slash tokens", async () => {
	const tool = await createRegisteredTool();
	const fixture = createWeirdPathDiffFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const listed = await tool.execute("call-3b", { action: "list_changed_files" });
		assert.equal(listed.isError, undefined);
		assert.deepEqual(listed.details.files, [
			{ path: "docs/foo b/bar.md", status: "modified", oldPath: undefined, additions: 1, deletions: 1 },
		]);

		const diff = await tool.execute("call-3c", {
			action: "read_diff",
			path: "docs/foo b/bar.md",
		});
		assert.equal(diff.isError, undefined);
		assert.equal(diff.details.files[0].path, "docs/foo b/bar.md");
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});

test("list_changed_files preserves renamed files", async () => {
	const tool = await createRegisteredTool();
	const fixture = createRenameDiffFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const listed = await tool.execute("call-3d", { action: "list_changed_files" });
		assert.equal(listed.isError, undefined);
		assert.deepEqual(listed.details.files, [
			{ path: "docs/new.md", status: "renamed", oldPath: "docs/old.md", additions: 0, deletions: 0 },
		]);

		const diff = await tool.execute("call-3e", {
			action: "read_diff",
			path: "docs/old.md",
		});
		assert.equal(diff.isError, undefined);
		assert.equal(diff.details.files[0].path, "docs/new.md");
		assert.equal(diff.details.files[0].oldPath, "docs/old.md");
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});

test("list_changed_files preserves renamed files whose paths contain b-slash tokens", async () => {
	const tool = await createRegisteredTool();
	const fixture = createRenameDiffFixture("docs/foo b/old.md", "docs/foo b/new.md");
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const listed = await tool.execute("call-3f", { action: "list_changed_files" });
		assert.equal(listed.isError, undefined);
		assert.deepEqual(listed.details.files, [
			{ path: "docs/foo b/new.md", status: "renamed", oldPath: "docs/foo b/old.md", additions: 0, deletions: 0 },
		]);

		const diff = await tool.execute("call-3g", {
			action: "read_diff",
			path: "docs/foo b/old.md",
		});
		assert.equal(diff.isError, undefined);
		assert.equal(diff.details.files[0].path, "docs/foo b/new.md");
		assert.equal(diff.details.files[0].oldPath, "docs/foo b/old.md");
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
		assert.equal(result.details.truncated, false);
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});

test("search_repo respects pathPrefix scoping", async () => {
	const tool = await createRegisteredTool();
	const fixture = createReviewRunFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const result = await tool.execute("call-4b", {
			action: "search_repo",
			query: "line",
			pathPrefix: "docs",
			limit: 10,
		});
		assert.equal(result.isError, undefined);
		assert.deepEqual(result.details.results, [
			{ path: "docs/notes.md", line: 1, excerpt: "line one" },
			{ path: "docs/notes.md", line: 2, excerpt: "line two" },
			{ path: "docs/notes.md", line: 3, excerpt: "line three" },
		]);
		assert.equal(result.details.truncated, false);
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});

test("read_file rejects endLine values below startLine", async () => {
	const tool = await createRegisteredTool();
	const fixture = createReviewRunFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const result = await tool.execute("call-4c", {
			action: "read_file",
			path: "docs/notes.md",
			startLine: 3,
			endLine: 2,
		});
		assert.equal(result.isError, true);
		assert.match(String(result.details.error), /endLine 2 must be >= startLine 3/);
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

		const outsideDir = path.join(path.dirname(fixture.reviewRunPath), "outside");
		fs.mkdirSync(outsideDir, { recursive: true });
		fs.writeFileSync(path.join(outsideDir, "secret.txt"), "classified\n", "utf8");
		fs.symlinkSync(outsideDir, path.join(path.dirname(fixture.reviewRunPath), "workspace", "escape-dir"));

		const escapedSymlinkFile = await tool.execute("call-7", {
			action: "read_file",
			path: "escape-dir/secret.txt",
		});
		assert.equal(escapedSymlinkFile.isError, true);
		assert.match(String(escapedSymlinkFile.details.error), /path escapes workspace root/);

		const escapedSymlinkSearch = await tool.execute("call-8", {
			action: "search_repo",
			query: "classified",
			pathPrefix: "escape-dir",
		});
		assert.equal(escapedSymlinkSearch.isError, true);
		assert.match(String(escapedSymlinkSearch.details.error), /path escapes workspace root/);
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});

test("search_repo skips nested symlinks and oversized files", async () => {
	const tool = await createRegisteredTool();
	const fixture = createReviewRunFixture();
	const restoreEnv = withEnv({ CERBERUS_REVIEW_RUN: fixture.reviewRunPath });

	try {
		const workspaceRoot = path.join(path.dirname(fixture.reviewRunPath), "workspace");
		const outsideDir = path.join(path.dirname(fixture.reviewRunPath), "outside");
		fs.mkdirSync(outsideDir, { recursive: true });
		fs.writeFileSync(path.join(outsideDir, "secret.txt"), "classified\n", "utf8");
		fs.symlinkSync(path.join(outsideDir, "secret.txt"), path.join(workspaceRoot, "docs", "linked-secret.txt"));
		fs.writeFileSync(
			path.join(workspaceRoot, "docs", "huge.txt"),
			`${"A".repeat(1024 * 1024)} oversized-token\n`,
			"utf8",
		);

		const symlinkResult = await tool.execute("call-9", {
			action: "search_repo",
			query: "classified",
			limit: 10,
		});
		assert.equal(symlinkResult.isError, undefined);
		assert.deepEqual(symlinkResult.details.results, []);

		const largeFileResult = await tool.execute("call-10", {
			action: "search_repo",
			query: "oversized-token",
			limit: 10,
		});
		assert.equal(largeFileResult.isError, undefined);
		assert.deepEqual(largeFileResult.details.results, []);
	} finally {
		restoreEnv();
		fixture.cleanup();
	}
});
