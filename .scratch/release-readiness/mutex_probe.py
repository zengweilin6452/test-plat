"""一次性互斥探针：运行占用设备期间尝试创建调试会话。

流程：启动 joint 运行 → 轮询到租约激活（dispatching/running）→ 立即 POST /debug-sessions
→ 打印响应 → 关闭会话（若创建成功）→ 取消运行收尾。
"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
HEADERS = {"Content-Type": "application/json", "X-TestDock-Client": "web"}
TID = "02fb058b-7091-48cd-887d-7dd61c725e4f"
APP = "a9feb4f2-9d51-4d6e-9ea1-aeb423901f5f"


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


status, run = call("POST", "/runs", {
    "task_id": TID, "platform": "android", "application_id": APP,
    "request_key": f"rr-mutex2-{int(time.time())}",
})
print("run:", run.get("display_id"), run.get("id"))
rid = run["id"]

deadline = time.time() + 20
lease_active = False
while time.time() < deadline:
    _, r = call("GET", f"/runs/{rid}")
    if r.get("state") in ("dispatching", "running", "finalizing"):
        lease_active = True
        break
    if r.get("state") in ("completed", "errored", "cancelled"):
        break
    time.sleep(0.3)
print("run_state_before_probe:", r.get("state"), "lease_active:", lease_active)

if lease_active:
    st, sess = call("POST", "/debug-sessions", {"serial": "749622c9"})
    print("debug_create ->", st, json.dumps(sess, ensure_ascii=False)[:300])
    if st < 300:
        call("DELETE", f"/debug-sessions/{sess['id']}")
        print("debug session cleaned")

# 收尾：取消运行，释放设备
st2, cancelled = call("POST", f"/runs/{rid}/cancel", {})
print("cancel ->", st2, json.dumps(cancelled, ensure_ascii=False)[:200])
time.sleep(3)
_, final = call("GET", f"/runs/{rid}")
print("final:", final.get("state"), final.get("outcome"))
