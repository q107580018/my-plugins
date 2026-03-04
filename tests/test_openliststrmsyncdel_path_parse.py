import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


PLUGIN_FILE = Path(
    "/Users/mac/Documents/my-plugins/plugins.v2/openliststrmsyncdel/__init__.py"
)


def load_plugin_class():
    app = types.ModuleType("app")
    sys.modules["app"] = app

    core = types.ModuleType("app.core")
    sys.modules["app.core"] = core

    config = types.ModuleType("app.core.config")
    config.settings = types.SimpleNamespace(LIBRARY_PATH="")
    sys.modules["app.core.config"] = config

    event = types.ModuleType("app.core.event")

    class DummyEventManager:
        def register(self, *_):
            def deco(func):
                return func

            return deco

    event.Event = object
    event.eventmanager = DummyEventManager()
    sys.modules["app.core.event"] = event

    log = types.ModuleType("app.log")

    class DummyLogger:
        def __init__(self):
            self.records = []

        def _record(self, level, *args, **kwargs):
            msg = args[0] if args else ""
            self.records.append((level, str(msg)))

        def info(self, *_, **__):
            self._record("info", *_)

        def warning(self, *_, **__):
            self._record("warning", *_)

        def warn(self, *_, **__):
            self._record("warn", *_)

        def error(self, *_, **__):
            self._record("error", *_)

        def debug(self, *_, **__):
            self._record("debug", *_)

    log.logger = DummyLogger()
    sys.modules["app.log"] = log

    plugins = types.ModuleType("app.plugins")

    class Base:
        def get_data(self, *_):
            return None

        def save_data(self, *_):
            return None

    plugins._PluginBase = Base
    sys.modules["app.plugins"] = plugins

    schemas = types.ModuleType("app.schemas")
    sys.modules["app.schemas"] = schemas

    types_mod = types.ModuleType("app.schemas.types")

    class EventType:
        TransferComplete = "TransferComplete"
        DownloadAdded = "DownloadAdded"
        DownloadFileDeleted = "DownloadFileDeleted"
        PluginAction = "PluginAction"
        WebhookMessage = "WebhookMessage"

    types_mod.EventType = EventType
    sys.modules["app.schemas.types"] = types_mod

    utils = types.ModuleType("app.utils")
    sys.modules["app.utils"] = utils

    http = types.ModuleType("app.utils.http")

    class RequestUtils:
        def __init__(self, *_, **__):
            return None

        def post_res(self, *_, **__):
            return None

    http.RequestUtils = RequestUtils
    sys.modules["app.utils.http"] = http

    spec = importlib.util.spec_from_file_location("openlist_plugin", PLUGIN_FILE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.OpenListStrmSyncDel, module, log.logger


class TestPathParse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin_cls, cls.plugin_module, cls.logger = load_plugin_class()

    def setUp(self):
        self.plugin = self.plugin_cls()
        self.logger.records.clear()

    def test_parse_monitor_paths_strips_wrapping_quotes(self):
        raw = '“/115\n/quark/videos”'
        result = self.plugin._OpenListStrmSyncDel__parse_monitor_paths(raw)
        self.assertEqual(result, ["/115", "/quark/videos"])

    def test_parse_local_paths_strips_wrapping_quotes(self):
        raw = '“/media/videos_strm/115_strm\n/media/videos_strm/quark_strm”'
        result = self.plugin._OpenListStrmSyncDel__parse_local_paths(raw)
        self.assertEqual(
            result,
            ["/media/videos_strm/115_strm", "/media/videos_strm/quark_strm"],
        )

    def test_warn_when_strm_deleted_and_cache_missed(self):
        self.plugin._enabled = True
        self.plugin._token = "token"
        self.plugin._path_prefixes = ["/quark/videos"]
        self.plugin._library_path_roots = ["/media/videos_strm/quark_strm"]
        self.plugin._strm_cache = {}

        missing_strm = "/media/videos_strm/quark_strm/示例/示例.strm"
        self.plugin._OpenListStrmSyncDel__handle_delete_event_path(
            missing_strm, "DownloadFileDeleted"
        )

        warning_logs = [
            msg
            for level, msg in self.logger.records
            if level in ["warning", "warn"]
        ]
        self.assertTrue(
            any("缓存未命中" in msg and missing_strm in msg for msg in warning_logs),
            warning_logs,
        )

    def test_cache_manual_strm_on_download_added(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_root = Path(tmpdir) / "quark_strm"
            strm_file = lib_root / "女人的战争：搬来的男人" / "clip.strm"
            strm_file.parent.mkdir(parents=True, exist_ok=True)
            strm_file.write_text(
                "http://192.168.1.189:5244/d/quark/videos/女人的战争：搬来的男人/clip.mp4?sign=abc",
                encoding="utf-8",
            )

            self.plugin._enabled = True
            self.plugin._token = "token"
            self.plugin._path_prefixes = ["/quark/videos"]
            self.plugin._library_path_roots = [str(lib_root)]
            self.plugin._strm_cache = {}
            self.plugin._target_cache = {}

            event = types.SimpleNamespace(event_data={"src": str(strm_file)})
            self.plugin.on_download_added(event)

            self.assertIn(str(strm_file), self.plugin._strm_cache)
            cache_item = self.plugin._strm_cache[str(strm_file)]
            self.assertEqual(cache_item.get("target_path"), "/quark/videos/女人的战争：搬来的男人/clip.mp4")

    def test_cache_manual_strm_on_webhook_library_added(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_root = Path(tmpdir) / "quark_strm"
            strm_file = lib_root / "女人的战争：搬来的男人" / "clip.strm"
            strm_file.parent.mkdir(parents=True, exist_ok=True)
            strm_file.write_text(
                "http://192.168.1.189:5244/d/quark/videos/女人的战争：搬来的男人/clip.mp4?sign=abc",
                encoding="utf-8",
            )

            self.plugin._enabled = True
            self.plugin._token = "token"
            self.plugin._path_prefixes = ["/quark/videos"]
            self.plugin._library_path_roots = [str(lib_root)]
            self.plugin._strm_cache = {}
            self.plugin._target_cache = {}

            event = types.SimpleNamespace(
                event_data={"event": "library.added", "item_path": str(strm_file)}
            )
            self.plugin.on_webhook_message(event)

            self.assertIn(str(strm_file), self.plugin._strm_cache)

    def test_skip_delete_when_download_deleted_event_but_file_still_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_root = Path(tmpdir) / "quark_strm"
            strm_file = lib_root / "误删风险" / "clip.strm"
            strm_file.parent.mkdir(parents=True, exist_ok=True)
            strm_file.write_text("http://example.com/d/quark/videos/误删风险/clip.mp4", encoding="utf-8")

            self.plugin._enabled = True
            self.plugin._token = "token"
            self.plugin._path_prefixes = ["/quark/videos"]
            self.plugin._library_path_roots = [str(lib_root)]

            called = {"value": False}

            def fake_handle(*_, **__):
                called["value"] = True

            self.plugin._OpenListStrmSyncDel__handle_delete_event_path = fake_handle
            event = types.SimpleNamespace(event_data={"src": str(strm_file)})
            self.plugin.on_download_file_deleted(event)

            self.assertFalse(called["value"])
            warning_logs = [
                msg
                for level, msg in self.logger.records
                if level in ["warning", "warn"]
            ]
            self.assertTrue(
                any("疑似误触发" in msg and str(strm_file) in msg for msg in warning_logs),
                warning_logs,
            )

    def test_continue_delete_when_download_deleted_event_and_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_root = Path(tmpdir) / "quark_strm"
            strm_file = lib_root / "正常删除" / "clip.strm"
            strm_file.parent.mkdir(parents=True, exist_ok=True)
            strm_file.write_text("http://example.com/d/quark/videos/正常删除/clip.mp4", encoding="utf-8")
            strm_file.unlink()

            self.plugin._enabled = True
            self.plugin._token = "token"
            self.plugin._path_prefixes = ["/quark/videos"]
            self.plugin._library_path_roots = [str(lib_root)]

            called = {"value": False}

            def fake_handle(*_, **__):
                called["value"] = True

            self.plugin._OpenListStrmSyncDel__handle_delete_event_path = fake_handle
            event = types.SimpleNamespace(event_data={"src": str(strm_file)})
            self.plugin.on_download_file_deleted(event)

            self.assertTrue(called["value"])


if __name__ == "__main__":
    unittest.main()
