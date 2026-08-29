from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_image_builds_fresh_desktop_frontend_from_lockfile():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()

    assert (
        "FROM --platform=$BUILDPLATFORM node:22-bookworm-slim@sha256:"
        "83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5 "
        "AS frontend-builder"
    ) in dockerfile
    assert "COPY frontend/package.json frontend/package-lock.json ./" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "COPY frontend/ ./" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert (
        "COPY --from=frontend-builder /static/vue-dist ./static/vue-dist"
        in dockerfile
    )
    assert dockerfile.index("COPY static/ ./static/") < dockerfile.index(
        "COPY --from=frontend-builder /static/vue-dist ./static/vue-dist"
    )


def test_docker_context_includes_frontend_build_inputs():
    ignored_lines = {
        line.strip()
        for line in (PROJECT_ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "frontend/*" not in ignored_lines
    assert "frontend/src/*" not in ignored_lines
    assert "frontend/package.json" not in ignored_lines
    assert "frontend/package-lock.json" not in ignored_lines
    assert "**/node_modules/" in ignored_lines
    assert "static/vue-dist/" in ignored_lines
