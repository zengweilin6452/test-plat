# 来源与文件清单（release-readiness 受控验收套件）

- `test_smoke.py`：逐字复制自 `.scratch/first-release-closure/real-suite/test_smoke.py`
  （2026-11-01 首期真机验收用的受控冒烟套件，2 用例：派发设备绑定 + 冷启动截帧；
  11-08 增加 15s 前台停留用例后的版本，共 3 用例——以 `FILES.sha256` 为准）。
- `test_deliberate_failure.py`：本轮新增，唯一改动点；故意的断言失败用例，
  用于验证失败结论与证据产物链路（release-readiness 工单 02）。
- 本目录是宿主配置的受控验收来源（`TESTDOCK_SUITE_SOURCES` 指向它），
  不是客户生产套件；未修改 `.scratch/first-release-closure/` 下任何文件。
