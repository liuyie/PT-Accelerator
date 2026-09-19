import logging
import requests
import traceback
from typing import List, Dict, Any, Optional, TypedDict
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ConnResult(TypedDict):
    success: bool
    message: str
    version: Optional[str]
    api_version: Optional[str]


class TorrentClientBase:
    """下载器客户端基类"""
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_https: bool = False,
        api_key: str = "",
        verify_ssl: bool = True
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_https = use_https
        self.api_key = api_key
        self.verify_ssl = verify_ssl
        self.base_url = (
            f"{'https' if use_https else 'http'}://{host}:{port}"
        )
        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        logger.debug(
            "初始化下载器客户端: %s, URL: %s",
            self.__class__.__name__, self.base_url
        )

    def test_connection(self) -> Dict[str, Any]:
        """测试连接"""
        raise NotImplementedError("子类必须实现此方法")

    def get_trackers(self) -> List[str]:
        """获取所有种子的Tracker列表"""
        raise NotImplementedError("子类必须实现此方法")


class QBittorrentClient(TorrentClientBase):
    """
    qBittorrent客户端
    支持：
    1. qBittorrent 5.2+ API Key
    2. 用户名 + 密码 + QBT_SID Cookie（兼容 qB4.x SID 和 qB5.x QBT_SID_端口）
    3. qBittorrent 登录返回 HTTP 204 的情况
    """
    API_VERSION_ENDPOINT = "/app/version"
    API_WEBAPI_VERSION_ENDPOINT = "/app/webapiVersion"
    API_TORRENT_INFO_ENDPOINT = "/torrents/info"
    API_LOGIN_ENDPOINT = "/auth/login"
    QBT_SID_PREFIX = "QBT_SID_"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_https: bool = False,
        api_key: str = "",
        verify_ssl: bool = True
    ):
        super().__init__(
            host=host,
            port=port,
            username=username,
            password=password,
            use_https=use_https,
            api_key=api_key,
            verify_ssl=verify_ssl
        )
        self.api_url = f"{self.base_url}/api/v2"
        self._authed = False  # 会话认证标记
        logger.info(
            "初始化qBittorrent客户端: %s:%s, 使用HTTPS: %s",
            host, port, use_https
        )
        logger.debug("qBittorrent API URL: %s", self.api_url)
        if self.api_key:
            logger.info("qBittorrent配置了API Key，将优先使用API Key认证")
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}"
            })
        else:
            logger.info("qBittorrent未配置API Key，将使用用户名密码认证")
        logger.debug(
            "qBittorrent用户名: %s, 密码长度: %s",
            username, len(password) if password else 0
        )

    def _get_qbt_sid(self) -> Optional[str]:
        """提取QBT_SID Cookie，抽离复用"""
        sid_val = None
        for cookie_name, cookie_val in self.session.cookies.items():
            if cookie_name.startswith(self.QBT_SID_PREFIX):
                sid_val = cookie_val
                break
        return sid_val

    def login(self) -> bool:
        """
        登录/验证qBittorrent。
        认证优先级：
        1. qBittorrent 5.2+ API Key（Bearer）
        2. API Key 失败后自动回退到用户名 + 密码 + QBT_SID Cookie
        用户名、密码和 API Key 可以同时配置。
        API Key 成功时保留 Bearer Header；如果 API Key 失效，
        会自动移除 Bearer Header，再使用用户名/密码建立会话。
        """
        try:
            self.session.cookies.clear()
            self._authed = False
            # API Key认证（优先）
            if self.api_key:
                logger.info(
                    "正在使用qBittorrent API Key进行认证（用户名/密码仍保留作为备用认证）"
                )
                self.session.headers.update({
                    "Authorization": f"Bearer {self.api_key}"
                })
                version_url = f"{self.api_url}{self.API_VERSION_ENDPOINT}"
                logger.debug("API Key验证请求: %s", version_url)
                response = self.session.get(
                    version_url,
                    timeout=10
                )
                logger.debug(
                    "API Key验证响应: 状态码=%s, 内容='%s'",
                    response.status_code, response.text
                )
                if response.status_code == 200:
                    logger.info("qBittorrent API Key认证成功，后续请求使用API Key")
                    self._authed = True
                    return True
                logger.warning(
                    "qBittorrent API Key认证失败: 状态码=%s, 响应='%s'；将自动回退到用户名/密码认证",
                    response.status_code, response.text
                )
                self.session.headers.pop("Authorization", None)

            # 用户名密码备用认证
            if not self.username or not self.password:
                logger.error(
                    "qBittorrent API Key不可用，且未配置完整的用户名/密码，无法进行备用认证"
                )
                return False
            logger.info("正在使用qBittorrent用户名 + 密码进行备用认证")
            login_url = f"{self.api_url}{self.API_LOGIN_ENDPOINT}"
            logger.debug("尝试登录qBittorrent: %s", login_url)
            data = {
                "username": self.username,
                "password": self.password
            }
            headers = {"Referer": self.base_url}
            response = self.session.post(
                login_url,
                data=data,
                headers=headers,
                timeout=10
            )
            sid_val = self._get_qbt_sid()
            sid_old = self.session.cookies.get("SID")
            logger.debug(
                "登录响应: 状态码=%s, 内容='%s', QBT_SID=%s",
                response.status_code, response.text, "已获取" if sid_val else "None"
            )
            # qB5.x 204 + QBT_SID
            if response.status_code == 204 and sid_val:
                logger.info("qBittorrent用户名/密码登录成功（HTTP 204 + QBT_SID Cookie，qB5.x）")
                self._authed = True
                return True
            # qB4.x 200 OK + SID
            if (
                response.status_code == 200
                and response.text
                and response.text.lower().startswith("ok")
                and sid_old
            ):
                logger.info("qBittorrent用户名/密码登录成功（HTTP 200 + OK + SID，qB4.x）")
                self._authed = True
                return True
            # 兼容旧版本 200 + SID
            if response.status_code == 200 and sid_old:
                logger.info("qBittorrent用户名/密码登录成功（HTTP 200 + SID）")
                self._authed = True
                return True
            logger.error(
                "qBittorrent用户名/密码登录失败: 状态码=%s, 响应='%s', QBT_SID=%s",
                response.status_code, response.text, "已获取" if sid_val else "None"
            )
            return False
        except requests.exceptions.Timeout:
            logger.error("qBittorrent登录超时: %s:%s", self.host, self.port)
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error("qBittorrent连接错误: %s", str(e))
            return False
        except Exception as e:
            error_msg = f"qBittorrent登录异常: {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            logger.debug(traceback.format_exc())
            return False

    def test_connection(self) -> Dict[str, Any]:
        """测试qBittorrent连接"""
        try:
            logger.info("测试qBittorrent连接: %s:%s", self.host, self.port)
            if not self.login():
                sid = self._get_qbt_sid()
                logger.error("登录失败后QBT_SID: %s", "已获取" if sid else "None")
                if self.api_key:
                    message = "qBittorrent API Key及用户名/密码认证均失败，请检查API Key、主机地址、端口、用户名和密码"
                else:
                    message = "登录失败，请检查主机地址、端口、用户名和密码"
                return {
                    "success": False,
                    "message": message
                }
            sid = self._get_qbt_sid()
            if self.api_key and self.session.headers.get("Authorization"):
                logger.info("qBittorrent认证成功，当前使用API Key认证")
            else:
                logger.info("qBittorrent认证成功，QBT_SID=%s", "已获取" if sid else "None")

            version_url = f"{self.api_url}{self.API_VERSION_ENDPOINT}"
            logger.debug("获取qBittorrent版本信息: %s", version_url)
            response = self.session.get(
                version_url,
                timeout=10
            )
            logger.debug(
                "版本信息响应: 状态码=%s, 内容='%s'",
                response.status_code, response.text
            )
            if response.status_code != 200:
                error_msg = f"获取qBittorrent版本信息失败: 状态码={response.status_code}, 响应='{response.text}'"
                logger.error(error_msg)
                return {
                    "success": False,
                    "message": error_msg
                }
            version = response.text.strip()
            logger.info("qBittorrent版本: %s", version)

            api_version_url = f"{self.api_url}{self.API_WEBAPI_VERSION_ENDPOINT}"
            api_response = self.session.get(
                api_version_url,
                timeout=10
            )
            if api_response.status_code == 200:
                api_version = api_response.text.strip()
            else:
                api_version = "未知"
            logger.info("qBittorrent API版本: %s", api_version)
            return {
                "success": True,
                "message": f"连接成功，qBittorrent版本: {version}, API版本: {api_version}",
                "version": version,
                "api_version": api_version
            }
        except requests.exceptions.Timeout:
            error_msg = f"qBittorrent连接超时: {self.host}:{self.port}"
            logger.error(error_msg)
            return {
                "success": False,
                "message": error_msg
            }
        except requests.exceptions.ConnectionError as e:
            error_msg = f"qBittorrent连接错误: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "message": error_msg
            }
        except Exception as e:
            error_msg = f"测试qBittorrent连接异常: {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            logger.debug(traceback.format_exc())
            return {
                "success": False,
                "message": error_msg
            }

    def get_trackers(self) -> List[str]:
        """
        获取所有种子的Tracker列表。
        API Key模式下：Authorization Header会自动通过Session发送。
        QBT_SID模式下：Cookie会自动通过Session发送。
        """
        try:
            # 仅未认证时登录；后续复用会话
            if not self._authed:
                if not self.login():
                    sid = self._get_qbt_sid()
                    logger.error("获取Tracker失败: 登录失败，QBT_SID=%s", "已获取" if sid else "None")
                    return []
            sid = self._get_qbt_sid()
            logger.info("获取Tracker时QBT_SID: %s", "已获取" if sid else "None")

            torrents_url = f"{self.api_url}{self.API_TORRENT_INFO_ENDPOINT}"
            response = self.session.get(
                torrents_url,
                timeout=15
            )
            # 会话失效，重置标记重试一次
            if response.status_code in (401, 403):
                logger.warning("qB会话失效，重新认证")
                self._authed = False
                if not self.login():
                    return []
                response = self.session.get(torrents_url, timeout=15)

            logger.debug("获取种子列表响应: 状态码=%s", response.status_code)
            if response.status_code != 200:
                logger.error(
                    "获取种子列表失败: 状态码=%s, 响应='%s'",
                    response.status_code, response.text
                )
                return []
            try:
                torrents = response.json()
            except Exception as e:
                logger.error("解析种子列表JSON失败: %s", str(e))
                return []
            logger.info("获取到 %s 个种子", len(torrents))
            tracker_urls = set()

            # 直接读取torrent.info自带trackers，不再循环请求接口
            for torrent in torrents:
                trackers = torrent.get("trackers", [])
                for tracker in trackers:
                    tracker_url = tracker.get("url", "")
                    if tracker_url and tracker_url.startswith("http"):
                        try:
                            parsed_url = urlparse(tracker_url)
                            domain = parsed_url.netloc
                            if domain:
                                tracker_urls.add(domain)
                                logger.debug("提取Tracker域名: %s", domain)
                        except Exception as e:
                            logger.error("解析Tracker URL失败: %s", str(e))
            logger.info("总共提取了 %s 个唯一Tracker域名", len(tracker_urls))
            return list(tracker_urls)
        except Exception as e:
            logger.error(
                "获取qBittorrent Tracker列表异常: %s: %s",
                type(e).__name__, str(e)
            )
            logger.debug(traceback.format_exc())
            return []


class TransmissionClient(TorrentClientBase):
    """Transmission客户端"""
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_https: bool = False,
        path: str = "/transmission/rpc",
        verify_ssl: bool = True
    ):
        super().__init__(
            host=host,
            port=port,
            username=username,
            password=password,
            use_https=use_https,
            api_key="",
            verify_ssl=verify_ssl
        )
        self.rpc_url = f"{self.base_url}{path}"
        self.session_id: Optional[str] = None

    def _get_session_id(self) -> bool:
        """获取Transmission会话ID"""
        try:
            response = self.session.get(
                self.rpc_url,
                auth=(self.username, self.password),
                timeout=10
            )
            if response.status_code == 409:
                self.session_id = response.headers.get("X-Transmission-Session-Id")
                if self.session_id:
                    logger.info("获取Transmission会话ID成功")
                    return True
            logger.error("获取Transmission会话ID失败: %s", response.status_code)
            return False
        except Exception as e:
            logger.error("获取Transmission会话ID异常: %s", str(e))
            return False

    def _make_request(
        self,
        method: str,
        arguments: Optional[Dict] = None
    ) -> Dict:
        """发送RPC请求到Transmission，循环重试，限制重试次数"""
        retry = 0
        max_retry = 1
        while retry <= max_retry:
            if not self.session_id and not self._get_session_id():
                return {
                    "result": "error",
                    "message": "无法获取会话ID"
                }
            headers = {
                "X-Transmission-Session-Id": self.session_id
            }
            payload = {
                "method": method,
                "arguments": arguments or {}
            }
            try:
                response = self.session.post(
                    self.rpc_url,
                    headers=headers,
                    json=payload,
                    auth=(self.username, self.password),
                    timeout=15
                )
                if response.status_code == 409:
                    self.session_id = response.headers.get("X-Transmission-Session-Id")
                    retry += 1
                    continue
                if response.status_code == 200:
                    return response.json()
                return {
                    "result": "error",
                    "message": f"请求失败: {response.status_code}"
                }
            except Exception as e:
                return {
                    "result": "error",
                    "message": f"请求异常: {str(e)}"
                }
        return {
            "result": "error",
            "message": "会话ID重试次数耗尽"
        }

    def test_connection(self) -> Dict[str, Any]:
        """测试Transmission连接"""
        try:
            if not self._get_session_id():
                return {
                    "success": False,
                    "message": "无法获取会话ID，请检查连接信息"
                }
            response = self._make_request("session-get")
            if response.get("result") != "error":
                version = response.get("arguments", {}).get("version", "未知")
                return {
                    "success": True,
                    "message": f"连接成功，Transmission版本: {version}",
                    "version": version
                }
            return {
                "success": False,
                "message": response.get("message", "未知错误")
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"连接异常: {str(e)}"
            }

    def get_trackers(self) -> List[str]:
        """获取所有种子的Tracker列表"""
        try:
            if not self._get_session_id():
                logger.error("获取Tracker失败: 无法获取会话ID")
                return []
            response = self._make_request(
                "torrent-get",
                {
                    "fields": [
                        "id",
                        "trackers"
                    ]
                }
            )
            if response.get("result") == "error":
                logger.error("获取种子列表失败: %s", response.get("message", "未知错误"))
                return []
            torrents = response.get("arguments", {}).get("torrents", [])
            tracker_urls = set()
            for torrent in torrents:
                trackers = torrent.get("trackers", [])
                for tracker in trackers:
                    tracker_url = tracker.get("announce", "")
                    if tracker_url and tracker_url.startswith("http"):
                        try:
                            parsed_url = urlparse(tracker_url)
                            domain = parsed_url.netloc
                            if domain:
                                tracker_urls.add(domain)
                        except Exception as e:
                            logger.error("解析Tracker URL失败: %s", str(e))
            logger.info("Transmission获取到 %s 个唯一Tracker域名", len(tracker_urls))
            return list(tracker_urls)
        except Exception as e:
            logger.error("获取Tracker列表异常: %s", str(e))
            return []


class TorrentClientManager:
    """下载器客户端管理器 - 支持多实例动态管理"""
    def __init__(
        self,
        config: Dict[str, Any]
    ):
        self.config = config
        self.clients: Dict[str, Dict[str, Any]] = {}
        self._init_clients()

    def _init_clients(self):
        """初始化下载器客户端 - 支持多实例"""
        self.clients = {}
        clients_config = self.config.get("torrent_clients", [])
        # 兼容旧配置格式
        if isinstance(clients_config, dict):
            logger.info("检测到旧版本配置格式，正在转换为新格式...")
            converted_clients = []
            if "qbittorrent" in clients_config:
                qb_config = clients_config["qbittorrent"]
                converted_clients.append({
                    "id": "qb_migrated",
                    "name": "qBittorrent (迁移)",
                    "type": "qbittorrent",
                    **qb_config
                })
            if "transmission" in clients_config:
                tr_config = clients_config["transmission"]
                converted_clients.append({
                    "id": "tr_migrated",
                    "name": "Transmission (迁移)",
                    "type": "transmission",
                    **tr_config
                })
            clients_config = converted_clients
            self.config["torrent_clients"] = clients_config
            logger.info("配置转换完成，共转换 %s 个客户端", len(converted_clients))

        for client_config in clients_config:
            client_id = client_config.get("id")
            client_type = client_config.get("type")
            if not client_id or not client_type:
                logger.warning("跳过无效的客户端配置: %s", client_config)
                continue
            try:
                if client_type == "qbittorrent":
                    client = QBittorrentClient(
                        host=client_config.get("host", "localhost"),
                        port=client_config.get("port", 8080),
                        username=client_config.get("username", ""),
                        password=client_config.get("password", ""),
                        use_https=client_config.get("use_https", False),
                        api_key=client_config.get("api_key", ""),
                        verify_ssl=client_config.get("verify_ssl", True)
                    )
                elif client_type == "transmission":
                    client = TransmissionClient(
                        host=client_config.get("host", "localhost"),
                        port=client_config.get("port", 9091),
                        username=client_config.get("username", ""),
                        password=client_config.get("password", ""),
                        use_https=client_config.get("use_https", False),
                        path=client_config.get("path", "/transmission/rpc"),
                        verify_ssl=client_config.get("verify_ssl", True)
                    )
                else:
                    logger.warning("不支持的客户端类型: %s", client_type)
                    continue
                self.clients[client_id] = {
                    "client": client,
                    "config": client_config
                }
                logger.info(
                    "初始化客户端成功: %s (%s)",
                    client_config.get('name', client_id), client_type
                )
            except Exception as e:
                logger.error(
                    "初始化客户端失败: %s - %s",
                    client_config.get('name', client_id), str(e)
                )
                logger.debug(traceback.format_exc())

    def update_config(
        self,
        config: Dict[str, Any]
    ):
        """更新配置并重新初始化客户端"""
        self.config = config
        self._init_clients()

    def test_client_connection(
        self,
        client_id: str
    ) -> Dict[str, Any]:
        """测试指定客户端连接"""
        logger.info("正在测试客户端连接: %s", client_id)
        logger.debug("当前已初始化的客户端列表: %s", list(self.clients.keys()))
        client_info = self.clients.get(client_id)
        if not client_info:
            logger.error(
                "未找到客户端: %s, 可用客户端: %s",
                client_id, list(self.clients.keys())
            )
            return {
                "success": False,
                "message": f"未找到客户端: {client_id}, 可能尚未保存或未启用"
            }
        try:
            logger.info("开始测试客户端 %s 的连接", client_id)
            result = client_info["client"].test_connection()
            logger.info("客户端 %s 测试结果: %s", client_id, result)
            return result
        except Exception as e:
            logger.error("测试客户端连接失败: %s - %s", client_id, str(e))
            return {
                "success": False,
                "message": f"测试连接失败: {str(e)}"
            }

    def test_client_connection_by_config(
        self,
        client_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """根据配置临时创建客户端并测试连接"""
        client_type = client_config.get("type")
        if not client_type:
            return {
                "success": False,
                "message": "缺少客户端类型"
            }
        try:
            if client_type == "qbittorrent":
                client = QBittorrentClient(
                    host=client_config.get("host", "localhost"),
                    port=client_config.get("port", 8080),
                    username=client_config.get("username", ""),
                    password=client_config.get("password", ""),
                    use_https=client_config.get("use_https", False),
                    api_key=client_config.get("api_key", ""),
                    verify_ssl=client_config.get("verify_ssl", True)
                )
            elif client_type == "transmission":
                client = TransmissionClient(
                    host=client_config.get("host", "localhost"),
                    port=client_config.get("port", 9091),
                    username=client_config.get("username", ""),
                    password=client_config.get("password", ""),
                    use_https=client_config.get("use_https", False),
                    path=client_config.get("path", "/transmission/rpc"),
                    verify_ssl=client_config.get("verify_ssl", True)
                )
            else:
                return {
                    "success": False,
                    "message": f"不支持的客户端类型: {client_type}"
                }
            result = client.test_connection()
            return result
        except Exception as e:
            logger.error("测试客户端连接失败: %s", str(e))
            logger.debug(traceback.format_exc())
            return {
                "success": False,
                "message": f"测试连接失败: {str(e)}"
            }

    def get_all_trackers(self) -> List[str]:
        """获取所有启用的下载器中的Tracker列表"""
        all_trackers = set()
        for client_id, client_info in self.clients.items():
            if not client_info["config"].get("enable", False):
                continue
            try:
                client_name = client_info["config"].get("name", client_id)
                trackers = client_info["client"].get_trackers()
                logger.info("从 %s 获取到 %s 个Tracker", client_name, len(trackers))
                all_trackers.update(trackers)
            except Exception as e:
                logger.error("从客户端 %s 获取Tracker失败: %s", client_id, str(e))
        return list(all_trackers)

    def import_trackers_from_clients(self):
        """
        自动从所有已启用下载器获取Tracker域名
        并返回详细信息
        """
        all_domains = set()
        client_results = {}
        for client_id, client_info in self.clients.items():
            if not client_info["config"].get("enable", False):
                continue
            client_name = client_info["config"].get("name", client_id)
            client_type = client_info["config"].get("type", "unknown")
            try:
                trackers = client_info["client"].get_trackers()
                client_results[client_id] = {
                    "name": client_name,
                    "type": client_type,
                    "trackers": trackers,
                    "count": len(trackers),
                    "success": True
                }
                all_domains.update(trackers)
                logger.info(
                    "从 %s (%s) 获取到 %s 个Tracker域名",
                    client_name, client_type, len(trackers)
                )
            except Exception as e:
                client_results[client_id] = {
                    "name": client_name,
                    "type": client_type,
                    "trackers": [],
                    "count": 0,
                    "success": False,
                    "error": str(e)
                }
                logger.error(
                    "从 %s (%s) 获取Tracker失败: %s",
                    client_name, client_type, str(e)
                )
        total_count = len(all_domains)
        return {
            "status": "success" if total_count > 0 else "warning",
            "message": f"成功导入 {total_count} 个唯一Tracker域名" if total_count > 0 else "未发现可导入的Tracker域名",
            "total_count": total_count,
            "client_results": client_results,
            "all_domains": list(all_domains)
        }

    def get_clients_info(self) -> List[Dict[str, Any]]:
        """获取所有客户端信息"""
        clients_info = []
        for client_id, client_info in self.clients.items():
            clients_info.append({
                "id": client_id,
                "name": client_info["config"].get("name", client_id),
                "type": client_info["config"].get("type"),
                "host": client_info["config"].get("host"),
                "port": client_info["config"].get("port"),
                "enabled": client_info["config"].get("enable", False)
            })
        return clients_info
