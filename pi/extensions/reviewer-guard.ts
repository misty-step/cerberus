import fs from "node:fs";
import path from "node:path";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const DEFAULT_SYSTEM_PROMPT_FILE = process.env.CERBERUS_TRUSTED_SYSTEM_PROMPT_FILE;
const MAX_STEPS = Number.parseInt(process.env.CERBERUS_MAX_STEPS || "", 10);

const BLOCKED_BASH_PATTERNS: Array<{ re: RegExp; reason: string }> = [
	{ re: /(^|\s)rm\s+-rf\s+\/$/, reason: "Refusing destructive root delete" },
	{ re: /(^|\s)rm\s+-rf\s+--no-preserve-root/, reason: "Refusing destructive root delete" },
	{ re: /(^|\s)git\s+push(\s|$)/, reason: "Refusing remote git push from reviewer runtime" },
	{ re: /(^|\s)git\s+reset\s+--hard(\s|$)/, reason: "Refusing irreversible git reset --hard" },
	{ re: /(^|\s)git\s+clean\s+-f(d|x)?(\s|$)/, reason: "Refusing destructive git clean" },
	{ re: /(^|\s)dd\s+if=\/dev\/(zero|random)/, reason: "Refusing destructive disk write pattern" },
	{ re: /(^|\s)mkfs(\.|\s|$)/, reason: "Refusing filesystem format command" },
	{ re: /(^|\s)shutdown(\s|$)/, reason: "Refusing host shutdown command" },
	{ re: /(^|\s)reboot(\s|$)/, reason: "Refusing host reboot command" },
];

function normalizePath(input: string, cwd: string): string {
	const resolved = path.isAbsolute(input) ? path.resolve(input) : path.resolve(cwd, input);
	return resolved;
}

function isTmpPath(inputPath: string, cwd: string): boolean {
	const resolved = normalizePath(inputPath, cwd);
	const tmpRoot = path.resolve("/tmp");
	return resolved === tmpRoot || resolved.startsWith(`${tmpRoot}${path.sep}`);
}

function readTrustedSystemPrompt(): string | null {
	if (!DEFAULT_SYSTEM_PROMPT_FILE) return null;
	try {
		if (!fs.existsSync(DEFAULT_SYSTEM_PROMPT_FILE)) return null;
		const content = fs.readFileSync(DEFAULT_SYSTEM_PROMPT_FILE, "utf-8").trim();
		return content.length > 0 ? content : null;
	} catch {
		return null;
	}
}

export default function reviewerGuardExtension(pi: ExtensionAPI) {
	pi.on("before_agent_start", async (event, ctx) => {
		const trustedPrompt = readTrustedSystemPrompt();
		if (!trustedPrompt) return undefined;

		const enforcement = `\n\nOUTPUT CONTRACT ENFORCEMENT:\n- You are not done until you emit exactly one final JSON review block in \\`\\`\\`json fences.\n- Keep findings schema-compliant and machine-parseable.\n- If analysis is partial, emit SKIP with explicit summary.`;

		return {
			systemPrompt: `${trustedPrompt}${enforcement}`,
		};
	});

	pi.on("turn_start", async (event, ctx) => {
		if (!Number.isFinite(MAX_STEPS) || MAX_STEPS <= 0) return;
		if (event.turnIndex < MAX_STEPS) return;
		ctx.ui.notify(`Max reviewer steps reached (${MAX_STEPS}); aborting turn loop.`, "warning");
		ctx.abort();
	});

	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName === "write" || event.toolName === "edit") {
			const p = String((event.input as { path?: string }).path ?? "").trim();
			if (!p) {
				return { block: true, reason: "Missing path for file-modifying tool" };
			}
			if (!isTmpPath(p, ctx.cwd)) {
				return {
					block: true,
					reason: `Refusing ${event.toolName} outside /tmp: ${p}`,
				};
			}
		}

		if (event.toolName === "bash") {
			const command = String((event.input as { command?: string }).command ?? "");
			for (const rule of BLOCKED_BASH_PATTERNS) {
				if (rule.re.test(command)) {
					return { block: true, reason: rule.reason };
				}
			}
		}

		return undefined;
	});
}
