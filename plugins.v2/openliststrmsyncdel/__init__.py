import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from app.core.config import settings
from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.utils.http import RequestUtils


class OpenListStrmSyncDel(_PluginBase):
    # 插件名称
    plugin_name = "同步删除strm指向的openlist源文件"
    # 插件描述
    plugin_desc = "监听strm删除事件，解析strm内容并删除OpenList中的源文件。"
    # 插件图标
    plugin_icon = "Alist_B.png"
    # 插件版本
    plugin_version = "1.7"
    # 插件作者
    plugin_author = "Tony Stark"
    # 作者主页
    author_url = "https://github.com/q107580018"
    # 插件配置项ID前缀
    plugin_config_prefix = "openliststrmsyncdel_"
    # 加载顺序
    plugin_order = 25
    # 可使用的用户级别
    auth_level = 1

    _enabled = False
    _token = ""
    _monitor_source_paths = ""
    _library_paths = ""
    _library_path_roots: List[str] = []
    _path_prefixes: List[str] = []
    _strm_cache: Dict[str, Dict[str, Any]] = {}
    _target_cache: Dict[str, Dict[str, Any]] = {}
    _recent_deleted: Dict[str, float] = {}

    _cache_key = "strm_content_map"
    _cache_limit = 3000
    _history_key = "history"
    _history_limit = 200
    _recent_ttl_seconds = 300

    def init_plugin(self, config: dict = None):
        self._enabled = False
        self._token = ""
        self._monitor_source_paths = ""
        self._library_paths = ""
        self._library_path_roots = []
        self._path_prefixes = []
        self._recent_deleted = {}
        self._strm_cache = {}
        self._target_cache = {}

        if config:
            self._enabled = config.get("enabled", False)
            self._token = (config.get("token") or "").strip()
            self._monitor_source_paths = config.get("monitor_source_paths") or ""
            self._library_paths = (
                config.get("library_paths") or config.get("library_path") or ""
            ).strip()
            self._path_prefixes = self.__parse_monitor_paths(self._monitor_source_paths)
        self._library_path_roots = self.__get_library_paths()

        self.__load_cache()
        if self._enabled:
            logger.info(
                f"已启用，监控源文件路径前缀：{self._path_prefixes if self._path_prefixes else '未配置'}"
            )
            logger.info(
                f"已启用，strm资源目录：{self._library_path_roots if self._library_path_roots else '未配置'}"
            )
            if self.get_state():
                self.__warmup_strm_cache()

    def get_state(self) -> bool:
        return bool(
            self._enabled
            and self._token
            and self._path_prefixes
            and self._library_path_roots
        )

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/history",
                "endpoint": self.api_history,
                "methods": ["GET"],
                "summary": "获取删除历史",
                "description": "返回插件最近删除历史记录（默认20条）。",
            },
            {
                "path": "/delete_history",
                "endpoint": self.api_clear_history,
                "methods": ["GET", "POST"],
                "summary": "删除历史（兼容路径）",
                "description": "兼容旧事件配置的清空历史接口。",
            },
            {
                "path": "/clear_history",
                "endpoint": self.api_clear_history,
                "methods": ["POST", "GET"],
                "summary": "清空删除历史",
                "description": "清空插件删除历史记录。",
            },
        ]

    def api_history(
        self,
        limit: int = 20,
        api_token: str = "",
        request: Any = None,
        **kwargs,
    ) -> Dict[str, Any]:
        token_value = self.__resolve_api_token(
            api_token=api_token,
            request=request,
            kwargs=kwargs,
        )
        if not self.__verify_api_token(token_value):
            return {"success": False, "message": "API_TOKEN校验失败"}

        history = self.get_data(self._history_key) or []
        if not isinstance(history, list):
            history = []

        if not isinstance(limit, int):
            raw_limit = kwargs.get("limit")
            if isinstance(raw_limit, str) and raw_limit.isdigit():
                limit = int(raw_limit)

        if not isinstance(limit, int) or limit <= 0:
            limit = 20
        limit = min(limit, self._history_limit)

        records = [item for item in history if isinstance(item, dict)][:limit]
        return {
            "success": True,
            "message": "ok",
            "total": len(history),
            "limit": limit,
            "data": records,
        }

    def api_clear_history(
        self,
        api_token: str = "",
        request: Any = None,
        **kwargs,
    ) -> Dict[str, Any]:
        token_value = self.__resolve_api_token(
            api_token=api_token,
            request=request,
            kwargs=kwargs,
        )
        if not self.__verify_api_token(token_value):
            return {"success": False, "message": "API_TOKEN校验失败"}

        self.save_data(self._history_key, [])
        return {"success": True, "message": "删除历史已清空"}

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "token",
                                            "label": "OpenList Token（必填）",
                                            "type": "password",
                                            "placeholder": "OpenList API Token（可填原始Token或Bearer Token）",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "monitor_source_paths",
                                            "label": "监控的源文件路径（OpenList路径，必填）",
                                            "rows": 3,
                                            "placeholder": "/115\n/影视库/电影",
                                            "hint": "一行一个OpenList路径前缀；这里不是本地/media路径。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "library_paths",
                                            "label": "strm资源目录（本地路径，必填）",
                                            "rows": 2,
                                            "placeholder": "/media/videos_strm/115_strm\n/media/videos_strm/aliyun_strm",
                                            "hint": "仅这些目录内的.strm删除事件会被处理；可多行填写，留空才回退系统LIBRARY_PATH。",
                                            "persistent-hint": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "参数说明："
                                            "1) OpenList Token：用于调用OpenList删除接口；"
                                            "2) 监控的源文件路径：填写OpenList内路径前缀（如/115），不是本地strm目录；"
                                            "3) strm资源目录：填写MoviePilot可访问的本地strm目录（如/media/videos_strm/115_strm）；"
                                            "4) 执行删除条件：事件路径属于strm资源目录且为.strm文件，并且解析出的OpenList目标路径命中监控路径。",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "token": "",
            "monitor_source_paths": "",
            "library_paths": "",
        }

    def get_page(self) -> List[dict]:
        history_data = self.get_data(self._history_key) or []
        if not isinstance(history_data, list):
            history_data = []

        history_items = [item for item in history_data if isinstance(item, dict)][:20]
        is_ready = self.get_state()
        status_text = (
            "已启用并就绪"
            if is_ready
            else "未就绪（请检查启用状态、token、监控路径、strm资源目录）"
        )
        status_type = "success" if is_ready else "warning"

        history_panel: List[dict] = []
        if history_items:
            for index, item in enumerate(history_items, start=1):
                event_name = str(item.get("event") or "-")
                event_path = str(item.get("event_path") or "-")
                target_path = str(item.get("target_path") or "-")
                openlist_url = str(item.get("openlist_url") or "-")
                event_time = str(item.get("time") or "-")
                history_panel.append(
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "density": "compact",
                            "text": f"#{index} [{event_time}] {event_name}\nOpenList目标: {target_path}\nstrm路径: {event_path}\nOpenList地址: {openlist_url}",
                        },
                    }
                )
        else:
            history_panel = [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": "暂无删除历史记录",
                    },
                }
            ]

        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": status_type,
                                    "variant": "tonal",
                                    "text": f"插件状态：{status_text} | 版本：v{self.plugin_version}",
                                },
                            }
                        ],
                    },
                ],
            },
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 9},
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "info",
                                    "variant": "tonal",
                                    "text": f"最近删除历史（最多展示20条，已记录 {len(history_data)} 条），当前缓存 {len(self._strm_cache)} 条映射",
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 3},
                        "content": [
                            {
                                "component": "VBtn",
                                "props": {
                                    "color": "warning",
                                    "variant": "tonal",
                                    "text": "清空历史记录",
                                    "prepend-icon": "mdi-delete-sweep",
                                    "block": True,
                                },
                                "events": {
                                    "click": {
                                        "api": "/plugin/OpenListStrmSyncDel/delete_history",
                                        "method": "GET",
                                    }
                                },
                            }
                        ],
                    },
                ],
            },
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": history_panel,
                    }
                ],
            },
        ]

    def stop_service(self):
        self._recent_deleted = {}

    @eventmanager.register(EventType.TransferComplete)
    def cache_strm_content(self, event: Event):
        """
        入库后缓存strm内容，保证后续删除事件触发时即使strm文件已被删除也可回溯。
        """
        if not self._enabled or not event or not event.event_data:
            return
        transfer_info = self.__safe_get(event.event_data, "transferinfo")
        file_list = self.__safe_get(transfer_info, "file_list_new")
        if not file_list:
            return

        changed = False
        for file_path in file_list:
            strm_path = self.__normalize_local_path(file_path)
            if not strm_path or not strm_path.lower().endswith(".strm"):
                continue
            content = self.__read_strm_content(Path(strm_path))
            if not content:
                continue
            base_url, target_path = self.__parse_openlist_target(content)
            if not base_url or not target_path:
                continue
            self.__upsert_cache(
                strm_path=strm_path,
                content=content,
                base_url=base_url,
                target_path=target_path,
            )
            changed = True

        if changed:
            self.__persist_cache()

    @eventmanager.register(EventType.DownloadFileDeleted)
    def on_download_file_deleted(self, event: Event):
        """
        处理源文件删除事件
        """
        if not event:
            return
        src = self.__safe_get(event.event_data, "src")
        logger.info(f"收到事件 DownloadFileDeleted，src={src}")
        if not self.get_state():
            logger.warning(
                f"状态未就绪，已跳过（请检查启用状态、token、监控路径、strm资源目录）"
            )
            return
        self.__handle_delete_event_path(src, "DownloadFileDeleted")

    @eventmanager.register(EventType.PluginAction)
    def on_plugin_action(self, event: Event):
        """
        兼容MediaSyncDel发送的删除动作
        """
        if not event:
            return
        event_data = event.event_data
        if self.__safe_get(event_data, "action") != "networkdisk_del":
            return
        media_path = self.__safe_get(event_data, "media_path")
        logger.info(f"收到事件 PluginAction.networkdisk_del，media_path={media_path}")
        if not self.get_state():
            logger.warning(
                f"状态未就绪，已跳过（请检查启用状态、token、监控路径、strm资源目录）"
            )
            return
        self.__handle_delete_event_path(media_path, "PluginAction.networkdisk_del")

    @eventmanager.register(EventType.WebhookMessage)
    def on_webhook_message(self, event: Event):
        """
        兼容媒体服务器删除事件
        """
        if not event:
            return
        event_data = event.event_data
        event_name = str(self.__safe_get(event_data, "event") or "").lower()
        if event_name not in ["library.deleted", "media_del"]:
            return
        media_path = self.__safe_get(event_data, "item_path")
        logger.info(f"收到事件 WebhookMessage.{event_name}，item_path={media_path}")
        if not self.get_state():
            logger.warning(
                f"状态未就绪，已跳过（请检查启用状态、token、监控路径、strm资源目录）"
            )
            return
        self.__handle_delete_event_path(media_path, f"WebhookMessage.{event_name}")

    def __handle_delete_event_path(self, raw_path: Optional[str], event_name: str):
        if not raw_path:
            return
        event_path = self.__normalize_local_path(raw_path)
        if not event_path:
            return

        # 仅处理媒体库目录内的strm删除事件
        if not event_path.lower().endswith(".strm"):
            logger.debug(f"跳过事件 {event_name}，非strm文件：{event_path}")
            return
        if not self.__is_in_library_paths(event_path):
            logger.debug(f"跳过事件 {event_name}，不在strm资源目录：{event_path}")
            return

        base_url, target_path = self.__resolve_target_from_strm(event_path)

        if not base_url or not target_path:
            logger.debug(f"跳过事件 {event_name}，无法解析OpenList目标：{event_path}")
            return
        if not self.__in_monitor_paths(target_path):
            logger.debug(f"跳过未命中监控路径的文件：{target_path}")
            return
        if self.__is_recently_deleted(target_path):
            logger.debug(f"跳过短时间重复删除：{target_path}")
            return

        if self.__remove_openlist_file(base_url=base_url, target_path=target_path):
            logger.info(f"删除成功：{target_path}（事件：{event_name}）")
            self.__cleanup_empty_parent_dirs(base_url=base_url, file_path=target_path)
            self._recent_deleted[target_path] = time.time()
            self.__save_history(
                event_name=event_name,
                event_path=event_path,
                target_path=target_path,
                base_url=base_url,
            )
            if event_path.lower().endswith(".strm"):
                self.__remove_cache_by_strm_path(event_path)
        else:
            logger.error(f"删除失败：{target_path}（事件：{event_name}）")

    def __resolve_target_from_strm(
        self, strm_path: str
    ) -> Tuple[Optional[str], Optional[str]]:
        content = self.__read_strm_content(Path(strm_path))
        base_url, target_path = self.__parse_openlist_target(content or "")
        if not base_url and target_path:
            base_url = self.__latest_base_url()

        if base_url and target_path and content:
            self.__upsert_cache(
                strm_path=strm_path,
                content=content,
                base_url=base_url,
                target_path=target_path,
            )
            self.__persist_cache()
            return base_url, target_path

        cache_item = self._strm_cache.get(strm_path)
        if cache_item:
            base_url = cache_item.get("base_url")
            target_path = cache_item.get("target_path")
            if base_url and target_path:
                return base_url, target_path
        return None, None

    def __resolve_target_from_path(
        self, path_value: str
    ) -> Tuple[Optional[str], Optional[str]]:
        # 兼容事件直接给出URL
        base_url, target_path = self.__parse_openlist_target(path_value)
        if base_url and target_path:
            return base_url, target_path

        target_path = self.__normalize_openlist_path(path_value)
        if not target_path:
            return None, None

        cache_item = self._target_cache.get(target_path)
        if cache_item and cache_item.get("base_url"):
            return cache_item.get("base_url"), target_path

        # 若事件给出的就是源文件路径，且已缓存过base_url，则按最近一次base_url处理
        latest_base_url = self.__latest_base_url()
        if latest_base_url and self.__in_monitor_paths(target_path):
            logger.warn(
                f"未能从事件路径确定OpenList地址，使用最近一次地址：{latest_base_url}"
            )
            return latest_base_url, target_path

        return None, None

    def __remove_openlist_file(self, base_url: str, target_path: str) -> bool:
        return self.__remove_openlist_item(
            base_url=base_url, item_path=target_path, not_found_as_success=True
        )

    def __cleanup_empty_parent_dirs(self, base_url: str, file_path: str):
        monitor_root = self.__get_monitor_root_for_target(file_path)
        if not monitor_root:
            return

        current_dir = self.__normalize_openlist_path(
            str(PurePosixPath(file_path).parent)
        )
        while current_dir and current_dir != "/" and current_dir != monitor_root:
            if not current_dir.startswith(f"{monitor_root}/"):
                break
            # 如果配置的是根目录监控，保护一级目录，避免误删 /115 这类入口目录
            if monitor_root == "/" and self.__path_depth(current_dir) <= 1:
                break

            if not self.__is_openlist_dir_empty(
                base_url=base_url, dir_path=current_dir
            ):
                break

            if not self.__remove_openlist_item(
                base_url=base_url, item_path=current_dir, not_found_as_success=True
            ):
                logger.warning(f"空目录删除失败，停止向上清理：{current_dir}")
                break

            logger.info(f"已删除空目录：{current_dir}")
            parent_dir = self.__normalize_openlist_path(
                str(PurePosixPath(current_dir).parent)
            )
            if parent_dir == current_dir:
                break
            current_dir = parent_dir

    def __is_openlist_dir_empty(self, base_url: str, dir_path: str) -> bool:
        payload = {
            "path": dir_path,
            "password": "",
            "page": 1,
            "per_page": 1,
            "refresh": False,
        }
        response = self.__openlist_post(
            base_url=base_url, api_path="/api/fs/list", payload=payload
        )
        if not response:
            logger.warning(f"无法查询目录内容，跳过目录删除：{dir_path}")
            return False

        if not response.ok:
            logger.warning(
                f"查询目录失败，跳过目录删除：{dir_path}，HTTP {response.status_code}"
            )
            return False

        try:
            body = response.json() or {}
        except Exception:
            logger.warning(f"查询目录返回非JSON，跳过目录删除：{dir_path}")
            return False

        code = body.get("code")
        if code not in [None, 0, 200]:
            msg = str(body.get("message") or body.get("msg") or "").strip()
            logger.warning(
                f"查询目录返回异常 code={code} msg={msg}，跳过目录删除：{dir_path}"
            )
            return False

        data = body.get("data")
        if isinstance(data, dict):
            for key in ["content", "files", "items"]:
                value = data.get(key)
                if isinstance(value, list):
                    return len(value) == 0
            for key in ["total", "count", "obj_count"]:
                value = data.get(key)
                if isinstance(value, int):
                    return value == 0
                if isinstance(value, str) and value.isdigit():
                    return int(value) == 0
            # 未识别到明确字段时，为安全起见按非空处理
            return False
        if isinstance(data, list):
            return len(data) == 0
        return False

    def __remove_openlist_item(
        self, base_url: str, item_path: str, not_found_as_success: bool = False
    ) -> bool:
        item_path = self.__normalize_openlist_path(item_path)
        if not item_path or item_path == "/":
            return False

        posix_path = PurePosixPath(item_path)
        item_name = posix_path.name
        if not item_name:
            return False
        dir_path = self.__normalize_openlist_path(str(posix_path.parent)) or "/"

        payload = {"dir": dir_path, "names": [item_name]}
        response = self.__openlist_post(
            base_url=base_url, api_path="/api/fs/remove", payload=payload
        )
        if not response:
            return False
        if not response.ok:
            logger.error(
                f"OpenList请求失败：HTTP {response.status_code} - {response.text}"
            )
            return False

        try:
            body = response.json() or {}
        except Exception:
            body = {}

        code = body.get("code")
        msg = str(body.get("message") or body.get("msg") or "").strip()
        if code not in [None, 0, 200]:
            if not_found_as_success and "not found" in msg.lower():
                logger.warn(f"目标不存在，视为成功：{item_path}")
                return True
            logger.error(f"OpenList返回异常 code={code} msg={msg}")
            return False
        return True

    def __openlist_post(self, base_url: str, api_path: str, payload: dict):
        url = f"{base_url.rstrip('/')}{api_path}"
        headers = {"Authorization": self._token, "Content-Type": "application/json"}
        response = RequestUtils(headers=headers).post_res(url, json=payload)
        if (
            (not response or not response.ok)
            and self._token
            and not self._token.lower().startswith("bearer ")
        ):
            headers["Authorization"] = f"Bearer {self._token}"
            response = RequestUtils(headers=headers).post_res(url, json=payload)
        return response

    def __get_monitor_root_for_target(self, target_path: str) -> Optional[str]:
        target_path = self.__normalize_openlist_path(target_path)
        if not target_path:
            return None
        candidates = []
        for prefix in self._path_prefixes:
            if (
                prefix == "/"
                or target_path == prefix
                or target_path.startswith(f"{prefix}/")
            ):
                candidates.append(prefix)
        if not candidates:
            return None
        return max(candidates, key=len)

    @staticmethod
    def __path_depth(path_value: str) -> int:
        path_value = str(path_value or "")
        if not path_value or path_value == "/":
            return 0
        return len([part for part in path_value.split("/") if part])

    def __load_cache(self):
        cache_data = self.get_data(self._cache_key)
        if not isinstance(cache_data, dict):
            return

        for strm_path, item in cache_data.items():
            if not strm_path:
                continue
            strm_path = self.__normalize_local_path(strm_path)

            if isinstance(item, dict):
                content = (item.get("content") or "").strip()
                base_url = (item.get("base_url") or "").strip()
                target_path = self.__normalize_openlist_path(
                    item.get("target_path") or ""
                )
                ts = int(item.get("ts") or time.time())
            else:
                content = str(item).strip()
                base_url, target_path = self.__parse_openlist_target(content)
                ts = int(time.time())

            if not content or not base_url or not target_path:
                continue

            cache_item = {
                "content": content,
                "base_url": base_url,
                "target_path": target_path,
                "ts": ts,
            }
            self._strm_cache[strm_path] = cache_item
            self._target_cache[target_path] = cache_item

    def __upsert_cache(
        self, strm_path: str, content: str, base_url: str, target_path: str
    ):
        strm_path = self.__normalize_local_path(strm_path)
        target_path = self.__normalize_openlist_path(target_path)
        if not strm_path or not base_url or not target_path:
            return

        cache_item = {
            "content": content.strip(),
            "base_url": base_url.strip(),
            "target_path": target_path,
            "ts": int(time.time()),
        }
        self._strm_cache[strm_path] = cache_item
        self._target_cache[target_path] = cache_item

    def __remove_cache_by_strm_path(self, strm_path: str):
        cache_item = self._strm_cache.pop(strm_path, None)
        if cache_item:
            target_path = cache_item.get("target_path")
            if target_path and self._target_cache.get(target_path) == cache_item:
                self._target_cache.pop(target_path, None)
            self.__persist_cache()

    def __warmup_strm_cache(self):
        """
        启动时扫描媒体库中的strm文件，建立“本地strm路径 -> OpenList目标路径”映射。
        解决历史strm在删除时文件已不存在导致无法解析的问题。
        """
        scan_roots = self._library_path_roots
        if not scan_roots:
            logger.warning(
                f"未配置strm资源目录（library_paths/LIBRARY_PATH），跳过strm预扫描"
            )
            return
        logger.info(f"strm预扫描开始，目录：{scan_roots}")

        scanned = 0
        cached = 0
        changed = False

        for root in scan_roots:
            root_path = Path(root)
            if not root_path.exists() or not root_path.is_dir():
                logger.warning(f"strm预扫描目录不存在或不可访问，已跳过：{root}")
                continue
            root_scanned = 0
            root_cached = 0
            try:
                for strm_file in root_path.rglob("*.strm"):
                    scanned += 1
                    root_scanned += 1
                    strm_path = self.__normalize_local_path(strm_file)
                    if strm_path in self._strm_cache:
                        continue
                    content = self.__read_strm_content(strm_file)
                    if not content:
                        continue
                    base_url, target_path = self.__parse_openlist_target(content)
                    if not base_url or not target_path:
                        continue
                    if not self.__in_monitor_paths(target_path):
                        continue
                    self.__upsert_cache(
                        strm_path=strm_path,
                        content=content,
                        base_url=base_url,
                        target_path=target_path,
                    )
                    cached += 1
                    root_cached += 1
                    changed = True
            except Exception as err:
                logger.error(f"扫描目录失败：{root}，原因：{err}")
            logger.info(
                f"strm预扫描目录完成：{root}，扫描 {root_scanned} 个，新增缓存 {root_cached} 个"
            )

        if changed:
            self.__persist_cache()
        logger.info(f"strm预扫描完成，扫描 {scanned} 个，新增缓存 {cached} 个")

    def __get_library_paths(self) -> List[str]:
        custom_paths = self.__parse_local_paths(self._library_paths)
        if custom_paths:
            return custom_paths

        lib_value = getattr(settings, "LIBRARY_PATH", None)
        return self.__parse_local_paths(lib_value)

    def __is_in_library_paths(self, event_path: str) -> bool:
        if not event_path:
            return False
        normalized_event = self.__normalize_local_path(event_path)
        if not normalized_event:
            return False
        normalized_event = normalized_event.rstrip("/") or "/"
        for root in self._library_path_roots:
            if normalized_event == root or normalized_event.startswith(f"{root}/"):
                return True
        return False

    @staticmethod
    def __parse_local_paths(path_value: Any) -> List[str]:
        if not path_value:
            return []
        candidates = []
        if isinstance(path_value, (list, tuple, set)):
            candidates.extend([str(v).strip() for v in path_value if str(v).strip()])
        else:
            raw = str(path_value)
            for sep in [",", "，", ";", "；"]:
                raw = raw.replace(sep, "\n")
            lines = raw.splitlines()
            candidates.extend([line.strip() for line in lines if line.strip()])

        seen = set()
        result = []
        for item in candidates:
            normalized = item.replace("\\", "/")
            while "//" in normalized:
                normalized = normalized.replace("//", "/")
            if len(normalized) > 1 and normalized.endswith("/"):
                normalized = normalized.rstrip("/")
            if normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def __persist_cache(self):
        if len(self._strm_cache) > self._cache_limit:
            keep_items = sorted(
                self._strm_cache.items(),
                key=lambda item: item[1].get("ts", 0),
                reverse=True,
            )[: self._cache_limit]
            self._strm_cache = dict(keep_items)
            self._target_cache = {
                item.get("target_path"): item
                for item in self._strm_cache.values()
                if item.get("target_path")
            }
        self.save_data(self._cache_key, self._strm_cache)

    def __save_history(
        self, event_name: str, event_path: str, target_path: str, base_url: str
    ):
        history = self.get_data(self._history_key) or []
        history.insert(
            0,
            {
                "event": event_name,
                "event_path": event_path,
                "target_path": target_path,
                "openlist_url": base_url,
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            },
        )
        self.save_data(self._history_key, history[: self._history_limit])

    @staticmethod
    def __verify_api_token(api_token: str = "") -> bool:
        expected = str(getattr(settings, "API_TOKEN", "") or "").strip()
        if not expected:
            return True

        provided = str(api_token or "").strip()
        if not provided:
            return True
        return provided == expected

    @staticmethod
    def __resolve_api_token(
        api_token: Any = "",
        request: Any = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        token_value = api_token if isinstance(api_token, str) else ""
        token_value = token_value.strip()
        if token_value:
            return token_value

        ext_kwargs = kwargs if isinstance(kwargs, dict) else {}
        kw_token = ext_kwargs.get("api_token")
        if isinstance(kw_token, str) and kw_token.strip():
            return kw_token.strip()

        if request is not None:
            try:
                query_token = request.query_params.get("api_token")
                if query_token:
                    return str(query_token).strip()
            except Exception:
                pass
            try:
                header_token = request.headers.get(
                    "Authorization"
                ) or request.headers.get("X-API-Token")
                if header_token:
                    return str(header_token).strip()
            except Exception:
                pass

        return ""

    def __latest_base_url(self) -> Optional[str]:
        latest_item = None
        for item in self._strm_cache.values():
            if not item.get("base_url"):
                continue
            if not latest_item or item.get("ts", 0) > latest_item.get("ts", 0):
                latest_item = item
        return latest_item.get("base_url") if latest_item else None

    def __is_recently_deleted(self, target_path: str) -> bool:
        now = time.time()
        to_remove = []
        for cached_path, ts in self._recent_deleted.items():
            if now - ts >= self._recent_ttl_seconds:
                to_remove.append(cached_path)
        for cached_path in to_remove:
            self._recent_deleted.pop(cached_path, None)

        last_ts = self._recent_deleted.get(target_path)
        return bool(last_ts and now - last_ts < self._recent_ttl_seconds)

    def __in_monitor_paths(self, target_path: str) -> bool:
        if not target_path or not self._path_prefixes:
            return False
        for prefix in self._path_prefixes:
            if prefix == "/":
                return True
            if target_path == prefix or target_path.startswith(f"{prefix}/"):
                return True
        return False

    def __parse_monitor_paths(self, raw_text: str) -> List[str]:
        result = []
        text = str(raw_text or "")
        for sep in [",", "，", ";", "；"]:
            text = text.replace(sep, "\n")
        for line in text.splitlines():
            value = line.strip()
            if not value:
                continue
            _, path = self.__parse_openlist_target(value)
            if path and path not in result:
                result.append(path)
        return result

    @staticmethod
    def __safe_get(data: Any, key: str, default: Any = None) -> Any:
        if not data:
            return default
        if isinstance(data, dict):
            return data.get(key, default)
        return getattr(data, key, default)

    @staticmethod
    def __normalize_local_path(path_value: Any) -> str:
        return str(path_value or "").strip().replace("\\", "/")

    @staticmethod
    def __normalize_openlist_path(path_value: Any) -> Optional[str]:
        path = str(path_value or "").strip().replace("\\", "/")
        if not path:
            return None
        while "//" in path:
            path = path.replace("//", "/")
        if not path.startswith("/"):
            path = f"/{path}"
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        return path

    @staticmethod
    def __read_strm_content(strm_file: Path) -> Optional[str]:
        try:
            if not strm_file.exists() or not strm_file.is_file():
                return None
            content = strm_file.read_text(encoding="utf-8-sig", errors="ignore")
            for line in content.splitlines():
                line = line.strip()
                if line:
                    return line
            return None
        except Exception as err:
            logger.error(f"读取strm文件失败：{strm_file}，原因：{err}")
            return None

    def __parse_openlist_target(
        self, raw_text: str
    ) -> Tuple[Optional[str], Optional[str]]:
        value = str(raw_text or "").strip()
        if not value:
            return None, None

        if value.startswith("http://") or value.startswith("https://"):
            parsed = urlparse(value)
            if not parsed.scheme or not parsed.netloc:
                return None, None
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            target_path = self.__extract_openlist_path(parsed)
            return base_url, target_path

        target_path = self.__normalize_openlist_path(value)
        return None, target_path

    def __extract_openlist_path(self, parsed_url) -> Optional[str]:
        query_map = parse_qs(parsed_url.query or "")
        for key in ["path", "file", "target", "src"]:
            value = query_map.get(key)
            if value and value[0]:
                return self.__normalize_openlist_path(unquote(value[0]))

        path = unquote(parsed_url.path or "")
        if not path:
            return None
        for prefix in ["/d", "/dav", "/p"]:
            if path == prefix or path == f"{prefix}/":
                return "/"
            if path.startswith(f"{prefix}/"):
                return self.__normalize_openlist_path(path[len(prefix) :])
        return self.__normalize_openlist_path(path)
