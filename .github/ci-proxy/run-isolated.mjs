import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtempSync, rmdirSync } from "node:fs";
import { createConnection, createServer, isIPv4 } from "node:net";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const invocation = process.argv.slice(2);
if (!invocation.length) throw new Error("Pass a command to run in the isolated network namespace.");

function relay(connect) {
  const connections = new Set();
  const server = createServer((client) => {
    const target = connect();
    for (const socket of [client, target]) {
      connections.add(socket);
      socket.once("close", () => connections.delete(socket));
      socket.once("error", () => {
        client.destroy();
        target.destroy();
      });
    }
    client.pipe(target).pipe(client);
  });
  return {
    server,
    close() {
      for (const socket of connections) socket.destroy();
      server.close();
    },
  };
}

async function run(command, args, env = process.env) {
  const child = spawn(command, args, { env, stdio: "inherit" });
  const [status] = await once(child, "exit");
  process.exitCode = status ?? 1;
}

if (invocation[0] === "--namespace") {
  const [, bridgePath, command, ...args] = invocation;
  const bridge = relay(() => createConnection(bridgePath));
  try {
    bridge.server.listen(0, "127.0.0.1");
    await once(bridge.server, "listening");
    const proxy = `http://127.0.0.1:${bridge.server.address().port}`;
    const env = { ...process.env };
    for (const key of ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]) {
      env[key] = proxy;
    }
    env.NO_PROXY = env.no_proxy = "localhost,127.0.0.1,::1,.localhost";
    const chrome = JSON.parse(env.CHROME_ARGS_EXTRA || "[]");
    env.CHROME_ARGS_EXTRA = JSON.stringify([
      ...chrome.filter((arg) => !arg.startsWith("--proxy-server=")),
      `--proxy-server=${proxy}`,
    ]);
    await run(command, args, env);
  } finally {
    bridge.close();
  }
} else {
  const proxy = new URL(process.env.CI_REPLAY_PROXY || process.env.HTTPS_PROXY || "");
  if (proxy.protocol !== "http:" || !isIPv4(proxy.hostname) || proxy.port !== "3129") {
    throw new Error("Configure the numeric replay-only proxy endpoint on port 3129 first.");
  }
  // Loopback inside a namespace has no route to the runner. Cross it over a
  // Unix socket whose host-side destination is fixed to the replay listener.
  const directory = mkdtempSync("/tmp/ci-network-");
  const bridgePath = join(directory, "proxy.sock");
  const bridge = relay(() => createConnection(Number(proxy.port), proxy.hostname));
  try {
    bridge.server.listen(bridgePath);
    await once(bridge.server, "listening");
    await run("sudo", [
      "--preserve-env", "--", "unshare", "--mount", "--net", "--",
      "bash", "-c",
      `set -e
      ip link set lo up
      # Hide host service sockets that could perform network operations on the test's behalf.
      mount -t tmpfs -o mode=0755 tmpfs /run
      uid=$1; gid=$2; path=$3; home=$4; shift 4
      exec setpriv --reuid "$uid" --regid "$gid" --init-groups --no-new-privs -- \\
        /usr/bin/env "PATH=$path" "HOME=$home" "$@"`,
      "ci-network", String(process.getuid()), String(process.getgid()),
      process.env.PATH, process.env.HOME,
      process.execPath, fileURLToPath(import.meta.url), "--namespace", bridgePath, ...invocation,
    ]);
  } finally {
    bridge.close();
    rmdirSync(directory);
  }
}
