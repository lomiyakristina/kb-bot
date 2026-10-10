#!/usr/bin/env node
import { mkdir, readdir, writeFile, readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { createConnection } from "node:net";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const OUT = join(ROOT, "png");
const PORT = 8765;
const DEBUG_PORT = 9222;
const W = 1080;
const H = 1350;
const CHROME = process.env.CHROME || "google-chrome";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".ttf": "font/ttf",
  ".jpg": "image/jpeg",
  ".png": "image/png",
};

function serve() {
  return new Promise((resolve) => {
    const server = createServer(async (req, res) => {
      try {
        let url = decodeURIComponent((req.url || "/").split("?")[0]);
        if (url === "/") url = "/index.html";
        const path = join(ROOT, url.replace(/^\//, ""));
        if (!path.startsWith(ROOT)) {
          res.writeHead(403); res.end(); return;
        }
        const data = await readFile(path);
        res.writeHead(200, { "Content-Type": MIME[extname(path)] || "application/octet-stream" });
        res.end(data);
      } catch {
        res.writeHead(404); res.end("not found");
      }
    });
    server.listen(PORT, "127.0.0.1", () => resolve(server));
  });
}

async function waitPort(port, ms = 15000) {
  const start = Date.now();
  while (Date.now() - start < ms) {
    const ok = await new Promise((resolve) => {
      const s = createConnection({ host: "127.0.0.1", port }, () => { s.end(); resolve(true); });
      s.on("error", () => resolve(false));
    });
    if (ok) return;
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`port ${port} not open`);
}

async function cdp(wsUrl, method, params = {}) {
  const WebSocket = (await import("ws")).default;
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const id = 1;
    const t = setTimeout(() => { ws.close(); reject(new Error(`timeout ${method}`)); }, 30000);
    ws.on("open", () => ws.send(JSON.stringify({ id, method, params })));
    ws.on("message", (raw) => {
      const msg = JSON.parse(raw.toString());
      if (msg.id === id) {
        clearTimeout(t);
        ws.close();
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    });
    ws.on("error", reject);
  });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const server = await serve();

  // Ensure bootstrap is linked
  let index = await readFile(join(ROOT, "index.html"), "utf8");
  if (!index.includes("_export-boot.js")) {
    index = index.replace("</body>", '  <script src="_export-boot.js"></script>\n</body>');
    await writeFile(join(ROOT, "index.html"), index);
  }

  const data = await readFile(join(ROOT, "menu-data.js"), "utf8");
  const ids = [...data.matchAll(/^\s*id:\s*"([^"]+)"/gm)].map((m) => m[1]);
  const slideIds = [];
  for (const id of ids) if (!slideIds.includes(id)) slideIds.push(id);

  const userData = `/tmp/chrome-kb-menu-${process.pid}`;
  const chrome = spawn(CHROME, [
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${userData}`,
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    `--window-size=${W},${H}`,
    "about:blank",
  ], { stdio: ["ignore", "pipe", "pipe"] });

  let chromeErr = "";
  chrome.stderr.on("data", (d) => { chromeErr += d.toString(); });

  try {
    await waitPort(DEBUG_PORT);
    const ver = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/version`).then((r) => r.json());
    const browserWs = ver.webSocketDebuggerUrl;

    // Create one page target
    const { targetId } = await cdp(browserWs, "Target.createTarget", { url: "about:blank" });
    const targets = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`).then((r) => r.json());
    const page = targets.find((t) => t.id === targetId) || targets.find((t) => t.type === "page");
    if (!page) throw new Error("no page target: " + chromeErr);
    const pageWs = page.webSocketDebuggerUrl;

    // Use a persistent websocket for page
    const WebSocket = (await import("ws")).default;
    const ws = new WebSocket(pageWs);
    await new Promise((res, rej) => { ws.on("open", res); ws.on("error", rej); });
    let nextId = 1;
    const pending = new Map();
    ws.on("message", (raw) => {
      const msg = JSON.parse(raw.toString());
      if (msg.id && pending.has(msg.id)) {
        const { resolve, reject } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    });
    function send(method, params = {}) {
      const id = nextId++;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params }));
        setTimeout(() => {
          if (pending.has(id)) {
            pending.delete(id);
            reject(new Error(`timeout ${method}`));
          }
        }, 45000);
      });
    }

    await send("Page.enable");
    await send("Runtime.enable");
    await send("Emulation.setDeviceMetricsOverride", {
      width: W, height: H, deviceScaleFactor: 1, mobile: false,
    });

    console.log(`Exporting ${slideIds.length} slides…`);
    for (let i = 0; i < slideIds.length; i++) {
      const id = slideIds[i];
      const name = `${String(i + 1).padStart(2, "0")}-${id}.png`;
      const out = join(OUT, name);
      process.stdout.write(`  ${name}… `);
      const url = `http://127.0.0.1:${PORT}/index.html?export=${encodeURIComponent(id)}`;
      await send("Page.navigate", { url });
      // wait for READY title / fonts
      for (let t = 0; t < 60; t++) {
        const { result } = await send("Runtime.evaluate", { expression: "document.title", returnByValue: true });
        if (String(result.value || "").startsWith("READY:")) break;
        await new Promise((r) => setTimeout(r, 100));
      }
      await new Promise((r) => setTimeout(r, 250));
      const shot = await send("Page.captureScreenshot", {
        format: "png",
        fromSurface: true,
        clip: { x: 0, y: 0, width: W, height: H, scale: 1 },
      });
      await writeFile(out, Buffer.from(shot.data, "base64"));
      console.log("ok");
    }

    ws.close();
  } finally {
    chrome.kill("SIGKILL");
    server.close();
  }

  const files = (await readdir(OUT)).filter((f) => f.endsWith(".png")).sort();
  console.log(`Done: ${files.length} files in png/`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
