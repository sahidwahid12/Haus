// ssh-bridge.js — bridges WebSocket connections to a ROOT SSH session on the
// local runtime (localhost:22). This is the dedicated root-access channel that
// is separate from the per-user non-root app shell.
//
// Run inside the backend runtime (where sshd + the root key live):
//   npm install && node ssh-bridge.js
//
// Then point a WebSocket client (e.g. the Haus app's root terminal) at
//   ws://<host>:<SSH_BRIDGE_PORT>
// and you get a root shell on the runtime, from which you can `docker` into any
// sandbox container.
const WebSocket = require("ws");
const { Client } = require("ssh2");
const fs = require("fs");

const PORT = parseInt(process.env.SSH_BRIDGE_PORT || "20129", 10);
const KEY = process.env.WS_ROOT_SSH_KEY || "/var/lib/webshell/root_ssh_key";

const wss = new WebSocket.Server({ port: PORT });
wss.on("connection", (ws) => {
  const conn = new Client();
  conn.on("ready", () => {
    conn.shell((err, stream) => {
      if (err) {
        ws.close();
        return;
      }
      ws.on("message", (m) => stream.write(m));
      stream.on("data", (d) => ws.send(d));
      stream.stderr.on("data", (d) => ws.send(d));
      ws.on("close", () => conn.end());
    });
  }).connect({
    host: "127.0.0.1",
    port: 22,
    username: "root",
    privateKey: fs.readFileSync(KEY),
  });
  conn.on("error", () => ws.close());
});
console.log("[haus] ssh-bridge listening on ws://0.0.0.0:%d", PORT);
