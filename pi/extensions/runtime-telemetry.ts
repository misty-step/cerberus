import fs from "node:fs";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const telemetryFile = process.env.CERBERUS_RUNTIME_TELEMETRY_FILE || "/tmp/cerberus-pi-runtime.ndjson";

function emit(eventType: string, payload: Record<string, unknown>) {
	const record = {
		ts: new Date().toISOString(),
		event: eventType,
		...payload,
	};
	try {
		fs.appendFileSync(telemetryFile, `${JSON.stringify(record)}\n`, "utf-8");
	} catch {
		// Telemetry is best-effort; never block reviewer flow.
	}
}

export default function runtimeTelemetryExtension(pi: ExtensionAPI) {
	emit("session_start", { cwd: process.cwd(), telemetryFile });

	pi.on("agent_start", async () => {
		emit("agent_start", {});
	});

	pi.on("agent_end", async (event) => {
		emit("agent_end", {
			messageCount: event.messages.length,
		});
	});

	pi.on("turn_end", async (event) => {
		emit("turn_end", {
			turnIndex: event.turnIndex,
			toolResults: event.toolResults.length,
			stopReason:
				event.message.role === "assistant"
					? (event.message.stopReason ?? null)
					: null,
		});
	});

	pi.on("tool_execution_end", async (event) => {
		emit("tool_execution_end", {
			toolName: event.toolName,
			isError: event.isError,
		});
	});

	pi.on("message_end", async (event) => {
		if (event.message.role !== "assistant") return;
		emit("assistant_message_end", {
			stopReason: event.message.stopReason ?? null,
			hasErrorMessage: !!event.message.errorMessage,
		});
	});
}
