# Skill: `metronow-dockerfile-review`

**Summary.** Audit MetroNow Atlas Dockerfile, docker-compose files,
and container configs. The runtime is a multi-stage build producing a
`python:3.12-slim` image with Node.js 20 layered in; the Express.js
server (`web/server.js`) listens on port 3000 and shells out to the
Python `osm` CLI.

## What it does

Applies the container-specific subset of standards:

- **Multi-stage builds** — `python-deps` + `node-deps` + final
  `python:3.12-slim` runtime; stages are layered, not flattened.
- **Pinned base image** — `python:3.12-slim` with explicit version,
  not `latest`.
- **No secrets in `ENV`** — Blocker-level if a key, token, or
  credential ends up baked into the image.
- **Minimal apt installs** — each `apt-get install` followed by
  `rm -rf /var/lib/apt/lists/*` to keep layers small.
- **Health check** — `HEALTHCHECK` against the Express `/health`
  endpoint at port 3000.
- **Non-root user for runtime** — Warning-level if the final stage
  runs as root.
- **`COPY` layer ordering** — `requirements.txt` / `package.json`
  copied before the source so dependency layer is cacheable.

## When to invoke

- "Review my Dockerfile"
- "Is this image secure"
- "Optimize my Docker build"
- "Check my compose file"
- A `Dockerfile` / `docker-compose.yml` / `.dockerignore` is in scope.

## What it produces

Standard review report with Blocker / Warning / Info findings, scoped
to the container config under review.

## Related skills

- [`metronow-code-review`](metronow-code-review.md) — umbrella that
  invokes this skill for Dockerfile-shaped files.

## See also

- [`SKILL.md`](../../.claude/skills/metronow-dockerfile-review/SKILL.md)
- [`docs/web-architecture.md`](../web-architecture.md) — the runtime
  this Dockerfile builds.
