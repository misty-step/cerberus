/**
 * Transform function for Cerberus eval outputs.
 * Extracts and normalizes JSON verdict blocks from LLM responses.
 */
module.exports = function (output, vars) {
  const normalize = (value) => {
    if (!value || typeof value !== 'object') {
      return {
        verdict: 'SKIP',
        summary: 'Could not parse model output',
        findings: [],
      };
    }

    if (typeof value.verdict === 'string') {
      const normalized = value.verdict.trim().toUpperCase();
      if (
        normalized === 'PASS' ||
        normalized === 'FAIL' ||
        normalized === 'SKIP'
      ) {
        value.verdict = normalized;
      }
    }

    if (!Array.isArray(value.findings)) {
      value.findings = [];
    }

    return value;
  };

  const parseJson = (text) => {
    try {
      return normalize(JSON.parse(text));
    } catch (e) {
      return null;
    }
  };

  // 1. Try direct JSON parse
  const direct = parseJson(output);
  if (direct) return direct;

  // 2. Try fenced JSON blocks (```json ... ```)
  const fences = [...output.matchAll(/```json\s*([\s\S]*?)\s*```/g)];
  for (let i = fences.length - 1; i >= 0; i--) {
    const parsed = parseJson(fences[i][1]);
    if (parsed) return parsed;
  }

  // 3. Try finding anything that looks like a JSON object
  const n = output.match(/\{[\s\S]*\}/);
  if (n) {
    const parsed = parseJson(n[0]);
    if (parsed) return parsed;
  }

  // 4. Fallback to SKIP
  return {
    verdict: 'SKIP',
    summary: 'Could not parse model output',
    findings: [],
  };
};
