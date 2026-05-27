=== Task 8 — README.md (#13 API) ===

[✅ #13] API endpoints documented — 49 endpoints across 12 groups:
  - Health check & system:       3 (GET /api/health, GET /api/check-update, POST /api/shutdown)
  - Config management:           5 (GET/PUT /api/config, GET /api/init-status, GET/POST /api/safe-mode)
  - Profiles:                    8 (GET list, GET active, GET/{id}, PUT/{id}, DELETE/{id}, POST active/{id}, POST detect, POST auto-switch)
  - Monitor control:             3 (GET /api/status, POST /api/monitor/start, POST /api/monitor/stop)
  - Manual actions:              2 (POST /api/actions/login, POST /api/actions/test-network)
  - Task management:            10 (GET list, GET/{id}, PUT/{id}, DELETE/{id}, GET active, POST active/{id}, GET repo/fetch, GET repo/task, GET tools/*, GET docs/*)
  - Logs:                        2 (GET /api/logs, WS /ws/logs)
  - Autostart:                   3 (GET status, POST enable, POST disable)
  - Static resources:            1 (GET /debug/{filename})
  - Debug:                       5 (POST start, POST next, POST run-all, POST stop, GET status)
  - Uninstall:                   2 (GET /api/uninstall/detect, POST /api/uninstall)
  - Backup:                      5 (GET list, POST create, POST restore, GET download, DELETE)
  Total: 49 API endpoints documented (well exceeds the 19 requirement).

VERDICT: PASS
