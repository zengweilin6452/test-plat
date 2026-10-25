"""网络剖面编排（ticket 17）：档位纯函数、代理侧证据判定、生命周期恢复与 doctor。

三条实测约束的回归保护：
① 档位校验宁可早失败，不静默用错误参数跑采集；
② 代理是否生效**只看代理侧日志**——不能拿"页面能否打开"当证据；
③ 异常路径后设备代理与 reverse 必被恢复，doctor 能发现并复验残留。
"""

import json
import socket
from types import SimpleNamespace

import pytest

from mobile_perf import netprof

# ---------- 档位纯函数 ----------


def test_build_profile_returns_preset_parameters():
    profile = netprof.build_profile("weak")

    assert profile.name == "weak"
    assert profile.latency_ms == 400.0
    assert profile.down_kbps == 400.0
    assert profile.up_kbps == 200.0
    assert profile.loss_pct == 2.0
    assert profile.is_passthrough is False


def test_build_profile_none_is_passthrough():
    assert netprof.build_profile("none").is_passthrough is True


def test_build_profile_preset_override_only_changes_given_keys():
    profile = netprof.build_profile("3g", {"latency_ms": 500})

    assert profile.latency_ms == 500.0
    assert profile.down_kbps == 780.0  # 其余保持预设


def test_build_profile_custom_requires_all_parameters():
    with pytest.raises(ValueError, match="缺少参数.*down_kbps"):
        netprof.build_profile("custom", {"latency_ms": 100, "up_kbps": 100, "loss_pct": 0})


def test_build_profile_custom_accepts_full_parameters():
    profile = netprof.build_profile(
        "custom", {"latency_ms": 120, "down_kbps": 900, "up_kbps": 300, "loss_pct": 5}
    )

    assert profile.as_dict() == {
        "name": "custom",
        "latencyMs": 120.0,
        "downKbps": 900.0,
        "upKbps": 300.0,
        "lossPct": 5.0,
    }


def test_build_profile_rejects_unknown_preset():
    with pytest.raises(ValueError, match="未知网络档位"):
        netprof.build_profile("2g")


def test_build_profile_rejects_unknown_parameter():
    with pytest.raises(ValueError, match="未知网络参数"):
        netprof.build_profile("4g", {"jitter_ms": 10})


def test_build_profile_rejects_negative_and_oversized_loss():
    with pytest.raises(ValueError, match="不能为负"):
        netprof.build_profile("4g", {"latency_ms": -1})
    with pytest.raises(ValueError, match="丢包率不能超过 100%"):
        netprof.build_profile("custom", {"latency_ms": 1, "down_kbps": 1, "up_kbps": 1,
                                         "loss_pct": 150})


def test_profiles_are_comparable_requires_identical_parameters():
    weak = netprof.build_profile("weak").as_dict()
    weak_override = netprof.build_profile("weak", {"latency_ms": 401}).as_dict()

    assert netprof.profiles_are_comparable(weak, dict(weak)) is True
    assert netprof.profiles_are_comparable(weak, weak_override) is False
    # 未记录档位的历史 run 与任何档位都不可比（与设备档案同构语义）
    assert netprof.profiles_are_comparable(None, weak) is False
    assert netprof.profiles_are_comparable(None, None) is True


# ---------- mitmproxy 探测 ----------


def test_find_mitmproxy_reports_missing_with_actionable_hint():
    result = netprof.find_mitmproxy(candidates=[], which=lambda _n: None, probe=lambda _p: None,
                                    env={})

    assert result.available is False
    assert "3.12" in result.reason
    assert "MOBILE_PERF_MITMDUMP" in result.hint


def test_find_mitmproxy_prefers_explicit_candidate_over_env_and_path():
    probed = []

    def probe(path):
        probed.append(path)
        return "12.3.0"

    result = netprof.find_mitmproxy(
        candidates=["/explicit/mitmdump"],
        which=lambda _n: "/path/mitmdump",
        probe=probe,
        env={"MOBILE_PERF_MITMDUMP": "/env/mitmdump"},
    )

    assert result.available is True
    assert result.executable == "/explicit/mitmdump"
    assert probed == ["/explicit/mitmdump"]  # 命中即停，不继续探测


def test_find_mitmproxy_falls_back_to_env_when_explicit_fails():
    versions = {"/env/mitmdump": "12.3.0"}

    result = netprof.find_mitmproxy(
        candidates=["/broken/mitmdump"],
        which=lambda _n: None,
        probe=lambda path: versions.get(path),
        env={"MOBILE_PERF_MITMDUMP": "/env/mitmdump"},
    )

    assert result.executable == "/env/mitmdump"


# ---------- 代理侧日志：生效的唯一证据 ----------


def _lines(*records) -> list[str]:
    return [json.dumps(record) if isinstance(record, dict) else record for record in records]


def test_analyze_log_counts_connections_and_first_byte_duration():
    lines = _lines(
        {"t": 100.0, "ev": "http_connect", "host": "api.example.com", "port": 443},
        {"t": 100.5, "ev": "tcp_start", "fid": "f1", "host": "api.example.com", "port": 443},
        {"t": 101.0, "ev": "tcp_message", "fid": "f1", "from_client": True, "size": 300},
        {"t": 101.2, "ev": "tcp_message", "fid": "f1", "from_client": True, "size": 90},
        {"t": 102.0, "ev": "tcp_message", "fid": "f1", "from_client": False, "size": 5000},
        {"t": 103.0, "ev": "tcp_end", "fid": "f1"},
    )

    summary = netprof.analyze_proxy_log(lines)

    assert summary.connections == 1
    assert summary.conn_durations_ms == [pytest.approx(500.0)]  # 100.5 → 101.0
    assert summary.hosts == ["api.example.com"]  # CONNECT 与 tcp_start 同 host 只留一次
    assert summary.connect_requests == 1
    assert summary.bytes_up == 390
    assert summary.bytes_down == 5000
    assert summary.evidence == netprof.EVIDENCE_OBSERVED


def test_analyze_log_without_connections_is_not_evidence():
    """代理起来了但日志里没有连接 → 没有证据，不能算生效。"""
    summary = netprof.analyze_proxy_log(_lines({"t": 1.0, "ev": "params", "latencyMs": 400}))

    assert summary.connections == 0
    assert summary.evidence == netprof.EVIDENCE_NONE
    assert summary.params == {"latencyMs": 400}


def test_analyze_log_skips_malformed_lines_and_counts_errors():
    lines = _lines(
        "not json at all",
        "",
        {"t": 1.0, "ev": "tcp_start", "fid": "f1", "host": "a.com", "port": 443},
        {"t": 2.0, "ev": "tcp_error", "fid": "f1", "error": "connection reset"},
        {"t": 3.0, "ev": "server_connect_error", "cid": "c1", "error": "refused"},
    )

    summary = netprof.analyze_proxy_log(lines)

    assert summary.connections == 1
    assert summary.errors == 2
    assert summary.conn_durations_ms == []  # 无首字节的流不计耗时


def test_analyze_log_counts_connection_without_bytes_as_connection_only():
    summary = netprof.analyze_proxy_log(
        _lines({"t": 1.0, "ev": "tcp_start", "fid": "f9", "host": "a.com", "port": 443})
    )

    assert summary.connections == 1
    assert summary.conn_durations_ms == []


def test_read_proxy_log_missing_file_returns_empty_summary(tmp_path):
    summary = netprof.read_proxy_log(tmp_path / "absent.jsonl")

    assert summary.connections == 0
    assert summary.evidence == netprof.EVIDENCE_NONE


def test_conn_duration_rows_aggregates_and_skips_empty():
    summary = netprof.analyze_proxy_log(
        _lines(
            {"t": 0.0, "ev": "tcp_start", "fid": "a", "host": "h", "port": 443},
            {"t": 0.1, "ev": "tcp_message", "fid": "a", "from_client": True, "size": 1},
            {"t": 1.0, "ev": "tcp_start", "fid": "b", "host": "h", "port": 443},
            {"t": 1.5, "ev": "tcp_message", "fid": "b", "from_client": True, "size": 1},
        )
    )

    rows = netprof.conn_duration_rows(summary)

    assert [row["metric_key"] for row in rows] == ["net_conn_duration_ms"]
    assert rows[0]["median"] == pytest.approx(300.0)  # 100ms 与 500ms 的中位
    assert rows[0]["sample_count"] == 2
    assert rows[0]["source"] == "pc_supplement"
    assert netprof.conn_duration_rows(netprof.ProxyLogSummary()) == []


# ---------- 生命周期 ----------


class FakeDevice:
    """记录 adb 调用；按需让某些命令失败。stdout_map 按子串匹配命令。"""

    def __init__(self, failing=(), stdout_map=None):
        self.calls: list[list[str]] = []
        self.failing = set(failing)
        self.stdout_map = stdout_map or {}

    def __call__(self, args, timeout_s=15.0):
        self.calls.append(list(args))
        joined = " ".join(args)
        code = 1 if any(token in joined for token in self.failing) else 0
        stdout = ""
        for needle, value in self.stdout_map.items():
            if needle in joined:
                stdout = value
                break
        return SimpleNamespace(stdout=stdout, returncode=code, stderr="")

    def commands(self) -> list[str]:
        return [" ".join(call) for call in self.calls]


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return None  # 一直活着

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def _profiler(device, *, available=True, port_busy=False, process=None):
    """构造一个不真起进程的 profiler：端口探测按 port_busy 回答。"""
    state = {"busy": port_busy}
    popen_calls = []

    def popen(args, **kwargs):
        popen_calls.append((args, kwargs))
        state["busy"] = True  # 起进程后端口变忙
        return process or FakeProcess()

    profiler = netprof.NetProfiler(
        adb_path="adb",
        serial="s1",
        mitmdump="/fake/mitmdump",
        call_device=device,
        popen=popen,
        sleep=lambda _s: None,
        now=lambda: 0.0,
        probe=lambda _p: "12.3.0" if available else None,
        which=lambda _n: None,
        in_use=lambda _port: state["busy"],
        env={},
    )
    profiler.popen_calls = popen_calls
    return profiler


def test_start_sets_reverse_then_proxy_and_stop_restores_in_reverse_order(tmp_path):
    device = FakeDevice()
    profiler = _profiler(device)

    session = profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)
    assert session.applied is True
    commands = device.commands()
    assert commands[0].endswith("reverse tcp:8080 tcp:8080")
    assert commands[1].endswith("settings put global http_proxy 127.0.0.1:8080")

    stopped = profiler.stop()

    # 恢复顺序与设置相反：先清系统代理，再拆 reverse，最后停进程
    assert device.commands()[2].endswith("settings put global http_proxy :0")
    assert device.commands()[3].endswith("reverse --remove tcp:8080")
    assert stopped.restored["deviceProxy"] is True
    assert stopped.restored["reverse"] is True
    assert stopped.restored["proxyProcess"] is True
    assert stopped.proxy_set is False and stopped.reverse_set is False


def test_start_none_profile_does_not_touch_device_or_proxy(tmp_path):
    device = FakeDevice()
    profiler = _profiler(device)

    session = profiler.start(netprof.build_profile("none"), work_dir=tmp_path)

    assert session.applied is True
    assert session.effective is True  # 无整形即无需代理证明
    assert device.calls == []
    assert profiler.popen_calls == []


def test_start_without_mitmproxy_degrades_with_hint_and_no_device_changes(tmp_path):
    device = FakeDevice()
    profiler = _profiler(device, available=False)

    session = profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)

    assert session.applied is False
    assert session.effective is False
    assert "mitmproxy" in session.setup_errors[0]
    assert "MOBILE_PERF_MITMDUMP" in session.hint
    assert device.calls == []
    assert "not_tested" not in session.setup_errors[0]  # 原因本身不夹带状态词


def test_start_fails_fast_when_port_busy(tmp_path):
    device = FakeDevice()
    profiler = _profiler(device, port_busy=True)

    session = profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)

    assert session.applied is False
    assert "已被占用" in session.setup_errors[0]
    assert profiler.popen_calls == []


def test_start_rolls_back_proxy_when_reverse_fails(tmp_path):
    device = FakeDevice(failing=("reverse tcp:8080 tcp:8080",))
    profiler = _profiler(device)

    session = profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)

    assert session.applied is False
    assert session.reverse_set is False
    assert session.proxy_set is False
    assert profiler.popen_calls  # 进程起过
    assert session.restored == {}  # 回滚不留待恢复项


def test_start_rolls_back_reverse_and_proxy_when_proxy_setting_fails(tmp_path):
    device = FakeDevice(failing=("http_proxy 127.0.0.1:8080",))
    profiler = _profiler(device)

    session = profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)

    assert session.applied is False
    assert session.proxy_set is False
    commands = device.commands()
    assert any("reverse --remove tcp:8080" in command for command in commands)  # 已回滚


def test_context_manager_restores_even_when_body_raises(tmp_path):
    device = FakeDevice()
    profiler = _profiler(device)

    with pytest.raises(RuntimeError, match="采集失败"):
        with profiler:
            profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)
            raise RuntimeError("采集失败")

    commands = device.commands()
    assert any(command.endswith("settings put global http_proxy :0") for command in commands)
    assert any(command.endswith("reverse --remove tcp:8080") for command in commands)


def test_stop_is_idempotent(tmp_path):
    device = FakeDevice()
    profiler = _profiler(device)
    profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)

    first = profiler.stop()
    calls_after_first = len(device.calls)
    second = profiler.stop()

    assert second is first
    assert len(device.calls) == calls_after_first  # 不再重复发恢复命令


def test_stop_without_start_is_safe():
    profiler = _profiler(FakeDevice())

    session = profiler.stop()

    assert session.applied is False


def test_double_start_raises(tmp_path):
    profiler = _profiler(FakeDevice())
    profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)

    with pytest.raises(netprof.NetProfileError, match="已在运行"):
        profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)


def test_session_evidence_comes_from_proxy_log_not_from_app_behaviour(tmp_path):
    """关键回归：环境设置成功但代理侧零连接 → effective=False 且原因如实。

    这正是"页面能打开不等于代理生效"的落点——判定只看代理侧日志。
    """
    device = FakeDevice()
    profiler = _profiler(device)

    profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)
    log_path = tmp_path / netprof.LOG_FILENAME
    log_path.write_text(
        json.dumps({"t": 1.0, "ev": "params", "latencyMs": 400}) + "\n", encoding="utf-8"
    )
    session = profiler.stop()

    assert session.applied is True
    assert session.evidence == netprof.EVIDENCE_NONE
    assert session.effective is False
    assert "代理侧日志未观察到任何连接" in session.not_tested_reason


def test_session_evidence_observed_when_proxy_log_has_traffic(tmp_path):
    device = FakeDevice()
    profiler = _profiler(device)

    profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)
    (tmp_path / netprof.LOG_FILENAME).write_text(
        "\n".join(
            _lines(
                {"t": 0.0, "ev": "tcp_start", "fid": "f1", "host": "api.test", "port": 443},
                {"t": 0.45, "ev": "tcp_message", "fid": "f1", "from_client": True, "size": 512},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    session = profiler.stop()

    assert session.effective is True
    assert session.not_tested_reason is None
    assert netprof.conn_duration_rows(session.log_summary)[0]["median"] == pytest.approx(450.0)


def test_addon_params_and_log_path_reach_subprocess_env(tmp_path):
    profiler = _profiler(FakeDevice())

    profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)

    args, kwargs = profiler.popen_calls[0]
    params = json.loads(kwargs["env"]["MOBILE_PERF_NETPARAMS"])
    assert params == {"latency_ms": 400.0, "down_kbps": 400.0, "up_kbps": 200.0,
                      "loss_pct": 2.0}
    assert kwargs["env"]["MOBILE_PERF_NETLOG"] == str(tmp_path / netprof.LOG_FILENAME)
    assert args[-1].endswith(netprof.ADDON_FILENAME)
    assert "--listen-port" in args


def test_spawn_failure_is_reported_and_not_retried(tmp_path):
    def popen(_args, **_kwargs):
        raise OSError("no such executable")

    profiler = netprof.NetProfiler(
        adb_path="adb", serial="s1", mitmdump="/fake/mitmdump", call_device=FakeDevice(),
        popen=popen, sleep=lambda _s: None, now=lambda: 0.0, probe=lambda _p: "12.3.0",
        which=lambda _n: None, in_use=lambda _p: False, env={},
    )

    session = profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)

    assert session.applied is False
    assert "代理启动失败" in session.setup_errors[0]


def test_process_exiting_during_startup_is_reported(tmp_path):
    class DeadProcess(FakeProcess):
        def poll(self):
            return 1  # 起来就退出

    profiler = netprof.NetProfiler(
        adb_path="adb", serial="s1", mitmdump="/fake/mitmdump", call_device=FakeDevice(),
        popen=lambda _a, **_k: DeadProcess(), sleep=lambda _s: None, now=lambda: 0.0,
        probe=lambda _p: "12.3.0", which=lambda _n: None, in_use=lambda _p: False, env={},
    )

    session = profiler.start(netprof.build_profile("weak"), work_dir=tmp_path)

    assert session.applied is False
    assert "提前退出" in session.setup_errors[0]


def test_addon_file_is_present_next_to_module():
    from pathlib import Path

    import mobile_perf

    addon = Path(mobile_perf.__file__).parent / netprof.ADDON_FILENAME
    assert addon.is_file()


# ---------- doctor ----------


def test_doctor_cleans_stale_proxy_and_verifies_cleanup():
    device = FakeDevice(
        stdout_map={
            "s1 shell settings get global http_proxy": "127.0.0.1:8080\n",
            "s1 reverse --list": "host-1 tcp:8080 tcp:8080\n",
        }
    )

    # 清理后复读：proxy 读回 :0（settings put 生效），reverse 已空
    def call(args, timeout_s=15.0):
        result = device(args, timeout_s)
        joined = " ".join(args)
        if len(device.calls) > 4:  # 前 4 条是「读+读+清+清」，之后是复读
            if joined.endswith("settings get global http_proxy"):
                result.stdout = ":0\n"
            elif joined.endswith("reverse --list"):
                result.stdout = ""
        return result

    report = netprof.doctor(call, "s1")

    assert report["staleProxy"] is True
    assert report["staleReverse"] is True
    assert report["cleaned"] is True
    assert report["proxyClean"] is True
    assert report["reverseClean"] is True
    commands = device.commands()
    assert any(command.endswith("settings put global http_proxy :0") for command in commands)
    assert any(command.endswith("reverse --remove tcp:8080") for command in commands)


def test_doctor_on_clean_device_changes_nothing():
    device = FakeDevice(
        stdout_map={
            "s1 shell settings get global http_proxy": ":0\n",
            "s1 reverse --list": "",
        }
    )

    report = netprof.doctor(device, "s1")

    assert report["cleaned"] is False
    assert report["proxyClean"] is True
    assert report["reverseClean"] is True
    assert len(device.calls) == 2  # 只读两次，无写操作


def test_doctor_reports_when_cleanup_did_not_take_effect():
    """清理命令返回 0 不等于设备真的干净——复读仍脏必须如实报告。"""
    device = FakeDevice(
        stdout_map={
            "s1 shell settings get global http_proxy": "127.0.0.1:8080\n",
            "s1 reverse --list": "",
        }
    )

    report = netprof.doctor(device, "s1")

    assert report["cleaned"] is True
    assert report["proxyClean"] is False  # 复读仍是旧值


def test_doctor_ignores_reverse_entries_for_other_ports():
    device = FakeDevice(
        stdout_map={
            "s1 shell settings get global http_proxy": ":0\n",
            "s1 reverse --list": "host-1 tcp:9999 tcp:9999\n",
        }
    )

    report = netprof.doctor(device, "s1")

    assert report["staleReverse"] is False
    assert report["cleaned"] is False


# ---------- 真实 mitmproxy 集成（可选：未装则跳过） ----------


def _real_mitmdump() -> str | None:
    """本机是否真有 mitmdump（读真实环境：PATH 与 MOBILE_PERF_MITMDUMP）。"""
    availability = netprof.find_mitmproxy()
    return availability.executable if availability.available else None


MITMDUMP = _real_mitmdump()


@pytest.mark.skipif(MITMDUMP is None, reason="本机无可用 mitmdump（Python ≥3.12 独立 venv）")
def test_real_proxy_injects_latency_and_writes_evidence(tmp_path):
    """真起 mitmproxy：整形后连接耗时明显变长，且代理侧日志给出证据。

    用本地 http.server 作目标，走 HTTP 代理路径（curl 的 --proxy 语义），
    避免依赖外网；验证 addon 确实加载、日志确实产出、延迟确实生效。
    """
    import http.server
    import threading
    import urllib.request

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        upstream_port = probe.getsockname()[1]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib 命名
            body = b"ok" * 100
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", upstream_port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    device = FakeDevice()
    profiler = netprof.NetProfiler(
        adb_path="adb", serial="s1", call_device=device, mitmdump=MITMDUMP,
        which=lambda _n: None, env={},
    )
    profiler.port = _free_port()
    try:
        session = profiler.start(netprof.build_profile("custom", {
            "latency_ms": 300, "down_kbps": 0, "up_kbps": 0, "loss_pct": 0,
        }), work_dir=tmp_path)
        assert session.applied is True, session.setup_errors

        proxy = f"http://127.0.0.1:{profiler.port}"
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy})
        )
        opener.open(f"http://127.0.0.1:{upstream_port}/", timeout=30).read()
        stopped = profiler.stop()
    finally:
        server.shutdown()
        profiler.stop()

    summary = stopped.log_summary
    assert summary.connections >= 1
    assert stopped.effective is True
    assert summary.params is not None and summary.params["latencyMs"] == 300.0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_port_in_use_detects_listening_socket():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert netprof.port_in_use(port) is True

    assert netprof.port_in_use(port) is False


def test_dump_json_is_stable():
    payload = {"b": 1, "a": [1, 2]}

    assert json.loads(netprof.dump_json(payload)) == payload


def test_netprof_does_not_import_mitmproxy_in_process():
    """进程边界：主进程不 import mitmproxy（它要求 Python ≥3.12，本项目 ≥3.10）。

    addon 由 mitmdump 子进程加载，故 ``netprof.py`` 源码里不得出现 import mitmproxy；
    反过来，addon 必须真的 import mitmproxy——它只在该子进程里跑。
    """
    from pathlib import Path

    package = Path(netprof.__file__).resolve().parent
    orchestrator = (package / "netprof.py").read_text(encoding="utf-8")
    addon = (package / netprof.ADDON_FILENAME).read_text(encoding="utf-8")

    assert "import mitmproxy" not in orchestrator
    assert "from mitmproxy" in addon
