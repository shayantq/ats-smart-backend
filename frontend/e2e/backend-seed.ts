import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const E2E_DIR = path.dirname(fileURLToPath(import.meta.url));

/** ریشه‌ی ریپو (جایی که docker-compose.yml هست) — پوشه‌ی بالای frontend */
const REPO_ROOT = path.resolve(E2E_DIR, "..", "..");
const SEED_SCRIPT = readFileSync(path.join(E2E_DIR, "seed_e2e_data.py"), "utf-8");

/**
 * اسکریپت پایتون seed_e2e_data.py را داخل کانتینر بک‌اند (همان کد و همان دیتابیس سیستم در
 * حال اجرا) اجرا می‌کند و خروجی JSON آن را برمی‌گرداند.
 */
export function runBackendSeed<T>(command: "seed" | "cleanup", runId: string): T {
  const output = execFileSync(
    "docker",
    ["compose", "exec", "-T", "backend_api", "python", "-", command, runId],
    { cwd: REPO_ROOT, input: SEED_SCRIPT, encoding: "utf-8" },
  );
  const lastLine = output.trim().split("\n").pop() ?? "{}";
  return JSON.parse(lastLine) as T;
}
