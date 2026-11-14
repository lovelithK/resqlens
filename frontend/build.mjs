// ResQLens frontend tooling (esbuild).
//   node build.mjs                 production bundle -> dist/ (served by the backend on :8000)
//   node build.mjs --dev           dev server on http://localhost:5173 with live reload;
//                                  /api, /docs and /openapi.json are proxied to the backend
//                                  (--host <h> --port <p> --api <url> to override)
//   node build.mjs --watch         rebuild dist/ on every change (no server)
import * as esbuild from "esbuild";
import http from "node:http";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";

const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const dev = args.includes("--dev");
const watch = args.includes("--watch");
const outRoot = dev ? ".dev" : "dist";

const html = (liveReload) => `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark" />
  <title>ResQLens – Failure Diagnosis & Recovery Decision Support</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%230b1526'/%3E%3Ccircle cx='15' cy='15' r='8' fill='none' stroke='%2322d3ee' stroke-width='3'/%3E%3Cpath d='M21 21l6 6' stroke='%233b82f6' stroke-width='3' stroke-linecap='round'/%3E%3C/svg%3E" />
  <link rel="stylesheet" href="/assets/main.css" />
</head>
<body>
  <div id="root"></div>
  <script type="module" src="/assets/main.js"></script>${liveReload ? `
  <script>new EventSource("/esbuild").addEventListener("change", () => location.reload());</script>` : ""}
</body>
</html>`;

rmSync(outRoot, { recursive: true, force: true });
mkdirSync(`${outRoot}/assets`, { recursive: true });
writeFileSync(`${outRoot}/index.html`, html(dev));

const options = {
  entryPoints: ["src/main.tsx"],
  bundle: true,
  outdir: `${outRoot}/assets`,
  format: "esm",
  jsx: "automatic",
  target: ["es2020"],
  minify: !(dev || watch),
  sourcemap: dev || watch,
  define: { "process.env.NODE_ENV": JSON.stringify(dev || watch ? "development" : "production") },
  logLevel: "info",
};

if (dev) {
  const host = arg("--host", "127.0.0.1");
  const port = Number(arg("--port", "5173"));
  const api = new URL(arg("--api", process.env.BACKEND_URL || "http://127.0.0.1:8000"));
  const ctx = await esbuild.context(options);
  await ctx.watch();
  const internal = await ctx.serve({ host: "127.0.0.1", port: 0, servedir: outRoot, fallback: `${outRoot}/index.html` });
  const proxy = (req, res, target) => {
    const upstream = http.request(
      { hostname: target.host, port: target.port, path: req.url, method: req.method, headers: { ...req.headers, host: `${target.host}:${target.port}` } },
      (up) => { res.writeHead(up.statusCode || 502, up.headers); up.pipe(res); },
    );
    upstream.on("error", (err) => {
      res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: { code: "BACKEND_UNAVAILABLE", message: `Backend not reachable at ${target.host}:${target.port} (${err.code}). Start it with start_backend.bat.` } }));
    });
    req.pipe(upstream);
  };
  const isBackend = (url) => url.startsWith("/api/") || url === "/api" || url.startsWith("/docs") || url.startsWith("/openapi.json");
  http.createServer((req, res) => {
    if (isBackend(req.url)) proxy(req, res, { host: api.hostname, port: Number(api.port || 80) });
    else proxy(req, res, { host: "127.0.0.1", port: internal.port });
  }).on("error", (err) => {
    console.error(err.code === "EADDRINUSE" ? `\n  Port ${port} is already in use. Stop the other process or run: npm run dev -- --port 5174\n` : err);
    process.exit(1);
  }).listen(port, host, () => {
    console.log(`\n  ResQLens dev server   http://${host === "127.0.0.1" ? "localhost" : host}:${port}`);
    console.log(`  Proxying /api, /docs  -> ${api.origin}`);
    console.log("  Live reload on save. Press Ctrl+C to stop.\n");
  });
} else if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  console.log("Watching src/ ... rebuilding dist/ (served by the backend at http://localhost:8000)");
} else {
  await esbuild.build(options);
}
