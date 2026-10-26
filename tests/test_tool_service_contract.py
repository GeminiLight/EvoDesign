from __future__ import annotations

import json
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_SERVICES = REPO_ROOT / "evo_diagram" / "agentic_system" / "tool_services"
RENDERER_ROUTES = {
    "/renderers/excalidraw": (
        TOOL_SERVICES
        / "src/app/api/v1/renderers/excalidraw/snapshot/route.ts"
    ),
    "/renderers/tldraw": (
        TOOL_SERVICES
        / "src/app/api/v1/renderers/tldraw/snapshot/route.ts"
    ),
}
SNAPSHOT_RENDERER = (
    TOOL_SERVICES
    / "src/app/api/v1/renderers/_shared/snapshotRenderer.ts"
)


def _assert_wait_for_function_timeout_is_third_arg(source: str) -> None:
    cursor = 0
    while True:
        index = source.find("waitForFunction", cursor)
        if index < 0:
            return
        snippet = source[index : index + 260]
        timeout_index = snippet.find("{ timeout:")
        if timeout_index >= 0:
            before_timeout = snippet[:timeout_index]
            assert "null," in before_timeout or "loaderFunctionName," in before_timeout, snippet
        cursor = index + len("waitForFunction")


def test_renderer_runtime_assets_are_package_data():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["evo_diagram"]

    assert "agentic_system/tool_services/scripts/*.ts" in package_data
    assert "agentic_system/tool_services/src/**/*.ts" in package_data
    assert "agentic_system/tool_services/src/**/*.tsx" in package_data
    assert "agentic_system/tool_services/src/**/*.css" in package_data
    assert "agentic_system/tool_services/src/**/*.ico" in package_data
    assert "resources/fonts/*.ttf" in package_data
    assert "resources/fonts/*.woff2" in package_data
    assert "agentic_system/tool_services/package.json" in package_data
    assert "agentic_system/tool_services/next-env.d.ts" in package_data
    assert "agentic_system/tool_services/next.config.js" in package_data


def test_renderer_snapshot_routes_reject_request_url_overrides():
    request_helper = (
        TOOL_SERVICES
        / "src/app/api/v1/renderers/_shared/rendererRequest.ts"
    ).read_text(encoding="utf-8")
    snapshot_helper = SNAPSHOT_RENDERER.read_text(encoding="utf-8")
    assert "Renderer URL overrides are not accepted" in request_helper
    assert "Configured renderer URL must point to a local host" in request_helper
    assert "viewport.margin is not supported by snapshot routes" in request_helper
    assert "MAX_RENDERER_VIEWPORT" in request_helper
    assert "parseRendererJsonRequest(request)" in snapshot_helper
    assert "resolveRendererUrl(" in snapshot_helper
    assert "parseViewport(body.viewport, DEFAULT_RENDERER_VIEWPORT)" in snapshot_helper
    assert "waitUntil: 'load'" in snapshot_helper
    assert "waitUntil: 'networkidle'" not in snapshot_helper

    for expected_path, route_path in RENDERER_ROUTES.items():
        source = route_path.read_text(encoding="utf-8")
        assert "renderSnapshotRequest(request" in source
        assert f"const RENDERER_PATH = '{expected_path}';" in source
        assert "const { scene, viewport, url }" not in source
        assert "const { manifest, viewport, url }" not in source
        assert "body.manifest" not in source
        assert "body.url" not in source
        assert "page.goto(url" not in source
        assert "chromium.launch" not in source
        assert "waitForTimeout" not in source


def test_renderer_snapshot_routes_use_canvas_native_payload_names():
    excalidraw_route = RENDERER_ROUTES["/renderers/excalidraw"].read_text(
        encoding="utf-8"
    )
    tldraw_route = RENDERER_ROUTES["/renderers/tldraw"].read_text(
        encoding="utf-8"
    )
    snapshot_helper = SNAPSHOT_RENDERER.read_text(encoding="utf-8")

    assert "payloadField: 'scene'" in excalidraw_route
    assert "payloadLabel: 'Excalidraw scene'" in excalidraw_route
    assert "loaderFunctionName: 'loadExcalidrawScene'" in excalidraw_route
    assert "payloadField: 'snapshot'" in tldraw_route
    assert "payloadLabel: 'TLDraw snapshot'" in tldraw_route
    assert "loaderFunctionName: 'loadTldrawSnapshot'" in tldraw_route
    assert "readRequiredField(body, 'manifest'" not in excalidraw_route
    assert "readRequiredField(body, 'manifest'" not in tldraw_route
    assert "readRequiredField(" in snapshot_helper
    assert "__renderStatus === 'ready'" in snapshot_helper
    assert "__renderStatus === 'error'" in snapshot_helper


def test_excalidraw_snapshot_route_returns_canvas_native_export():
    route = RENDERER_ROUTES["/renderers/excalidraw"].read_text(encoding="utf-8")

    assert "__exportedImageData" in route
    assert "decodePngDataUrl" in route
    assert "page.screenshot" not in route


def test_renderer_clis_use_canonical_local_renderer_pages():
    excalidraw_cli = (TOOL_SERVICES / "scripts/render-excalidraw.ts").read_text(
        encoding="utf-8"
    )
    tldraw_cli = (TOOL_SERVICES / "scripts/render-tldraw.ts").read_text(
        encoding="utf-8"
    )

    assert "process.env.EXCALIDRAW_RENDER_URL" in excalidraw_cli
    assert "http://localhost:3000/renderers/excalidraw" in excalidraw_cli
    assert "process.env.TLDRAW_RENDER_URL" in tldraw_cli
    assert "http://localhost:3000/renderers/tldraw" in tldraw_cli


def test_tool_services_dev_server_pins_renderer_port_3000():
    package_json = json.loads(
        (TOOL_SERVICES / "package.json").read_text(encoding="utf-8")
    )
    start_script = (REPO_ROOT / "scripts/start_service.sh").read_text(encoding="utf-8")

    assert package_json["scripts"]["dev"] == "next dev --port 3000"
    assert package_json["scripts"]["start"] == "next start --port 3000"
    assert "Starting on port 3000" in start_script
    assert "exec npm run dev" in start_script


def test_tldraw_error_boundary_sets_render_error_status():
    source = (
        TOOL_SERVICES / "src/app/components/ErrorBoundary.tsx"
    ).read_text(encoding="utf-8")

    assert "__renderStatus = 'error'" in source
    assert "__renderError = error?.message || String(error)" in source


def test_renderer_clis_do_not_generate_transitional_standalone_html():
    sources = [
        (TOOL_SERVICES / "scripts/render-excalidraw.ts").read_text(
            encoding="utf-8"
        ),
        (TOOL_SERVICES / "scripts/render-tldraw.ts").read_text(
            encoding="utf-8"
        ),
    ]

    forbidden_fragments = [
        "esm.sh",
        "unpkg.com",
        "fonts.googleapis.com",
        "mkdtemp",
        "pathToFileURL",
        "Generated independent renderer",
        "self-contained HTML",
        "standalone HTML",
    ]

    for source in sources:
        for fragment in forbidden_fragments:
            assert fragment not in source


def test_renderer_snapshot_viewport_margin_is_cli_only():
    helper = (
        TOOL_SERVICES
        / "src/app/api/v1/renderers/_shared/rendererRequest.ts"
    ).read_text(encoding="utf-8")

    assert "viewport.margin is not supported by snapshot routes" in helper
    assert "use the renderer CLI margin option for clipped exports" in helper
    for route_path in RENDERER_ROUTES.values():
        source = route_path.read_text(encoding="utf-8")
        assert "margin: 40" not in source


def test_renderer_entrypoints_share_render_defaults():
    defaults = (TOOL_SERVICES / "src/lib/renderDefaults.ts").read_text(
        encoding="utf-8"
    )
    excalidraw_cli = (TOOL_SERVICES / "scripts/render-excalidraw.ts").read_text(
        encoding="utf-8"
    )
    tldraw_cli = (TOOL_SERVICES / "scripts/render-tldraw.ts").read_text(
        encoding="utf-8"
    )
    excalidraw_page = (
        TOOL_SERVICES / "src/app/renderers/excalidraw/page.tsx"
    ).read_text(encoding="utf-8")
    snapshot_helper = SNAPSHOT_RENDERER.read_text(encoding="utf-8")

    assert "DEFAULT_RENDERER_VIEWPORT" in defaults
    assert "width: 4000" in defaults
    assert "height: 4000" in defaults
    assert "DEFAULT_RENDER_TIMEOUT_MS = 60000" in defaults
    assert "DEFAULT_RENDER_MARGIN = 40" in defaults
    assert "DEFAULT_EXCALIDRAW_EXPORT_SCALE = 4" in defaults
    assert "MAX_RENDERER_VIEWPORT" in defaults
    assert "MAX_RENDER_TIMEOUT_MS = 300000" in defaults
    assert "MAX_RENDER_MARGIN = 1000" in defaults
    assert "MAX_EXCALIDRAW_EXPORT_SCALE = 4" in defaults

    for source in (excalidraw_cli, tldraw_cli):
        assert "from '../src/lib/renderDefaults'" in source
        assert "from '../src/lib/renderContract'" in source
        assert "validateRendererUrl(" in source
        assert "validateRenderDimensions(" in source
        assert "validateRenderTimeout(" in source
        assert "validateRenderMargin(" in source
        assert "DEFAULT_RENDERER_VIEWPORT.width" in source
        assert "DEFAULT_RENDERER_VIEWPORT.height" in source
        assert "DEFAULT_RENDER_TIMEOUT_MS" in source
        assert "DEFAULT_RENDER_MARGIN" in source

    assert "DEFAULT_EXCALIDRAW_EXPORT_SCALE" in excalidraw_cli
    assert "validateExcalidrawExportScale(" in excalidraw_cli
    assert "DEFAULT_EXCALIDRAW_EXPORT_SCALE" in excalidraw_page
    assert "DEFAULT_RENDER_MARGIN" in excalidraw_page

    assert "DEFAULT_RENDERER_VIEWPORT" in snapshot_helper
    assert "DEFAULT_RENDER_TIMEOUT_MS" in snapshot_helper
    assert "parseViewport(body.viewport, DEFAULT_RENDERER_VIEWPORT)" in snapshot_helper

    for route_path in RENDERER_ROUTES.values():
        source = route_path.read_text(encoding="utf-8")
        assert "width: 2000" not in source
        assert "height: 1400" not in source
        assert "width: 3000" not in source
        assert "height: 2000" not in source

    assert "viewportHeight: 5080" not in tldraw_cli
    assert "Default: 1080" not in tldraw_cli


def test_renderer_wait_for_function_timeout_is_passed_as_options():
    sources = [
        TOOL_SERVICES / "scripts/render-excalidraw.ts",
        TOOL_SERVICES / "scripts/render-tldraw.ts",
        SNAPSHOT_RENDERER,
    ]

    for path in sources:
        _assert_wait_for_function_timeout_is_third_arg(
            path.read_text(encoding="utf-8")
        )


def test_renderer_clis_use_ci_safe_chromium_launch_flags():
    sources = [
        (TOOL_SERVICES / "scripts/render-excalidraw.ts").read_text(
            encoding="utf-8"
        ),
        (TOOL_SERVICES / "scripts/render-tldraw.ts").read_text(
            encoding="utf-8"
        ),
    ]

    for cli in sources:
        assert "chromium.launch({" in cli
        assert "headless: true" in cli
        assert "--no-sandbox" in cli
        assert "--disable-setuid-sandbox" in cli
        assert "--disable-dev-shm-usage" in cli


def test_tldraw_cli_uses_script_specific_renderer_url():
    cli = (TOOL_SERVICES / "scripts/render-tldraw.ts").read_text(encoding="utf-8")

    assert "process.env.TLDRAW_RENDER_URL" in cli
    assert "NEXT_PUBLIC_APP_URL" not in cli


def test_renderer_snapshot_docs_do_not_advertise_request_url_overrides():
    docs = (TOOL_SERVICES / "wiki.md").read_text(encoding="utf-8")

    assert '"url": "http://localhost:3000/renderers/excalidraw"' not in docs
    assert "可选，覆盖默认地址" not in docs
    assert "Snapshot API 不接受请求体级别的 `url` 覆盖" in docs
    assert "Excalidraw 使用 `scene`，TLDraw 使用 `snapshot`" in docs
    assert "`manifest` 不是 Snapshot API 的请求字段" in docs
    assert "HTTP Snapshot API 不接受 `viewport.margin`" in docs
    assert "EXCALIDRAW_RENDER_URL" in docs
    assert "TLDRAW_RENDER_URL" in docs
    assert "RENDERER_URL" not in docs
    assert "path 必须匹配对应的 renderer 页面" in docs
    assert "CLI 模式 (CLI Mode)" in docs
    assert "Zero-Port Mode" not in docs
    assert "渲染 CLI 不再生成临时 CDN HTML" in docs
    assert "`file://out/...`" in docs
    assert "out/renderers/excalidraw/index.html" not in docs
    assert "out/renderers/tldraw/index.html" not in docs


def test_text_width_route_and_cli_share_font_measurement_module():
    shared = (TOOL_SERVICES / "src/lib/textWidth.ts").read_text(encoding="utf-8")
    route = (
        TOOL_SERVICES / "src/app/api/v1/tools/text-width/route.ts"
    ).read_text(encoding="utf-8")
    cli = (TOOL_SERVICES / "scripts/text-width-cli.ts").read_text(encoding="utf-8")

    assert "resolveFontsDir" in shared
    assert "evo_diagram/resources/fonts" in shared
    assert "TextWidthInputError" in shared
    assert "SUPPORTED_TEXT_WIDTH_FONTS" in shared
    assert "MAX_TEXT_WIDTH_TEXT_LENGTH = 10000" in shared
    assert "MAX_TEXT_WIDTH_FONT_SIZE = 512" in shared
    assert "String(body.text)" not in shared
    assert "readOptionalFont(body.font)" in shared
    assert "error instanceof TextWidthInputError" in route
    assert "parseTextWidthRequest" in route
    assert "measureTextWidth" in route
    assert "parseTextWidthRequest" in cli
    assert "measureTextWidth" in cli
    assert "../../resources" not in route
    assert "../../../../resources" not in cli


def test_layout_route_and_cli_share_layout_module():
    shared = (TOOL_SERVICES / "src/lib/layout.ts").read_text(encoding="utf-8")
    route = (
        TOOL_SERVICES / "src/app/api/v1/tools/layout/route.ts"
    ).read_text(encoding="utf-8")
    cli = (TOOL_SERVICES / "scripts/layout-cli.ts").read_text(encoding="utf-8")

    assert "computeLayoutPositions" in shared
    assert "parseLayoutRequest" in shared
    assert "SUPPORTED_LAYOUTS" in shared
    assert "SUPPORTED_RANKDIRS" in shared
    assert "MAX_LAYOUT_NODES = 500" in shared
    assert "MAX_LAYOUT_EDGES = 1000" in shared
    assert "MAX_LAYOUT_DIMENSION = 10000" in shared
    assert "MAX_LAYOUT_SPACING = 5000" in shared
    assert "MAX_LAYOUT_LABEL_LENGTH = 2000" in shared
    assert "parseNodes(body.nodes)" in shared
    assert "parseEdges(body.edges, nodeIds)" in shared
    assert "layout: normalizeLayout(body.layout)" in shared
    assert "normalizeRankdir(body.rankdir)" in shared
    assert "readBoundedNumber(body.nodesep" in shared
    assert "const rankdir = normalizeRankdir(input.rankdir) || 'TB'" in shared
    assert "readLegacyNumber" not in shared
    assert "references unknown node" in shared
    assert "computeLayoutPositions" in route
    assert "parseLayoutRequest" in route
    assert "computeLayoutPositions" in cli
    assert "parseLayoutRequest" in cli
    assert "import dagre" not in route
    assert "import * as d3" not in route
    assert "import dagre" not in cli
    assert "import * as d3" not in cli
