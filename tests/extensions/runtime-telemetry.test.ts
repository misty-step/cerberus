import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import runtimeTelemetryExtension, {
	resolveTelemetryFile,
} from "../../pi/extensions/runtime-telemetry.ts";

type Handler = (event: any) => Promise<any> | any;

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

function readTelemetryLines(file: string) {
	const raw = fs.readFileSync(file, "utf-8").trim();
	if (!raw) return [];
	return raw.split("\n").map((line) => JSON.parse(line));
}

test("resolveTelemetryFile uses env override and fallback", () => {
	const previous = process.env.CERBERUS_RUNTIME_TELEMETRY_FILE;
	try {
		delete process.env.CERBERUS_RUNTIME_TELEMETRY_FILE;
		assert.equal(resolveTelemetryFile(), "/tmp/cerberus-pi-runtime.ndjson");

		process.env.CERBERUS_RUNTIME_TELEMETRY_FILE = "/tmp/custom-telemetry.ndjson";
		assert.equal(resolveTelemetryFile(), "/tmp/custom-telemetry.ndjson");
	} finally {
		if (previous === undefined) {
			delete process.env.CERBERUS_RUNTIME_TELEMETRY_FILE;
		} else {
			process.env.CERBERUS_RUNTIME_TELEMETRY_FILE = previous;
		}
	}
});

test("runtime telemetry writes session and event records", async () => {
	const telemetryFile = path.join(
		os.tmpdir(),
		`cerberus-runtime-telemetry-${Date.now()}-${Math.random().toString(36).slice(2)}.ndjson`,
	);
	const previous = process.env.CERBERUS_RUNTIME_TELEMETRY_FILE;
	process.env.CERBERUS_RUNTIME_TELEMETRY_FILE = telemetryFile;

	try {
		const fake = createFakePi();
		runtimeTelemetryExtension(fake.api as any);

		await fake.handlers.get("agent_start")!({});
		await fake.handlers.get("agent_end")!({ messages: [1, 2, 3] });
		await fake.handlers.get("turn_end")!({
			turnIndex: 2,
			toolResults: [1],
			message: { role: "assistant", stopReason: "end_turn" },
		});
		await fake.handlers.get("tool_execution_end")!({ toolName: "read", isError: false });
		await fake.handlers.get("message_end")!({
			message: { role: "assistant", stopReason: "end_turn", errorMessage: "" },
		});
		await fake.handlers.get("message_end")!({
			message: { role: "user", stopReason: null, errorMessage: "" },
		});

		const rows = readTelemetryLines(telemetryFile);
		const events = rows.map((row) => row.event);

		assert.ok(events.includes("session_start"));
		assert.ok(events.includes("agent_start"));
		assert.ok(events.includes("agent_end"));
		assert.ok(events.includes("turn_end"));
		assert.ok(events.includes("tool_execution_end"));
		assert.ok(events.includes("assistant_message_end"));

		const assistantRows = rows.filter((row) => row.event === "assistant_message_end");
		assert.equal(assistantRows.length, 1);
	} finally {
		if (previous === undefined) {
			delete process.env.CERBERUS_RUNTIME_TELEMETRY_FILE;
		} else {
			process.env.CERBERUS_RUNTIME_TELEMETRY_FILE = previous;
		}
		fs.rmSync(telemetryFile, { force: true });
	}
});
