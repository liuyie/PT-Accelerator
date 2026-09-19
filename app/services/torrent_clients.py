import logging
import requests
import traceback
from typing import List, Dict, Any, Optional
logger = logging.getLogger(__name__)


class TorrentClientBase:
    """下载器客户端基类"""
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_https: bool = False,
        api_key: str = ""
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_https = use_https
        self.api_key = api_key
        self.base_url = (
            f"{'https' if use_https else 'http'}://{host}:{port}"
        )
        self.session = requests.Session()
        logger.debug(
            f"初始化下载器客户端: "
            f"{self.__class__.__name__}, "
            f"URL: {self.base_url}"
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
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_https: bool = False,
        api_key: str = ""
    ):
        super().__init__(
            host=host,
            port=port,
            username=username,
            password=password,
            use_https=use_https,
            api_key=api_key
        )
        logger.info(
            f"初始化qBittorrent客户端: "
            f"{host}:{port}, "
            f"使用HTTPS: {use_https}"
        )
        self.api_url = f"{self.base_url}/api/v2"
        logger.debug(
            f"qBittorrent API URL: {self.api_url}"
        )
        if self.api_key:
            logger.info(
                "qBittorrent配置了API Key，将优先使用API Key认证"
            )
            # qBittorrent 5.2+
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}"
            })
        else:
            logger.info(
                "qBittorrent未配置API Key，将使用用户名密码认证"
            )
        logger.debug(
            f"qBittorrent用户名: {username}, "
            f"密码长度: {len(password) if password else 0}"
        )

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
            # 每次重新认证前清理旧Cookie，避免残留会话影响结果。
            self.session.cookies.clear()
            # ============================================================
            # API Key认证（优先）
            # ============================================================
            if self.api_key:
                logger.info(
                    "正在使用qBittorrent API Key进行认证（用户名/密码仍保留作为备用认证）"
                )
                # 确保 Bearer Header 使用当前配置的 API Key。
                self.session.headers.update({
                    "Authorization": f"Bearer {self.api_key}"
                })
                version_url = f"{self.api_url}/app/version"
                logger.debug(
                    f"API Key验证请求: {version_url}"
                )
                response = self.session.get(
                    version_url,
                    timeout=10
                )
                logger.debug(
                    f"API Key验证响应: "
                    f"状态码={response.status_code}, "
                    f"内容='{response.text}'"
                )
                if response.status_code == 200:
                    logger.info(
                        "qBittorrent API Key认证成功，后续请求使用API Key"
                    )
                    return True
                logger.warning(
                    f"qBittorrent API Key认证失败: "
                    f"状态码={response.status_code}, "
                    f"响应='{response.text}'；"
                    "将自动回退到用户名/密码认证"
                )
                # API Key 无效时必须移除 Bearer Header，
                # 否则后面的用户名/密码登录请求可能仍携带失效的 Bearer。
                self.session.headers.pop("Authorization", None)
            # ============================================================
            # 用户名 + 密码 + QBT_SID认证（API Key失败时自动回退）
            # ============================================================
            if not self.username or not self.password:
                logger.error(
                    "qBittorrent API Key不可用，且未配置完整的用户名/密码，"
                    "无法进行备用认证"
                )
                return False
            logger.info(
                "正在使用qBittorrent用户名 + 密码进行备用认证"
            )
            login_url = f"{self.api_url}/auth/login"
            logger.debug(
                f"尝试登录qBittorrent: {login_url}"
            )
            data = {
                "username": self.username,
                "password": self.password
            }
            # qB5.x 需要Referer头，否则后续接口返回403
            headers = {"Referer": self.base_url}
            response = self.session.post(
                login_url,
                data=data,
                headers=headers,
                timeout=10
            )
            # 遍历cookie，找到以 QBT_SID_ 开头的cookie（适配qB5.x动态cookie名）
            sid_val = None
            for cookie_name, cookie_val in self.session.cookies.items():
                if cookie_name.startswith("QBT_SID_"):
                    sid_val = cookie_val
                    break
            logger.debug(
                f"登录响应: "
                f"状态码={response.status_code}, "
                f"内容='{response.text}', "
                f"QBT_SID={'已获取' if sid_val else 'None'}"
            )
            # ============================================================
            # HTTP 204 + QBT_SID (qB5.x)
            # ============================================================
            if response.status_code == 204 and sid_val:
                logger.info(
                    "qBittorrent用户名/密码登录成功（HTTP 204 + QBT_SID Cookie，qB5.x）"
                )
                return True
            # ============================================================
            # HTTP 200 + OK + SID（qB4.x旧版本）
            # ============================================================
            sid_old = self.session.cookies.get("SID")
            if (
                response.status_code == 200
                and response.text
                and response.text.lower().startswith("ok")
                and sid_old
            ):
                logger.info(
                    "qBittorrent用户名/密码登录成功（HTTP 200 + OK + SID，qB4.x）"
                )
                return True
            # ============================================================
            # HTTP 200 + SID（兼容其他旧版本）
            # ============================================================
            if response.status_code == 200 and sid_old:
                logger.info(
                    "qBittorrent用户名/密码登录成功（HTTP 200 + SID）"
                )
                return True
            logger.error(
                f"qBittorrent用户名/密码登录失败: "
                f"状态码={response.status_code}, "
                f"响应='{response.text}', "
                f"QBT_SID={'已获取' if sid_val else 'None'}"
            )
            return False
        except requests.exceptions.Timeout:
            logger.error(
                f"qBittorrent登录超时: {self.host}:{self.port}"
            )
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error(
                f"qBittorrent连接错误: {str(e)}"
            )
            return False
        except Exception as e:
            error_msg = (
                f"qBittorrent登录异常: "
                f"{type(e).__name__}: {str(e)}"
            )
            logger.error(error_msg)
            logger.debug(traceback.format_exc())
            return False

    def test_connection(self) -> Dict[str, Any]:
        """测试qBittorrent连接"""
        try:
            logger.info(
                f"测试qBittorrent连接: "
                f"{self.host}:{self.port}"
            )
            # ============================================================
            # 登录 / API Key验证
            # ============================================================
            if not self.login():
                sid = None
                for cookie_name, cookie_val in self.session.cookies.items():
                    if cookie_name.startswith("QBT_SID_"):
                        sid = cookie_val
                        break
                logger.error(
                    f"登录失败后QBT_SID: {'已获取' if sid else 'None'}"
                )
                if self.api_key:
                    message = (
                        "qBittorrent API Key及用户名/密码认证均失败，"
                        "请检查API Key、主机地址、端口、用户名和密码"
                    )
                else:
                    message = (
                        "登录失败，请检查主机地址、端口、"
                        "用户名和密码"
                    )
                return {
                    "success": False,
                    "message": message
                }
            # ============================================================
            # 获取QBT_SID
            # ============================================================
            sid = None
            for cookie_name, cookie_val in self.session.cookies.items():
                if cookie_name.startswith("QBT_SID_"):
                    sid = cookie_val
                    break
            if self.api_key and self.session.headers.get("Authorization"):
                logger.info(
                    "qBittorrent认证成功，当前使用API Key认证"
                )
            else:
                logger.info(
                    f"qBittorrent认证成功，QBT_SID={'已获取' if sid else 'None'}"
                )
            # ============================================================
            # 获取qBittorrent版本
            # ============================================================
            version_url = f"{self.api_url}/app/version"
            logger.debug(
                f"获取qBittorrent版本信息: "
                f"{version_url}"
            )
            response = self.session.get(
                version_url,
                timeout=10
            )
            logger.debug(
                f"版本信息响应: "
                f"状态码={response.status_code}, "
                f"内容='{response.text}'"
            )
            if response.status_code != 200:
                error_msg = (
                    f"获取qBittorrent版本信息失败: "
                    f"状态码={response.status_code}, "
                    f"响应='{response.text}'"
                )
                logger.error(error_msg)
                return {
                    "success": False,
                    "message": error_msg
                }
            version = response.text.strip()
            logger.info(
                f"qBittorrent版本: {version}"
            )
            # ============================================================
            # 获取API版本
            # ============================================================
            api_version_url = (
                f"{self.api_url}/app/webapiVersion"
            )
            api_response = self.session.get(
                api_version_url,
                timeout=10
            )
            if api_response.status_code == 200:
                api_version = api_response.text.strip()
            else:
                api_version = "未知"
            logger.info(
                f"qBittorrent API版本: {api_version}"
            )
            return {
                "success": True,
                "message": (
                    f"连接成功，"
                    f"qBittorrent版本: {version}, "
                    f"API版本: {api_version}"
                ),
                "version": version,
                "api_version": api_version
            }
        except requests.exceptions.Timeout:
            error_msg = (
                f"qBittorrent连接超时: "
                f"{self.host}:{self.port}"
            )
            logger.error(error_msg)
            return {
                "success": False,
                "message": error_msg
            }
        except requests.exceptions.ConnectionError as e:
            error_msg = (
                f"qBittorrent连接错误: {str(e)}"
            )
            logger.error(error_msg)
            return {
                "success": False,
                "message": error_msg
            }
        except Exception as e:
            error_msg = (
                f"测试qBittorrent连接异常: "
                f"{type(e).__name__}: {str(e)}"
            )
            logger.error(error_msg)
            logger.debug(traceback.format_exc())
            return {
                "success": False,
                "message": error_msg
            }

    def get_trackers(self) -> List[str]:
        """
        获取所有种子的Tracker列表。
        API Key模式下：
        Authorization Header会自动通过Session发送。
        QBT_SID模式下：
        Cookie会自动通过Session发送。
        """
        try:
            # ============================================================
            # 登录 / API Key验证
            # ============================================================
            if not self.login():
                sid = None
                for cookie_name, cookie_val in self.session.cookies.items():
                    if cookie_name.startswith("QBT_SID_"):
                        sid = cookie_val
                        break
                logger.error(
                    f"获取Tracker失败: "
                    f"登录失败，QBT_SID={'已获取' if sid else 'None'}"
                )
                return []
            sid = None
            for cookie_name, cookie_val in self.session.cookies.items():
                if cookie_name.startswith("QBT_SID_"):
                    sid = cookie_val
                    break
            logger.info(
                f"获取Tracker时QBT_SID: {'已获取' if sid else 'None'}"
            )
            # ============================================================
            # 获取所有种子
            # ============================================================
            torrents_url = (
                f"{self.api_url}/torrents/info"
            )
            response = self.session.get(
                torrents_url,
                timeout=15
            )
            logger.debug(
                f"获取种子列表响应: "
                f"状态码={response.status_code}"
            )
            if response.status_code != 200:
                logger.error(
                    f"获取种子列表失败: "
                    f"状态码={response.status_code}, "
                    f"响应='{response.text}'"
                )
                return []
            try:
                torrents = response.json()
            except Exception as e:
                logger.error(
                    f"解析种子列表JSON失败: {str(e)}"
                )
                return []
            logger.info(
                f"获取到 {len(torrents)} 个种子"
            )
            tracker_urls = set()
            # ============================================================
            # 遍历种子
            # ============================================================
            for torrent in torrents:
                torrent_hash = torrent.get("hash")
                if not torrent_hash:
                    continue
                trackers_url = (
                    f"{self.api_url}/torrents/trackers"
                )
                params = {
                    "hash": torrent_hash
                }
                trackers_response = self.session.get(
                    trackers_url,
                    params=params,
                    timeout=15
                )
                logger.debug(
                    f"获取种子 {torrent_hash} 的Tracker响应: "
                    f"状态码={trackers_response.status_code}"
                )
                if trackers_response.status_code != 200:
                    logger.warning(
                        f"获取种子 {torrent_hash} "
                        f"的Tracker失败: "
                        f"状态码={trackers_response.status_code}"
                    )
                    continue
                try:
                    trackers = trackers_response.json()
                except Exception as e:
                    logger.warning(
                        f"解析种子 {torrent_hash} "
                        f"的Tracker JSON失败: {str(e)}"
                    )
                    continue
                # ========================================================
                # 提取Tracker域名
                # ========================================================
                for tracker in trackers:
                    tracker_url = tracker.get(
                        "url",
                        ""
                    )
                    if (
                        tracker_url
                        and tracker_url.startswith("http")
                    ):
                        try:
                            from urllib.parse import urlparse
                            parsed_url = urlparse(
                                tracker_url
                            )
                            domain = parsed_url.netloc
                            if domain:
                                tracker_urls.add(
                                    domain
                                )
                                logger.debug(
                                    f"提取Tracker域名: "
                                    f"{domain}"
                                )
                        except Exception as e:
                            logger.error(
                                f"解析Tracker URL失败: "
                                f"{str(e)}"
                            )
            logger.info(
                f"总共提取了 "
                f"{len(tracker_urls)} 个唯一Tracker域名"
            )
            return list(tracker_urls)
        except Exception as e:
            logger.error(
                f"获取qBittorrent Tracker列表异常: "
                f"{type(e).__name__}: {str(e)}"
            )
            logger.debug(
                traceback.format_exc()
            )
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
        path: str = "/transmission/rpc"
    ):
        super().__init__(
            host=host,
            port=port,
            username=username,
            password=password,
            use_https=use_https
        )
        self.rpc_url = (
            f"{self.base_url}{path}"
        )
        self.session_id = None

    def _get_session_id(self) -> bool:
        """获取Transmission会话ID"""
        try:
            response = self.session.get(
                self.rpc_url,
                auth=(
                    self.username,
                    self.password
                ),
                timeout=10
            )
            if response.status_code == 409:
                self.session_id = (
                    response.headers.get(
                        "X-Transmission-Session-Id"
                    )
                )
                if self.session_id:
                    logger.info(
                        "获取Transmission会话ID成功"
                    )
                    return True
            logger.error(
                f"获取Transmission会话ID失败: "
                f"{response.status_code}"
            )
            return False
        except Exception as e:
            logger.error(
                f"获取Transmission会话ID异常: "
                f"{str(e)}"
            )
            return False

    def _make_request(
        self,
        method: str,
        arguments: Optional[Dict] = None
    ) -> Dict:
        """发送RPC请求到Transmission"""
        if (
            not self.session_id
            and not self._get_session_id()
        ):
            return {
                "result": "error",
                "message": "无法获取会话ID"
            }
        headers = {
            "X-Transmission-Session-Id":
                self.session_id
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
                auth=(
                    self.username,
                    self.password
                ),
                timeout=15
            )
            if response.status_code == 409:
                self.session_id = (
                    response.headers.get(
                        "X-Transmission-Session-Id"
                    )
                )
                if not self.session_id:
                    return {
                        "result": "error",
                        "message": "重新获取会话ID失败"
                    }
                return self._make_request(
                    method,
                    arguments
                )
            if response.status_code == 200:
                return response.json()
            return {
                "result": "error",
                "message": (
                    f"请求失败: "
                    f"{response.status_code}"
                )
            }
        except Exception as e:
            return {
                "result": "error",
                "message": (
                    f"请求异常: {str(e)}"
                )
            }

    def test_connection(self) -> Dict[str, Any]:
        """测试Transmission连接"""
        try:
            if not self._get_session_id():
                return {
                    "success": False,
                    "message": (
                        "无法获取会话ID，"
                        "请检查连接信息"
                    )
                }
            response = self._make_request(
                "session-get"
            )
            if response.get("result") == "success":
                version = (
                    response
                    .get("arguments", {})
                    .get("version", "未知")
                )
                return {
                    "success": True,
                    "message": (
                        f"连接成功，"
                        f"Transmission版本: {version}"
                    ),
                    "version": version
                }
            return {
                "success": False,
                "message": response.get(
                    "message",
                    "未知错误"
                )
            }
        except Exception as e:
            return {
                "success": False,
                "message": (
                    f"连接异常: {str(e)}"
                )
            }

    def get_trackers(self) -> List[str]:
        """获取所有种子的Tracker列表"""
        try:
            if not self._get_session_id():
                logger.error(
                    "获取Tracker失败: "
                    "无法获取会话ID"
                )
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
            if response.get("result") != "success":
                logger.error(
                    f"获取种子列表失败: "
                    f"{response.get('message', '未知错误')}"
                )
                return []
            torrents = (
                response
                .get("arguments", {})
                .get("torrents", [])
            )
            tracker_urls = set()
            for torrent in torrents:
                trackers = torrent.get(
                    "trackers",
                    []
                )
                for tracker in trackers:
                    tracker_url = tracker.get(
                        "announce",
                        ""
                    )
                    if (
                        tracker_url
                        and tracker_url.startswith("http")
                    ):
                        try:
                            from urllib.parse import urlparse
                            parsed_url = urlparse(
                                tracker_url
                            )
                            domain = parsed_url.netloc
                            if domain:
                                tracker_urls.add(
                                    domain
                                )
                        except Exception as e:
                            logger.error(
                                f"解析Tracker URL失败: "
                                f"{str(e)}"
                            )
            logger.info(
                f"Transmission获取到 "
                f"{len(tracker_urls)} 个唯一Tracker域名"
            )
            return list(tracker_urls)
        except Exception as e:
            logger.error(
                f"获取Tracker列表异常: "
                f"{str(e)}"
            )
            return []


class TorrentClientManager:
    """下载器客户端管理器 - 支持多实例动态管理"""
    def __init__(
        self,
        config: Dict[str, Any]
    ):
        self.config = config
        self.clients = {}
        self._init_clients()

    def _init_clients(self):
        """初始化下载器客户端 - 支持多实例"""
        self.clients = {}
        clients_config = self.config.get(
            "torrent_clients",
            []
        )
        # ================================================================
        # 兼容旧配置格式
        # ================================================================
        if isinstance(clients_config, dict):
            logger.info(
                "检测到旧版本配置格式，"
                "正在转换为新格式..."
            )
            converted_clients = []
            # qBittorrent
            if "qbittorrent" in clients_config:
                qb_config = clients_config[
                    "qbittorrent"
                ]
                converted_clients.append({
                    "id": "qb_migrated",
                    "name": "qBittorrent (迁移)",
                    "type": "qbittorrent",
                    **qb_config
                })
            # Transmission
            if "transmission" in clients_config:
                tr_config = clients_config[
                    "transmission"
                ]
                converted_clients.append({
                    "id": "tr_migrated",
                    "name": "Transmission (迁移)",
                    "type": "transmission",
                    **tr_config
                })
            clients_config = converted_clients
            self.config[
                "torrent_clients"
            ] = clients_config
            logger.info(
                f"配置转换完成，"
                f"共转换 {len(converted_clients)} 个客户端"
            )
        # ================================================================
        # 初始化所有客户端
        # ================================================================
        for client_config in clients_config:
            client_id = client_config.get("id")
            client_type = client_config.get("type")
            if not client_id or not client_type:
                logger.warning(
                    f"跳过无效的客户端配置: "
                    f"{client_config}"
                )
                continue
            try:
                # ========================================================
                # qBittorrent
                # ========================================================
                if client_type == "qbittorrent":
                    client = QBittorrentClient(
                        host=client_config.get(
                            "host",
                            "localhost"
                        ),
                        port=client_config.get(
                            "port",
                            8080
                        ),
                        username=client_config.get(
                            "username",
                            ""
                        ),
                        password=client_config.get(
                            "password",
                            ""
                        ),
                        use_https=client_config.get(
                            "use_https",
                            False
                        ),
                        api_key=client_config.get(
                            "api_key",
                            ""
                        )
                    )
                # ========================================================
                # Transmission
                # ========================================================
                elif client_type == "transmission":
                    client = TransmissionClient(
                        host=client_config.get(
                            "host",
                            "localhost"
                        ),
                        port=client_config.get(
                            "port",
                            9091
                        ),
                        username=client_config.get(
                            "username",
                            ""
                        ),
                        password=client_config.get(
                            "password",
                            ""
                        ),
                        use_https=client_config.get(
                            "use_https",
                            False
                        ),
                        path=client_config.get(
                            "path",
                            "/transmission/rpc"
                        )
                    )
                else:
                    logger.warning(
                        f"不支持的客户端类型: "
                        f"{client_type}"
                    )
                    continue
                self.clients[client_id] = {
                    "client": client,
                    "config": client_config
                }
                logger.info(
                    f"初始化客户端成功: "
                    f"{client_config.get('name', client_id)} "
                    f"({client_type})"
                )
            except Exception as e:
                logger.error(
                    f"初始化客户端失败: "
                    f"{client_config.get('name', client_id)} "
                    f"- {str(e)}"
                )
                logger.debug(
                    traceback.format_exc()
                )

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
        logger.info(
            f"正在测试客户端连接: {client_id}"
        )
        logger.debug(
            f"当前已初始化的客户端列表: "
            f"{list(self.clients.keys())}"
        )
        client_info = self.clients.get(
            client_id
        )
        if not client_info:
            logger.error(
                f"未找到客户端: {client_id}, "
                f"可用客户端: "
                f"{list(self.clients.keys())}"
            )
            return {
                "success": False,
                "message": (
                    f"未找到客户端: {client_id}, "
                    f"可能尚未保存或未启用"
                )
            }
        try:
            logger.info(
                f"开始测试客户端 "
                f"{client_id} 的连接"
            )
            result = client_info[
                "client"
            ].test_connection()
            logger.info(
                f"客户端 {client_id} "
                f"测试结果: {result}"
            )
            return result
        except Exception as e:
            logger.error(
                f"测试客户端连接失败: "
                f"{client_id} - {str(e)}"
            )
            return {
                "success": False,
                "message": (
                    f"测试连接失败: {str(e)}"
                )
            }

    def test_client_connection_by_config(
        self,
        client_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """根据配置临时创建客户端并测试连接"""
        client_type = client_config.get(
            "type"
        )
        if not client_type:
            return {
                "success": False,
                "message": "缺少客户端类型"
            }
        try:
            # ============================================================
            # qBittorrent
            # ============================================================
            if client_type == "qbittorrent":
                client = QBittorrentClient(
                    host=client_config.get(
                        "host",
                        "localhost"
                    ),
                    port=client_config.get(
                        "port",
                        8080
                    ),
                    username=client_config.get(
                        "username",
                        ""
                    ),
                    password=client_config.get(
                        "password",
                        ""
                    ),
                    use_https=client_config.get(
                        "use_https",
                        False
                    ),
                    api_key=client_config.get(
                        "api_key",
                        ""
                    )
                )
            # ============================================================
            # Transmission
            # ============================================================
            elif client_type == "transmission":
                client = TransmissionClient(
                    host=client_config.get(
                        "host",
                        "localhost"
                    ),
                    port=client_config.get(
                        "port",
                        9091
                    ),
                    username=client_config.get(
                        "username",
                        ""
                    ),
                    password=client_config.get(
                        "password",
                        ""
                    ),
                    use_https=client_config.get(
                        "use_https",
                        False
                    ),
                    path=client_config.get(
                        "path",
                        "/transmission/rpc"
                    )
                )
            else:
                return {
                    "success": False,
                    "message": (
                        f"不支持的客户端类型: "
                        f"{client_type}"
                    )
                }
            # ============================================================
            # 测试连接
            # ============================================================
            result = client.test_connection()
            return result
        except Exception as e:
            logger.error(
                f"测试客户端连接失败: "
                f"{str(e)}"
            )
            logger.debug(
                traceback.format_exc()
            )
            return {
                "success": False,
                "message": (
                    f"测试连接失败: {str(e)}"
                )
            }

    def get_all_trackers(self) -> List[str]:
        """获取所有启用的下载器中的Tracker列表"""
        all_trackers = set()
        for client_id, client_info in self.clients.items():
            # 只从启用的客户端获取Tracker
            if not client_info[
                "config"
            ].get("enable", False):
                continue
            try:
                client_name = (
                    client_info[
                        "config"
                    ].get(
                        "name",
                        client_id
                    )
                )
                trackers = client_info[
                    "client"
                ].get_trackers()
                logger.info(
                    f"从 {client_name} "
                    f"获取到 {len(trackers)} 个Tracker"
                )
                all_trackers.update(
                    trackers
                )
            except Exception as e:
                logger.error(
                    f"从客户端 {client_id} "
                    f"获取Tracker失败: "
                    f"{str(e)}"
                )
        return list(all_trackers)

    def import_trackers_from_clients(self):
        """
        自动从所有已启用下载器获取Tracker域名
        并返回详细信息
        """
        all_domains = set()
        client_results = {}
        for client_id, client_info in self.clients.items():
            # 只从启用的客户端导入Tracker
            if not client_info[
                "config"
            ].get("enable", False):
                continue
            client_name = (
                client_info[
                    "config"
                ].get(
                    "name",
                    client_id
                )
            )
            client_type = (
                client_info[
                    "config"
                ].get(
                    "type",
                    "unknown"
                )
            )
            try:
                trackers = client_info[
                    "client"
                ].get_trackers()
                client_results[client_id] = {
                    "name": client_name,
                    "type": client_type,
                    "trackers": trackers,
                    "count": len(trackers),
                    "success": True
                }
                all_domains.update(
                    trackers
                )
                logger.info(
                    f"从 {client_name} "
                    f"({client_type}) "
                    f"获取到 {len(trackers)} "
                    f"个Tracker域名"
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
                    f"从 {client_name} "
                    f"({client_type}) "
                    f"获取Tracker失败: "
                    f"{str(e)}"
                )
        total_count = len(
            all_domains
        )
        return {
            "status": (
                "success"
                if total_count > 0
                else "warning"
            ),
            "message": (
                f"成功导入 {total_count} "
                f"个唯一Tracker域名"
                if total_count > 0
                else
                "未发现可导入的Tracker域名"
            ),
            "total_count": total_count,
            "client_results": client_results,
            "all_domains": list(
                all_domains
            )
        }

    def get_clients_info(
        self
    ) -> List[Dict[str, Any]]:
        """获取所有客户端信息"""
        clients_info = []
        for client_id, client_info in self.clients.items():
            clients_info.append({
                "id": client_id,
                "name": (
                    client_info[
                        "config"
                    ].get(
                        "name",
                        client_id
                    )
                ),
                "type": (
                    client_info[
                        "config"
                    ].get("type")
                ),
                "host": (
                    client_info[
                        "config"
                    ].get("host")
                ),
                "port": (
                    client_info[
                        "config"
                    ].get("port")
                ),
                "enabled": (
                    client_info[
                        "config"
                    ].get(
                        "enable",
                        False
                    )
                )
            })
        return clients_info
