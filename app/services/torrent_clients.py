import logging
import requests
import json
import time
from typing import List, Dict, Any, Optional, Union
import traceback
logger = logging.getLogger(__name__)
class TorrentClientBase:
    """下载器客户端基类"""
    def __init__(self, host: str, port: int, username: str, password: str, use_https: bool = False):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_https = use_https
        self.base_url = f"{'https' if use_https else 'http'}://{host}:{port}"
        self.session = requests.Session()
        logger.debug(f"初始化下载器客户端: {self.__class__.__name__}, URL: {self.base_url}")
    
    def test_connection(self) -> Dict[str, Any]:
        """测试连接"""
        raise NotImplementedError("子类必须实现此方法")
    
    def get_trackers(self) -> List[str]:
        """获取所有种子的Tracker列表"""
        raise NotImplementedError("子类必须实现此方法")
class QBittorrentClient(TorrentClientBase):
    """qBittorrent客户端 - 使用直接API调用，自动检测SID cookie"""
    def __init__(self, host: str, port: int, username: str, password: str, use_https: bool = False):
        super().__init__(host, port, username, password, use_https)
        logger.info(f"初始化qBittorrent客户端: {host}:{port}, 使用HTTPS: {use_https}")
        self.api_url = f"{self.base_url}/api/v2"
        logger.debug(f"qBittorrent API URL: {self.api_url}")
        logger.debug(f"qBittorrent认证信息: 用户名: {username}, 密码长度: {len(password) if password else 0}")
    
    def login(self) -> bool:
        """登录qBittorrent WebUI，强制检测SID cookie"""
        try:
            login_url = f"{self.api_url}/auth/login"
            logger.debug(f"尝试登录qBittorrent: {login_url}")
            data = {"username": self.username, "password": self.password}
            response = self.session.post(login_url, data=data, timeout=10)
            logger.debug(f"登录响应: 状态码={response.status_code}, 内容='{response.text}', cookie={self.session.cookies}")
            # 兼容新版 qBittorrent：cookie 不再固定叫 SID，而是 QBT_SID_xxxx
            sid = None
            for cookie_name, cookie_value in self.session.cookies.items():
                if cookie_name.startswith("QBT_SID_"):
                    sid = cookie_value
                    break
            # 保留旧版本兼容，旧版还是 SID
            if sid is None:
                sid = self.session.cookies.get('SID')
            logger.debug(f"登录后SID: {sid}")
            if response.status_code == 200 and response.text.lower().startswith('ok') and sid:
                logger.info(f"qBittorrent登录成功，SID={sid}")
                return True
            else:
                logger.error(f"qBittorrent登录失败: 状态码={response.status_code}, 响应='{response.text}', SID={sid}")
                return False
        except Exception as e:
            error_msg = f"qBittorrent登录异常: {type(e).__name__}: {str(e)}"
            logger.error(error_msg)
            logger.debug(traceback.format_exc())
            return False
    
    def test_connection(self) -> Dict[str, Any]:
        """测试qBittorrent连接，登录后强制检查SID并打印cookie"""
        try:
            logger.info(f"测试qBittorrent连接: {self.host}:{self.port}")
            if not self.login():
                sid = None
                for cookie_name, cookie_value in self.session.cookies.items():
                    if cookie_name.startswith("QBT_SID_"):
                        sid = cookie_value
                        break
                if sid is None:
                    sid = self.session.cookies.get('SID')
                logger.error(f"登录失败后SID: {sid}")
                return {
                    "success": False,
                    "message": "登录失败，请检查主机地址、端口、用户名和密码"
                }
            sid = None
            for cookie_name, cookie_value in self.session.cookies.items():
                if cookie_name.startswith("QBT_SID_"):
                    sid = cookie_value
                    break
            if sid is None:
                sid = self.session.cookies.get('SID')
            logger.info(f"登录成功后SID: {sid}")
            version_url = f"{self.api_url}/app/version"
            logger.debug(f"获取qBittorrent版本信息: {version_url}, 当前cookie: {self.session.cookies}")
            response = self.session.get(version_url, timeout=10)
            logger.debug(f"版本信息响应: 状态码={response.status_code}, 内容='{response.text}', cookie={self.session.cookies}")
            if response.status_code == 200:
                version = response.text
                logger.info(f"qBittorrent版本: {version}")
                api_version_url = f"{self.api_url}/app/webapiVersion"
                api_response = self.session.get(api_version_url, timeout=10)
                api_version = api_response.text if api_response.status_code == 200 else "未知"
                logger.info(f"qBittorrent API版本: {api_version}")
                return {
                    "success": True,
                    "message": f"连接成功，qBittorrent版本: {version}, API版本: {api_version}",
                    "version": version,
                    "api_version": api_version
                }
            else:
                error_msg = f"获取qBittorrent版本信息失败: 状态码={response.status_code}, 响应='{response.text}', cookie={self.session.cookies}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "message": error_msg
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
        """获取所有种子的Tracker列表，登录后强制检查SID并打印cookie"""
        try:
            if not self.login():
                sid = None
                for cookie_name, cookie_value in self.session.cookies.items():
                    if cookie_name.startswith("QBT_SID_"):
                        sid = cookie_value
                        break
                if sid is None:
                    sid = self.session.cookies.get('SID')
                logger.error(f"获取Tracker失败: 登录失败，SID={sid}")
                return []
            sid = None
            for cookie_name, cookie_value in self.session.cookies.items():
                if cookie_name.startswith("QBT_SID_"):
                    sid = cookie_value
                    break
            if sid is None:
                sid = self.session.cookies.get('SID')
            logger.info(f"获取Tracker时SID: {sid}")
            torrents_url = f"{self.api_url}/torrents/info"
            response = self.session.get(torrents_url, timeout=15)
            logger.debug(f"获取种子列表响应: 状态码={response.status_code}, cookie={self.session.cookies}")
            if response.status_code != 200:
                logger.error(f"获取种子列表失败: 状态码={response.status_code}, 响应='{response.text}', cookie={self.session.cookies}")
                return []
            torrents = response.json()
            logger.info(f"获取到 {len(torrents)} 个种子")
            tracker_urls = set()
            for torrent in torrents:
                torrent_hash = torrent.get('hash')
                if not torrent_hash:
                    continue
                trackers_url = f"{self.api_url}/torrents/trackers"
                params = {"hash": torrent_hash}
                trackers_response = self.session.get(trackers_url, params=params, timeout=15)
                logger.debug(f"获取种子{torrent_hash}的Tracker响应: 状态码={trackers_response.status_code}, cookie={self.session.cookies}")
                if trackers_response.status_code != 200:
                    logger.warning(f"获取种子 {torrent_hash} 的Tracker失败: 状态码={trackers_response.status_code}, cookie={self.session.cookies}")
                    continue
                trackers = trackers_response.json()
                for tracker in trackers:
                    tracker_url = tracker.get('url', '')
                    if tracker_url and tracker_url.startswith('http'):
                        try:
                            from urllib.parse import urlparse
                            parsed_url = urlparse(tracker_url)
                            domain = parsed_url.netloc
                            if domain:
                                tracker_urls.add(domain)
                                logger.debug(f"提取Tracker域名: {domain}")
                        except Exception as e:
                            logger.error(f"解析Tracker URL失败: {str(e)}")
            logger.info(f"总共提取了 {len(tracker_urls)} 个唯一Tracker域名")
            return list(tracker_urls)
        except Exception as e:
            logger.error(f"获取qBittorrent Tracker列表异常: {type(e).__name__}: {str(e)}")
            logger.debug(traceback.format_exc())
            return []
class TransmissionClient(TorrentClientBase):
    """Transmission客户端"""
    def __init__(self, host: str, port: int, username: str, password: str, use_https: bool = False, path: str = '/transmission/rpc'):
        super().__init__(host, port, username, password, use_https)
        self.rpc_url = f"{self.base_url}{path}"
        self.session_id = None
    
    def _get_session_id(self) -> bool:
        """获取Transmission会话ID"""
        try:
            response = self.session.get(self.rpc_url, auth=(self.username, self.password))
            
            if response.status_code == 409:
                # 从响应头中获取X-Transmission-Session-Id
                self.session_id = response.headers.get('X-Transmission-Session-Id')
                if self.session_id:
                    logger.info("获取Transmission会话ID成功")
                    return True
            
            logger.error(f"获取Transmission会话ID失败: {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"获取Transmission会话ID异常: {str(e)}")
            return False
    
    def _make_request(self, method: str, arguments: Optional[Dict] = None) -> Dict:
        """发送RPC请求到Transmission"""
        if not self.session_id and not self._get_session_id():
            return {"result": "error", "message": "无法获取会话ID"}
        
        headers = {'X-Transmission-Session-Id': self.session_id}
        payload = {
            "method": method,
            "arguments": arguments or {}
        }
        
        try:
            response = self.session.post(
                self.rpc_url,
                headers=headers,
                json=payload,
                auth=(self.username, self.password)
            )
            
            if response.status_code == 409:
                # 会话ID过期，重新获取
                self.session_id = response.headers.get('X-Transmission-Session-Id')
                return self._make_request(method, arguments)
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"result": "error", "message": f"请求失败: {response.status_code}"}
        except Exception as e:
            return {"result": "error", "message": f"请求异常: {str(e)}"}
    
    def test_connection(self) -> Dict[str, Any]:
        """测试Transmission连接"""
        try:
            if not self._get_session_id():
                return {
                    "success": False,
                    "message": "无法获取会话ID，请检查连接信息"
                }
            
            # 获取会话信息
            response = self._make_request("session-get")
            
            if response.get("result") == "success":
                version = response.get("arguments", {}).get("version", "未知")
                return {
                    "success": True,
                    "message": f"连接成功，Transmission版本: {version}",
                    "version": version
                }
            else:
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
            
            # 获取所有种子信息，包括Tracker
            response = self._make_request("torrent-get", {"fields": ["id", "trackers"]})
            
            if response.get("result") != "success":
                logger.error(f"获取种子列表失败: {response.get('message', '未知错误')}")
                return []
            
            torrents = response.get("arguments", {}).get("torrents", [])
            tracker_urls = set()
            
            for torrent in torrents:
                trackers = torrent.get("trackers", [])
                for tracker in trackers:
                    tracker_url = tracker.get("announce", "")
                    if tracker_url and tracker_url.startswith('http'):
                        # 提取域名部分
                        try:
                            from urllib.parse import urlparse
                            parsed_url = urlparse(tracker_url)
                            domain = parsed_url.netloc
                            if domain:
                                tracker_urls.add(domain)
                        except Exception as e:
                            logger.error(f"解析Tracker URL失败: {str(e)}")
            
            return list(tracker_urls)
        except Exception as e:
            logger.error(f"获取Tracker列表异常: {str(e)}")
            return []
class TorrentClientManager:
    """下载器客户端管理器 - 支持多实例动态管理"""
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.clients = {}
        self._init_clients()
    
    def _init_clients(self):
        """初始化下载器客户端 - 支持多实例"""
        # 清空现有客户端
        self.clients = {}
        
        # 获取客户端配置列表
        clients_config = self.config.get("torrent_clients", [])
        
        # 兼容旧配置格式，如果是字典则转换为数组
        if isinstance(clients_config, dict):
            logger.info("检测到旧版本配置格式，正在转换为新格式...")
            converted_clients = []
            
            # 转换 qbittorrent 配置
            if "qbittorrent" in clients_config:
                qb_config = clients_config["qbittorrent"]
                converted_clients.append({
                    "id": "qb_migrated",
                    "name": "qBittorrent (迁移)",
                    "type": "qbittorrent",
                    **qb_config
                })
            
            # 转换 transmission 配置
            if "transmission" in clients_config:
                tr_config = clients_config["transmission"]
                converted_clients.append({
                    "id": "tr_migrated",
                    "name": "Transmission (迁移)",
                    "type": "transmission",
                    **tr_config
                })
            
            clients_config = converted_clients
            # 更新配置
            self.config["torrent_clients"] = clients_config
            logger.info(f"配置转换完成，共转换 {len(converted_clients)} 个客户端")
        
        # 初始化所有客户端（包括禁用的，以便于测试连接）
        for client_config in clients_config:
                
            client_id = client_config.get("id")
            client_type = client_config.get("type")
            
            if not client_id or not client_type:
                logger.warning(f"跳过无效的客户端配置: {client_config}")
                continue
            
            try:
                if client_type == "qbittorrent":
                    client = QBittorrentClient(
                        host=client_config.get("host", "localhost"),
                        port=client_config.get("port", 8080),
                        username=client_config.get("username", ""),
                        password=client_config.get("password", ""),
                        use_https=client_config.get("use_https", False)
                    )
                elif client_type == "transmission":
                    client = TransmissionClient(
                        host=client_config.get("host", "localhost"),
                        port=client_config.get("port", 9091),
                        username=client_config.get("username", ""),
                        password=client_config.get("password", ""),
                        use_https=client_config.get("use_https", False),
                        path=client_config.get("path", "/transmission/rpc")
                    )
                else:
                    logger.warning(f"不支持的客户端类型: {client_type}")
                    continue
                
                self.clients[client_id] = {
                    "client": client,
                    "config": client_config
                }
                logger.info(f"初始化客户端成功: {client_config.get('name', client_id)} ({client_type})")
                
            except Exception as e:
                logger.error(f"初始化客户端失败: {client_config.get('name', client_id)} - {str(e)}")
    
    def update_config(self, config: Dict[str, Any]):
        """更新配置并重新初始化客户端"""
        self.config = config
        self._init_clients()
    
    def test_client_connection(self, client_id: str) -> Dict[str, Any]:
        """测试指定客户端连接"""
        logger.info(f"正在测试客户端连接: {client_id}")
        logger.debug(f"当前已初始化的客户端列表: {list(self.clients.keys())}")
        
        client_info = self.clients.get(client_id)
        if not client_info:
            logger.error(f"未找到客户端: {client_id}, 可用客户端: {list(self.clients.keys())}")
            return {
                "success": False,
                "message": f"未找到客户端: {client_id}, 可能尚未保存或未启用"
            }
        
        try:
            logger.info(f"开始测试客户端 {client_id} 的连接")
            result = client_info["client"].test_connection()
            logger.info(f"客户端 {client_id} 测试结果: {result}")
            return result
        except Exception as e:
            logger.error(f"测试客户端连接失败: {client_id} - {str(e)}")
            return {
                "success": False,
                "message": f"测试连接失败: {str(e)}"
            }
    
    def test_client_connection_by_config(self, client_config: Dict[str, Any]) -> Dict[str, Any]:
        """根据配置临时创建客户端并测试连接"""
        client_type = client_config.get("type")
        
        if not client_type:
            return {"success": False, "message": "缺少客户端类型"}
        
        try:
            # 创建临时客户端进行测试
            if client_type == "qbittorrent":
                client = QBittorrentClient(
                    host=client_config.get("host", "localhost"),
                    port=client_config.get("port", 8080),
                    username=client_config.get("username", ""),
                    password=client_config.get("password", ""),
                    use_https=client_config.get("use_https", False)
                )
            elif client_type == "transmission":
                client = TransmissionClient(
                    host=client_config.get("host", "localhost"),
                    port=client_config.get("port", 9091),
                    username=client_config.get("username", ""),
                    password=client_config.get("password", ""),
                    use_https=client_config.get("use_https", False),
                    path=client_config.get("path", "/transmission/rpc")
                )
            else:
                return {"success": False, "message": f"不支持的客户端类型: {client_type}"}
            
            # 测试连接
            result = client.test_connection()
            return result
        except Exception as e:
            logger.error(f"测试客户端连接失败: {str(e)}")
            return {"success": False, "message": f"测试连接失败: {str(e)}"}
    
    def get_all_trackers(self) -> List[str]:
        """获取所有启用的下载器中的Tracker列表"""
        all_trackers = set()
        
        for client_id, client_info in self.clients.items():
            # 只从启用的客户端获取Tracker
            if not client_info["config"].get("enable", False):
                continue
                
            try:
                client_name = client_info["config"].get("name", client_id)
                trackers = client_info["client"].get_trackers()
                logger.info(f"从 {client_name} 获取到 {len(trackers)} 个Tracker")
                all_trackers.update(trackers)
            except Exception as e:
                logger.error(f"从客户端 {client_id} 获取Tracker失败: {str(e)}")
        
        return list(all_trackers)
    
    def import_trackers_from_clients(self):
        """自动从所有已启用下载器获取Tracker域名并返回详细信息"""
        all_domains = set()
        client_results = {}
        
        for client_id, client_info in self.clients.items():
            # 只从启用的客户端获取Tracker
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
                logger.info(f"从 {client_name} ({client_type}) 获取到 {len(trackers)} 个Tracker域名")
            except Exception as e:
                client_results[client_id] = {
                    "name": client_name,
                    "type": client_type,
                    "trackers": [],
                    "count": 0,
                    "success": False,
                    "error": str(e)
                }
                logger.error(f"从 {client_name} ({client_type}) 获取Tracker失败: {str(e)}")
        
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
