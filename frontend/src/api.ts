export async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = "Unexpected server response.";
    }
    throw new Error(typeof detail === "string" ? detail : "Invalid request.");
  }
  return response.json() as Promise<T>;
}
export const terminal = (status: string) =>
  ["completed", "error", "cancelled"].includes(status);
export const effortLabels: Record<string, string> = {
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Very high",
  max: "Maximum",
  ultra: "Ultra",
};
export const settingsLabel = (s: { model: string; reasoning_effort: string }) =>
  `${s.model} · reasoning ${effortLabels[s.reasoning_effort] || s.reasoning_effort} · autonomous research`;
