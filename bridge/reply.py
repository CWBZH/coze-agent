"""
回复类型枚举
"""
from enum import Enum
import hashlib


class ReplyType(Enum):
    TEXT = 1  # 文本
    IMAGE = 2  # 图片文件
    IMAGE_URL = 3  # 图片URL
    VIDEO_URL = 4  # 视频URL
    FILE = 5  # 文件
    LINK = 6 # 链接
    def __str__(self):
        return self.name


class Reply:
    def __init__(self, type: ReplyType = None, content=None):
        self.type = type
        self.content = content

    def __str__(self):
        content_text = "" if self.content is None else str(self.content)
        content_hash = hashlib.sha256(content_text.encode("utf-8", errors="ignore")).hexdigest()[:12] if content_text else ""
        return "Reply(type={}, content_length={}, content_hash={})".format(self.type, len(content_text), content_hash)
