"""iyp 内置默认关键词组（三层配置的第一层）。

用户侧配置文件为项目根目录的 iyp.toml，结构见 README。
此处只放 keyword check 的默认关键词组、默认跳过文件名与 IP 白名单；
.gitignore 问答树在 gitignore_gen.py 内。
"""

# 每个关键词组: {name, pattern(正则), description, severity}
# severity: high=疑似真实凭证  medium=疑似本机隐私信息  low=仅提示
DEFAULT_KEYWORDS = [
    # ---- 密钥/凭证前缀 ----
    {"name": "aws_access_key", "pattern": r"AKIA[0-9A-Z]{16}",
     "description": "AWS Access Key ID", "severity": "high"},
    {"name": "aws_secret", "pattern": r"(?i)aws(.{0,20})?['\"][0-9a-zA-Z/+]{40}['\"]",
     "description": "AWS Secret Access Key 形态字符串", "severity": "high"},
    {"name": "github_pat", "pattern": r"gh[pousr]_[A-Za-z0-9]{36,255}",
     "description": "GitHub token (ghp_/gho_/ghu_/ghs_/ghr_)", "severity": "high"},
    {"name": "gitlab_pat", "pattern": r"glpat-[A-Za-z0-9_\-]{20,}",
     "description": "GitLab PAT", "severity": "high"},
    {"name": "openai_key", "pattern": r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}",
     "description": "OpenAI / 通用 sk- 密钥", "severity": "high"},
    {"name": "anthropic_key", "pattern": r"sk-ant-[A-Za-z0-9_\-]{20,}",
     "description": "Anthropic API key", "severity": "high"},
    {"name": "slack_token", "pattern": r"xox[abprs]-[A-Za-z0-9\-]{10,}",
     "description": "Slack token", "severity": "high"},
    {"name": "private_key_block", "pattern": r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY( BLOCK)?-----",
     "description": "私钥块", "severity": "high"},
    # ---- 数据库凭证 ----
    {"name": "db_url", "pattern": r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp|jdbc:[a-z0-9]+)://[^\s'\"<>]+:[^\s'\"<>]+@",
     "description": "带账号密码的数据库连接串（脱敏示例 user:***@db / <password> 形态除外，由代码过滤）", "severity": "high"},
    # ---- cookie ----
    {"name": "cookie_header", "pattern": r"(?i)\bcookie\s*:\s*[^\n]{10,}",
     "description": "Cookie 请求头", "severity": "high"},
    {"name": "session_cookie", "pattern": r"(?i)\b(sessionid|jsessionid|phpsessid|csrftoken|auth_token|remember[-_]?token)\s*[=:]\s*['\"]?[A-Za-z0-9_\-\.]{16,}",
     "description": "常见会话/CSRF cookie 值", "severity": "high"},
    # ---- 本机用户名 / 用户目录 / 主机名 / Windows 路径 / 本机 IP ----
    # 这些是运行时按当前系统动态生成的（见 build_host_keywords / build_local_ip_keywords），
    # 静态列表里不再放宽泛的 /Users/xxx / C:\\Users 正则，避免把文档举例也当命中。
]


def build_host_keywords() -> list[dict]:
    """按当前系统实测拼出本机关键词：用户名、家目录、主机名、Windows 风格路径。

    只匹配真实值（转义后的字面量），不会把「/Users/xxx/...」这类举例当命中。
    """
    import getpass
    import os
    import platform
    import re as _re

    kws: list[dict] = []

    def add(name: str, literal: str, description: str, severity: str = "medium") -> None:
        literal = literal.strip().rstrip("/")
        if not literal or len(literal) < 3:
            return
        kws.append({
            "name": name,
            "pattern": _re.escape(literal),
            "description": f"{description}（实测值: {literal}）",
            "severity": severity,
        })

    try:
        user = getpass.getuser()
        add("my_username", user, "本机用户名")
    except Exception:
        pass

    home = os.path.expanduser("~")
    if home and home != "/":
        add("my_home_dir", home, "本机用户目录")
        # Windows 风格变体（在 WSL 下工作时 /mnt/c/Users/xxx 与 C:\\Users\\xxx 都可能泄进文件）
        m = _re.search(r"[\\/](Users[\\/][^\\/]+)$", home)
        if m:
            win_user = _re.split(r"[\\/]", m.group(1))[-1]
            add("my_windows_userpath", f"C:\\\\Users\\\\{win_user}", "Windows 用户目录（C:\\\\Users\\\\<用户名>）")
            add("my_windows_userpath_fwd", f"C:/Users/{win_user}", "Windows 用户目录（正斜杠变体）")

    try:
        host = platform.node() or os.uname().nodename
        base = host.split(".")[0]
        if base and base not in ("localhost",):
            add("my_hostname", base, "本机主机名")
    except Exception:
        pass

    return kws


def detect_local_ips() -> list[str]:
    """探测本机局域网 IP（主机名解析 + UDP connect 出口探测，不发包）。"""
    import socket
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if "." in ip and not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(ips)


# IP 白名单：永不算命中项的 IP（回环、常见公共 DNS）。用户可在 toml [check].ip_whitelist 追加。
DEFAULT_IP_WHITELIST = [
    "127.0.0.1", "0.0.0.0",
    "8.8.8.8", "8.8.4.4",               # Google DNS
    "1.1.1.1", "1.0.0.1",               # Cloudflare DNS
    "9.9.9.9",                          # Quad9
    "208.67.222.222", "208.67.220.220", # OpenDNS
    "223.5.5.5", "223.6.6.6",           # 阿里 DNS
    "119.29.29.29",                     # 腾讯 DNS
    "114.114.114.114",                  # 114 DNS
    "255.255.255.255",
]


def build_local_ip_keywords() -> list[dict]:
    """动态本机组第二部分：本机局域网 IP（探测到的每个 IP 一组）。"""
    import re as _re
    return [
        {
            "name": f"my_local_ip_{ip.replace('.', '_')}",
            "pattern": _re.escape(ip),
            "description": f"本机局域网 IP（探测值: {ip}）",
            "severity": "medium",
        }
        for ip in detect_local_ips()
    ]


STATIC_KEYWORDS_TAIL = [
    # ---- IPv4（任意公网/私网地址都命中；回环与白名单内的 IP 由 ip_whitelist 排除）----
    {"name": "ipv4", "pattern": r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\.\d)(?![\d.])",
     "description": "IPv4 地址（127.0.0.1/0.0.0.0/常见 DNS/白名单内的除外）", "severity": "medium"},
    # ---- MAC 地址 ----
    {"name": "mac_address", "pattern": r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])",
     "description": "MAC 地址（冒号形式）", "severity": "medium"},
]


def all_default_keywords() -> list[dict]:
    """静态默认组 + 运行时动态本机组（用户名/路径 + 本机 IP）。"""
    return DEFAULT_KEYWORDS + STATIC_KEYWORDS_TAIL + build_host_keywords() + build_local_ip_keywords()

# 默认忽略的文件名（即使被 git 跟踪也跳过内容扫描，如锁文件）
DEFAULT_SKIP_FILES = [
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Cargo.lock", "composer.lock", "Gemfile.lock",
]
