#!/usr/bin/env bash
# EDB 便携版 PostgreSQL 17.6 的 bash 入口（转调 .ps1，Windows 宿主用）。
# 在 Linux/WSL 上请直接用系统 postgres 或 container（首期不支持，见 R1）。
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec powershell -NoProfile -ExecutionPolicy Bypass -File "$REPO_ROOT/scripts/pg_portable_setup.ps1" "${1:-status}"
