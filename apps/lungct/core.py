import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return prefix + '_' + uuid4().hex


def key(prefix, *values):
    return prefix + '_' + hashlib.sha256('\0'.join(map(str, values)).encode()).hexdigest()[:24]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def code(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise ValueError('请输入 1–64 位研究代号（字母、数字、下划线或短横线）')
    return value


def owned(state, table, identity, project):
    item = state[table].get(identity)
    if item is None or item.get('project_id') != project:
        raise ValueError('记录不存在或所属项目不一致')
    return item
