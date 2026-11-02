# Regional browser deployments

The public browser release has one codebase and two runtimes:

- International: Vercel, with the existing `api/model.mjs` function.
- China: [ModelScope Studio](https://modelscope.cn/studios/GeminiLight/EvoDesign?mode=full), with `deploy/modelscope/server.mjs` serving the same built application and model handler on port 7860.

Neither deployment includes research datasets, experiments, private repository history or the full local backend. Both use `glm-5.3-flash` and the **same** Redis namespace and limits. Creating a mirror does not double the global allowance. Model keys and Redis credentials are platform secrets, never `VITE_*` settings.

## Entry and stored work

`deploy/routing/worker.mjs` runs on the Cloudflare route `evodesign.aurax.live/*`. Its ordinary origin remains the existing Vercel DNS target. Set `AUTO_ROUTE_ENABLED=1` only after the Studio and model service pass release checks; the initial configuration keeps it off until activation.

For document navigation to `/` or `/home`, a mainland-China (`CN`) IP selects the China workspace. All other locations, including unknown geography, stay on the international origin. Project deep links, other application routes, API requests and static assets are never geographically redirected. Automatic selection uses no third-party IP lookup and requests no device-location permission.

Before moving an automatic China visit, a minimal same-origin page checks whether the browser already has projects, DNA or model settings. It reads only whether those keys contain data; it never transmits their contents. Existing or unreadable data stays on the original origin, including when storage access is blocked. Choosing China or Global explicitly overrides this protection; choosing Automatic clears the remembered choice and keeps it. Projects, DNA and keys are **not** synchronized between origins.

**Preferences → Workspace region** opens the selected workspace in a new tab. The entry accepts only `region=auto`, `region=cn` and `region=global`; destinations are fixed. Explicit choices are remembered for a year in a Secure, HttpOnly, SameSite cookie. The landing query also prevents a loop if cookies are blocked. Responses use temporary redirects and `private, no-store` so country or preference cannot be cached for another visitor.

## Proxy identity and budget

Vercel overwrites `x-real-ip`. With Cloudflare in front, this can identify a proxy rather than the visitor. The entry signs Cloudflare's own client IP with `DEMO_EDGE_IP_SECRET`, removes incoming copies of the signature headers, and passes a short-lived HMAC proof to `/api/model`. The function verifies it before generating its existing daily visitor hash. Unsigned, stale or invalid proofs fall back to Vercel's IP. A user-supplied forwarded chain is never accepted. Keep the signing secret identical on the Worker and Vercel.

The Studio uses its managed ingress identity and the same bounded model handler. `STUDIO_PUBLIC_ORIGIN` is fixed to the application's `.ms.show` origin. A foreign or missing browser origin cannot spend the shared budget. The server permits Studio framing, serves missing assets as 404, and uses SPA fallback only for application routes.

## Publish and validate

1. Run the frontend quality gate, including `test:browser` and both build modes.
2. Set Studio secrets `DEMO_GLM_API_KEY`, `DEMO_REDIS_URL` and `DEMO_REDIS_TOKEN` to the existing production values. Preserve existing limits. Set `STUDIO_PUBLIC_ORIGIN=https://geminilight-evodesign.ms.show` as a plaintext variable.
3. Build with `npm --prefix frontend run build:browser`, then run `python scripts/publish_modelscope.py` with `MODELSCOPE_API_KEY` securely supplied through the environment. The publisher uses an isolated clone and fixed file allowlist, retains Studio Git history, never force pushes, explicitly requests deployment, and checks the running revision.
4. The public repository's **China workspace** workflow can always be run manually on `main`. It publishes successful `main` Quality runs automatically only after the repository variable `MODELSCOPE_PUBLISH=true` is set, using its `MODELSCOPE_API_KEY` secret. Fork pull requests and non-main manual runs cannot deploy. The dev repository does not have a second publisher competing for the same Studio.
5. The **Preferences → Workspace region** switch is hidden until browser builds set `VITE_REGION_SWITCH=1` (Vercel project setting and the repository variable of the same name for the Studio build). Turn it on together with `AUTO_ROUTE_ENABLED=1`, because the entry ignores `region` while routing is off.
6. Check Studio Running and `/api/health`, asset bytes, model discovery, a real diagram and edit. Check the public Studio iframe separately from its authenticated API host. Validate CN, overseas, explicit choice, stored-data and cookie-disabled routing before activation.

Cloudflare configuration is in `deploy/routing/wrangler.jsonc`; verify it against the current Wrangler schema before deploying. Account and zone are pinned to the existing aurax.live owner. Do not change other applications' routes or DNS records.

## Roll back

Set `AUTO_ROUTE_ENABLED=0` and redeploy to stop entry redirects immediately. The international application and stored work remain available. If the proxy itself is unavailable, remove only the EvoDesign Worker route and return the EvoDesign CNAME to DNS-only with its recorded Vercel target. Do not delete the Studio or browser data. Free Studio sleep/wake behavior and mainland network performance require real-user observation; geographic routing alone is not a mainland CDN guarantee.
