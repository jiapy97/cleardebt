import { spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";

const source = process.env.CLEARDEBT_WORK || "/work";
const hostRoot = process.env.CLEARDEBT_HOST_WORK || source;
const job = "/tmp/cleardebt-job";
const modules = "/opt/cleardebt/node_modules";

if (await online()) {
  process.stderr.write("沙箱还能上网，测试没有跑。\n");
  process.exit(1);
}

fs.rmSync(job, { recursive: true, force: true });
fs.mkdirSync(job, { recursive: true });
copyProject(source, job);
fs.symlinkSync(modules, path.join(job, "node_modules"));

const test = spawnSync("npm", ["test"], {
  cwd: job,
  encoding: "utf8",
  env: { ...process.env, CI: "1", NO_UPDATE_NOTIFIER: "1" },
});
process.stdout.write(test.stdout || "");
process.stderr.write(test.stderr || "");
if (test.status !== 0) {
  process.exit(test.status || 1);
}

const coverageFile = path.join(job, "coverage", "coverage-final.json");
if (!fs.existsSync(coverageFile)) {
  process.stderr.write("覆盖率结果没有写出来。\n");
  process.exit(1);
}
const coverage = JSON.parse(fs.readFileSync(coverageFile, "utf8"));
const rewritten = {};
for (const [key, value] of Object.entries(coverage)) {
  const nextKey = rewrite(key);
  if (value && typeof value.path === "string") {
    value.path = rewrite(value.path);
  }
  rewritten[nextKey] = value;
}
fs.mkdirSync(path.join(source, "coverage"), { recursive: true });
fs.writeFileSync(path.join(source, "coverage", "coverage-final.json"), JSON.stringify(rewritten));

function rewrite(value) {
  if (value === job) {
    return hostRoot;
  }
  const prefix = `${job}/`;
  if (value.startsWith(prefix)) {
    return hostRoot + value.slice(job.length);
  }
  return value;
}

function copyProject(from, to) {
  for (const entry of fs.readdirSync(from, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === "coverage" || entry.name === ".scannerwork" || entry.name === ".git") {
      continue;
    }
    const src = path.join(from, entry.name);
    const dest = path.join(to, entry.name);
    if (entry.isDirectory()) {
      fs.mkdirSync(dest, { recursive: true });
      copyProject(src, dest);
    } else if (entry.isFile()) {
      fs.copyFileSync(src, dest);
    }
  }
}

function online() {
  return Promise.all([connect("1.1.1.1", 443), connect("8.8.8.8", 53)]).then((results) => results.some(Boolean));
}

function connect(host, port) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    const finish = (value) => {
      socket.destroy();
      resolve(value);
    };
    socket.setTimeout(1000);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}
