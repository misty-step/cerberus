import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import reviewerGuardExtension, {
	BLOCKED_BASH_PATTERNS,
	isTmpPath,
} from "../../pi/extensions/reviewer-guard.ts";

type Handler = (event: any, ctx: any) => Promise<any> | any;

function createFakePi() {
	const handlers = new Map<string, Handler>();
	return {
		handlers,
		api: {
			on(eventName: string, handler: Handler) {
				handlers.set(eventName, handler);
			},
		},
	};
}

test("git clean rule blocks -fdx and variants", () => {
	const rule = BLOCKED_BASH_PATTERNS.find((entry) => entry.reason.includes("git clean"));
	assert.ok(rule, "git clean rule should exist");
	assert.equal(rule.re.test("git clean -f"), true);
	assert.equal(rule.re.test("git clean -fd"), true);
	assert.equal(rule.re.test("git clean -fx"), true);
	assert.equal(rule.re.test("git clean -fdx"), true);
	assert.equal(rule.re.test("git clean -n"), false);
});

test("isTmpPath allows regular /tmp path", () => {
	assert.equal(isTmpPath("/tmp/cerberus-safe-file.txt", process.cwd()), true);
});

test("isTmpPath blocks symlink escape from /tmp", () => {
	const outsideRoot = fs.mkdtempSync(path.join(process.cwd(), ".guard-outside-"));
	const linkPath = path.join(
		"/tmp",
		`cerberus-guard-link-${Date.now()}-${Math.random().toString(36).slice(2)}`,
	);

	try {
		fs.symlinkSync(outsideRoot, linkPath);
		const escaped = path.join(linkPath, "escaped.txt");
		assert.equal(isTmpPath(escaped, process.cwd()), false);
	} finally {
		fs.rmSync(linkPath, { force: true, recursive: true });
		fs.rmSync(outsideRoot, { force: true, recursive: true });
	}
});

test("tool_call blocks write outside /tmp", async () => {
	const fake = createFakePi();
	reviewerGuardExtension(fake.api as any);

	const toolCall = fake.handlers.get("tool_call");
	assert.ok(toolCall, "tool_call handler should be registered");

	const blocked = await toolCall!(
		{ toolName: "write", input: { path: "/etc/passwd" } },
		{ cwd: process.cwd(), ui: { notify() {} }, abort() {} },
	);

	assert.equal(blocked.block, true);
	assert.match(blocked.reason, /outside \/tmp/);
});

test("tool_call blocks destructive bash command", async () => {
	const fake = createFakePi();
	reviewerGuardExtension(fake.api as any);

	const toolCall = fake.handlers.get("tool_call");
	assert.ok(toolCall, "tool_call handler should be registered");

	const blocked = await toolCall!(
		{ toolName: "bash", input: { command: "git clean -fdx" } },
		{ cwd: process.cwd(), ui: { notify() {} }, abort() {} },
	);

	assert.equal(blocked.block, true);
	assert.match(blocked.reason, /git clean/i);

	const allowed = await toolCall!(
		{ toolName: "bash", input: { command: "echo hello" } },
		{ cwd: process.cwd(), ui: { notify() {} }, abort() {} },
	);
	assert.equal(allowed, undefined);
});

test("regex rules block case and shell-separator bypass forms", () => {
	const pushRule = BLOCKED_BASH_PATTERNS.find((entry) => entry.reason.includes("git push"));
	const rmRule = BLOCKED_BASH_PATTERNS.find((entry) => entry.reason.includes("root delete"));
	assert.ok(pushRule);
	assert.ok(rmRule);

	assert.equal(pushRule.re.test("(GIT PUSH)"), true);
	assert.equal(pushRule.re.test("echo ok; git push; echo done"), true);
	assert.equal(rmRule.re.test("rm -rf / "), true);
	assert.equal(rmRule.re.test("rm -rf /;"), true);
});

test("tool_call blocks network egress commands", async () => {
	const fake = createFakePi();
	reviewerGuardExtension(fake.api as any);

	const toolCall = fake.handlers.get("tool_call");
	assert.ok(toolCall, "tool_call handler should be registered");

	const curlBlocked = await toolCall!(
		{ toolName: "bash", input: { command: "curl https://example.com" } },
		{ cwd: process.cwd(), ui: { notify() {} }, abort() {} },
	);
	assert.equal(curlBlocked.block, true);
	assert.match(curlBlocked.reason, /network egress/i);

	const tcpBlocked = await toolCall!(
		{ toolName: "bash", input: { command: "echo hi > /dev/tcp/1.2.3.4/80" } },
		{ cwd: process.cwd(), ui: { notify() {} }, abort() {} },
	);
	assert.equal(tcpBlocked.block, true);
	assert.match(tcpBlocked.reason, /dev\/tcp/i);
});
