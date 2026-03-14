import fs from "node:fs";
import path from "node:path";

import { StringEnum, Type } from "@mariozechner/pi-ai";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

type ToolParams = {
	action: "list_changed_files" | "read_file" | "read_diff" | "search_repo";
	path?: string;
	pathPrefix?: string;
	query?: string;
	limit?: number;
	startLine?: number;
	endLine?: number;
};

type ReviewRun = {
	diff_file: string;
	workspace_root: string;
};

type ChangedFile = {
	path: string;
	status: "added" | "modified" | "deleted" | "renamed";
	oldPath?: string;
	additions: number;
	deletions: number;
	diff: string;
};

const DEFAULT_FILE_LIMIT = 20;
const DEFAULT_RESULT_LIMIT = 20;
const MAX_FILE_LIMIT = 100;
const MAX_RESULTS_LIMIT = 100;
const MAX_FILE_LINES = 200;
const MAX_DIFF_FILES = 20;
const IGNORED_DIRECTORIES = new Set([
	".git",
	".hg",
	".svn",
	".venv",
	"node_modules",
	"__pycache__",
]);

function normalizeLimit(rawLimit: number | undefined, fallback: number, max: number): number {
	const raw = Number(rawLimit ?? fallback);
	const normalized = Number.isFinite(raw) ? Math.trunc(raw) : fallback;
	return Math.max(1, Math.min(max, normalized));
}

function requireReviewRunPath(): string {
	const reviewRunPath = (process.env.CERBERUS_REVIEW_RUN || "").trim();
	if (!reviewRunPath) {
		throw new Error("Missing CERBERUS_REVIEW_RUN");
	}
	return reviewRunPath;
}

function loadReviewRun(): ReviewRun {
	const reviewRunPath = requireReviewRunPath();
	let raw = "";
	try {
		raw = fs.readFileSync(reviewRunPath, "utf8");
	} catch (error) {
		throw new Error(`Unable to read CERBERUS_REVIEW_RUN: ${String(error)}`);
	}

	let payload: unknown;
	try {
		payload = JSON.parse(raw);
	} catch (error) {
		throw new Error(`Invalid CERBERUS_REVIEW_RUN JSON: ${String(error)}`);
	}

	if (!payload || typeof payload !== "object") {
		throw new Error("Invalid CERBERUS_REVIEW_RUN payload");
	}

	const diffFile = String((payload as Record<string, unknown>).diff_file || "").trim();
	const workspaceRoot = String((payload as Record<string, unknown>).workspace_root || "").trim();
	if (!diffFile || !workspaceRoot) {
		throw new Error("CERBERUS_REVIEW_RUN must include diff_file and workspace_root");
	}

	return {
		diff_file: diffFile,
		workspace_root: workspaceRoot,
	};
}

function requireRelativePath(rawPath: string | undefined, fieldName: string): string {
	const value = (rawPath || "").trim();
	if (!value) {
		throw new Error(`${fieldName} is required`);
	}
	if (path.isAbsolute(value)) {
		throw new Error(`${fieldName} must be repository-relative`);
	}
	return value;
}

function pathEscapesRoot(rootPath: string, candidatePath: string): boolean {
	const relative = path.relative(rootPath, candidatePath);
	return relative === ".." || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative);
}

function resolveWorkspacePath(workspaceRoot: string, relativePath: string): string {
	const resolvedRoot = path.resolve(workspaceRoot);
	const candidate = path.resolve(resolvedRoot, relativePath);
	if (pathEscapesRoot(resolvedRoot, candidate)) {
		throw new Error("path escapes workspace root");
	}

	const realRoot = fs.realpathSync(resolvedRoot);
	const realCandidate = fs.realpathSync(candidate);
	if (pathEscapesRoot(realRoot, realCandidate)) {
		throw new Error("path escapes workspace root");
	}
	return realCandidate;
}

function parseHeaderPaths(header: string): { oldPath: string; newPath: string } | null {
	const prefix = "diff --git a/";
	if (!header.startsWith(prefix)) {
		return null;
	}
	const rest = header.slice(prefix.length);
	let offset = 0;
	while (true) {
		const separatorIndex = rest.indexOf(" b/", offset);
		if (separatorIndex === -1) {
			return null;
		}
		const oldPath = rest.slice(0, separatorIndex);
		const newPath = rest.slice(separatorIndex + 3);
		if (oldPath === newPath) {
			return { oldPath, newPath };
		}
		offset = separatorIndex + 1;
	}
}

function parseChangedFiles(diffText: string): ChangedFile[] {
	const files: ChangedFile[] = [];
	const chunks = diffText.split(/^diff --git /m).filter(Boolean);

	for (const chunk of chunks) {
		const text = `diff --git ${chunk}`;
		const lines = text.split("\n");
		const header = lines[0] || "";
		const headerPaths = parseHeaderPaths(header);
		if (!headerPaths) {
			continue;
		}

		let oldPath = headerPaths.oldPath;
		let newPath = headerPaths.newPath;
		let status: ChangedFile["status"] = "modified";
		let additions = 0;
		let deletions = 0;

		for (const line of lines.slice(1)) {
			if (line.startsWith("new file mode ")) {
				status = "added";
			} else if (line.startsWith("deleted file mode ")) {
				status = "deleted";
			} else if (line.startsWith("rename from ")) {
				status = "renamed";
				oldPath = line.slice("rename from ".length).trim();
			} else if (line.startsWith("rename to ")) {
				newPath = line.slice("rename to ".length).trim();
			} else if (line.startsWith("--- a/")) {
				oldPath = line.slice("--- a/".length).trim();
			} else if (line.startsWith("+++ b/")) {
				newPath = line.slice("+++ b/".length).trim();
			} else if (line.startsWith("+") && !line.startsWith("+++")) {
				additions += 1;
			} else if (line.startsWith("-") && !line.startsWith("---")) {
				deletions += 1;
			}
		}

		files.push({
			path: status === "deleted" ? oldPath : newPath,
			status,
			oldPath: status === "renamed" ? oldPath : undefined,
			additions,
			deletions,
			diff: text.trimEnd(),
		});
	}

	return files;
}

function readTextFile(filePath: string): string {
	try {
		return fs.readFileSync(filePath, "utf8");
	} catch (error) {
		throw new Error(`Unable to read file: ${String(error)}`);
	}
}

function buildFileSlice(
	filePath: string,
	relativePath: string,
	startLineRaw: number | undefined,
	endLineRaw: number | undefined,
) {
	const text = readTextFile(filePath);
	const lines = text.split("\n");
	const startLine = Math.max(1, Math.trunc(Number(startLineRaw ?? 1)));
	if (startLine > lines.length) {
		throw new Error(`startLine ${startLine} exceeds file length (${lines.length} lines)`);
	}
	const requestedEndLine = Math.trunc(Number(endLineRaw ?? startLine + MAX_FILE_LINES - 1));
	const endLine = Math.min(lines.length, Math.max(startLine, requestedEndLine));
	if (endLine - startLine + 1 > MAX_FILE_LINES) {
		throw new Error(`read_file may return at most ${MAX_FILE_LINES} lines`);
	}

	return {
		path: relativePath,
		startLine,
		endLine,
		totalLines: lines.length,
		content: lines.slice(startLine - 1, endLine).join("\n"),
	};
}

function buildDiffSlice(files: ChangedFile[], relativePath: string | undefined, rawLimit: number | undefined) {
	if (relativePath) {
		const file = files.find((entry) => entry.path === relativePath || entry.oldPath === relativePath);
		if (!file) {
			throw new Error(`Diff for ${relativePath} not found`);
		}
		return { files: [file], truncated: false };
	}

	const limit = normalizeLimit(rawLimit, DEFAULT_FILE_LIMIT, MAX_DIFF_FILES);
	return {
		files: files.slice(0, limit),
		truncated: files.length > limit,
	};
}

function shouldIgnoreEntry(name: string): boolean {
	return IGNORED_DIRECTORIES.has(name);
}

function searchRepo(
	rootPath: string,
	query: string,
	limit: number,
	results: Array<{ path: string; line: number; excerpt: string }>,
): void {
	const entries = fs.readdirSync(rootPath, { withFileTypes: true });
	for (const entry of entries) {
		if (results.length >= limit) {
			return;
		}
		if (entry.isDirectory()) {
			if (shouldIgnoreEntry(entry.name)) {
				continue;
			}
			searchRepo(path.join(rootPath, entry.name), query, limit, results);
			continue;
		}
		if (!entry.isFile()) {
			continue;
		}
		const absolutePath = path.join(rootPath, entry.name);
		let text = "";
		try {
			text = fs.readFileSync(absolutePath, "utf8");
		} catch {
			continue;
		}
		if (text.includes("\u0000")) {
			continue;
		}
		const lines = text.split("\n");
		for (let index = 0; index < lines.length; index += 1) {
			if (!lines[index].includes(query)) {
				continue;
			}
			results.push({
				path: absolutePath,
				line: index + 1,
				excerpt: lines[index],
			});
			if (results.length >= limit) {
				return;
			}
		}
	}
}

function repoRelativePath(workspaceRoot: string, absolutePath: string): string {
	const realRoot = fs.realpathSync(path.resolve(workspaceRoot));
	const realPath = fs.realpathSync(absolutePath);
	return path.relative(realRoot, realPath).split(path.sep).join("/");
}

export default function repoReadExtension(pi: ExtensionAPI) {
	pi.registerTool({
		name: "repo_read",
		label: "Repo Read",
		description: "Read-only repo context fetch (changed files, file slices, diff slices, repo search).",
		promptSnippet: "Fetch bounded local review context from the review-run contract and checked-out workspace.",
		promptGuidelines: [
			"Use this tool to inspect changed files, read file slices, read diff slices, and search the repo.",
			"Keep reads bounded with path and line limits.",
			"Prefer repo_read for local context and github_read for GitHub discussion context.",
		],
		parameters: Type.Object({
			action: StringEnum(["list_changed_files", "read_file", "read_diff", "search_repo"] as const),
			path: Type.Optional(Type.String()),
			pathPrefix: Type.Optional(Type.String()),
			query: Type.Optional(Type.String()),
			limit: Type.Optional(Type.Number({ minimum: 1, maximum: 100 })),
			startLine: Type.Optional(Type.Number({ minimum: 1 })),
			endLine: Type.Optional(Type.Number({ minimum: 1 })),
		}),
		async execute(_toolCallId, rawParams) {
			try {
				const params = rawParams as ToolParams;
				const reviewRun = loadReviewRun();
				const changedFiles = parseChangedFiles(readTextFile(reviewRun.diff_file));

				if (params.action === "list_changed_files") {
					const limit = normalizeLimit(params.limit, DEFAULT_FILE_LIMIT, MAX_FILE_LIMIT);
					const payload = {
						files: changedFiles.slice(0, limit).map(({ diff, ...rest }) => rest),
						truncated: changedFiles.length > limit,
					};
					return {
						content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
						details: payload,
					};
				}

				if (params.action === "read_file") {
					const relativePath = requireRelativePath(params.path, "path");
					const absolutePath = resolveWorkspacePath(reviewRun.workspace_root, relativePath);
					const payload = buildFileSlice(absolutePath, relativePath, params.startLine, params.endLine);
					return {
						content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
						details: payload,
					};
				}

				if (params.action === "read_diff") {
					const relativePath = params.path ? requireRelativePath(params.path, "path") : undefined;
					const payload = buildDiffSlice(changedFiles, relativePath, params.limit);
					return {
						content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
						details: payload,
					};
				}

				if (params.action === "search_repo") {
					const query = (params.query || "").trim();
					if (!query) {
						throw new Error("query is required for search_repo");
					}
					const limit = normalizeLimit(params.limit, DEFAULT_RESULT_LIMIT, MAX_RESULTS_LIMIT);
					const searchRoot = params.pathPrefix
						? resolveWorkspacePath(
								reviewRun.workspace_root,
					requireRelativePath(params.pathPrefix, "pathPrefix"),
								)
							: path.resolve(reviewRun.workspace_root);
						const results: Array<{ path: string; line: number; excerpt: string }> = [];
						searchRepo(searchRoot, query, limit + 1, results);
						const truncated = results.length > limit;
						const payload = {
							results: results.slice(0, limit).map((result) => ({
								path: repoRelativePath(reviewRun.workspace_root, result.path),
								line: result.line,
								excerpt: result.excerpt,
							})),
							truncated,
						};
					return {
						content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
						details: payload,
					};
				}

				throw new Error(`Unsupported action: ${params.action}`);
			} catch (error) {
				return {
					content: [{ type: "text", text: `repo_read error: ${String(error)}` }],
					details: { error: String(error) },
					isError: true,
				};
			}
		},
	});
}
