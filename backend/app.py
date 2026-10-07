"""HiDear tools: dependency-free WSGI service. Development binds loopback only."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
UTC = timezone.utc


class Problem(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def now():
    return datetime.now(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat()


def timestamp(value):
    if not isinstance(value, str):
        raise Problem("invalid_time", "时间必须是带时区的 ISO 8601 字符串")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Problem("invalid_time", "时间格式不正确")
    if result.tzinfo is None:
        raise Problem("invalid_time", "时间必须包含时区，例如 +08:00")
    return result.astimezone(UTC)


def field(kind, description, **extra):
    return {"type": kind, "description": description, **extra}


def schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


TEXT = lambda description, limit=200: field("string", description, minLength=1, maxLength=limit)
TOOLS = {
    "save_information": {
        "description": "保存当前用户提供的公告线索。始终标为未核实；不能用于替代官方核验。",
        "schema": schema({"title": TEXT("公告标题"), "source_url": TEXT("官方原文 HTTPS 链接", 2000), "city": TEXT("城市或全国", 80), "topic": TEXT("主题", 80), "summary": TEXT("公开信息摘要，不填个人资料", 2000), "deadline_at": TEXT("截止时间，带时区；未知则不传", 40)}, ("title", "source_url", "city", "topic", "summary")),
        "write": True,
    },
    "search_information": {
        "description": "查询已收录的公开信息与当前用户的未核实线索。不是全网搜索；空结果不表示没有政策。默认排除过期、撤回事项。",
        "schema": schema({"query": TEXT("标题、主题或摘要关键词", 200), "city": TEXT("城市；同时匹配全国事项", 80), "include_expired": field("boolean", "是否包含过期事项"), "limit": field("integer", "最多返回条数", minimum=1, maximum=20)}),
        "write": False,
    },
    "get_information": {
        "description": "获取公告及核验状态、来源和缺失字段。只能读取公开条目或当前用户线索。",
        "schema": schema({"information_id": TEXT("信息标识", 64)}, ("information_id",)), "write": False,
    },
    "prepare_action": {
        "description": "生成公告行动清单，不提交报名。过期或撤回的信息不能生成报名计划；未核实信息明确标记待核实。",
        "schema": schema({"information_id": TEXT("信息标识", 64)}, ("information_id",)), "write": False,
    },
    "create_followup": {
        "description": "用户明确同意后记录事项和到期时间。记录成功不代表手机通知成功；返回通知状态和日历导出链接。禁止填证件、医疗或财务资料。",
        "schema": schema({"title": TEXT("待办标题，不含敏感资料"), "due_at": TEXT("用户确认的时间，必须带时区", 40), "information_id": TEXT("关联信息标识，未知则不传", 64), "confirmed": field("boolean", "用户是否明确确认记录此事项")}, ("title", "due_at", "confirmed")), "write": True,
    },
    "list_followups": {
        "description": "查询当前用户的跟进事项或到期事项。身份由认证决定，不接受 user_id。",
        "schema": schema({"status": field("string", "事项状态", enum=["open", "completed", "cancelled", "all"]), "due_only": field("boolean", "只返回已经到期的未完成事项")}), "write": False,
    },
    "update_followup": {
        "description": "用户确认后完成、取消或改期自己的待办。version 防止覆盖并发更新。",
        "schema": schema({"followup_id": TEXT("跟进标识", 64), "version": field("integer", "当前版本", minimum=1), "status": field("string", "新状态", enum=["open", "completed", "cancelled"]), "due_at": TEXT("新的带时区时间", 40), "confirmed": field("boolean", "用户明确同意修改")}, ("followup_id", "version", "confirmed")), "write": True,
    },
}


def validate(data, definition):
    if not isinstance(data, dict):
        raise Problem("invalid_input", "参数必须是对象")
    properties = definition["properties"]
    if set(data) - set(properties):
        raise Problem("unknown_field", "包含未支持的参数，不接受 user_id 或身份覆盖")
    if set(definition["required"]) - set(data):
        raise Problem("missing_field", "缺少必要参数")
    for key, value in data.items():
        spec = properties[key]
        expected = {"string": str, "boolean": bool, "integer": int}[spec["type"]]
        if type(value) is not expected:
            raise Problem("invalid_input", f"{key} 类型不正确")
        if isinstance(value, str) and (not value.strip() or len(value) > spec.get("maxLength", 2000)):
            raise Problem("invalid_input", f"{key} 长度不正确")
        if "enum" in spec and value not in spec["enum"]:
            raise Problem("invalid_input", f"{key} 值不支持")
        if type(value) is int and not spec.get("minimum", value) <= value <= spec.get("maximum", value):
            raise Problem("invalid_input", f"{key} 超出范围")


def url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise Problem("invalid_url", "请使用不包含账号密码的 HTTPS 原文地址")
    return value


class Service:
    def __init__(self, database):
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY,subject TEXT NOT NULL,expires TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS information(id TEXT PRIMARY KEY,owner TEXT NOT NULL,source_url TEXT NOT NULL,data TEXT NOT NULL,UNIQUE(owner,source_url));
            CREATE TABLE IF NOT EXISTS followups(id TEXT PRIMARY KEY,subject TEXT NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests(subject TEXT NOT NULL,key TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(subject,key));
            CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,subject TEXT NOT NULL,tool TEXT NOT NULL,created_at TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def issue_token(self, subject, days=30):
        if not subject or len(subject) > 100 or subject == "public":
            raise ValueError("使用非 public 的独立用户标识")
        token = secrets.token_urlsafe(48)
        with self.connection() as db:
            db.execute("INSERT INTO tokens VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), subject, iso(now() + timedelta(days=days))))
        return token

    def authenticate(self, token):
        if not token or len(token) > 200:
            raise Problem("unauthorized", "需要有效的用户凭证", 401)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connection() as db:
            row = db.execute("SELECT subject,expires FROM tokens WHERE hash=?", (digest,)).fetchone()
        if not row or timestamp(row["expires"]) <= now():
            raise Problem("unauthorized", "凭证无效或已过期", 401)
        return row["subject"]

    def import_public(self, record):
        """Operator-only local command. Verification must be supplied with evidence."""
        required = {"title", "source_url", "city", "topic", "summary"}
        if not isinstance(record, dict) or not required <= set(record):
            raise Problem("invalid_record", "公告缺少标题、来源、城市、主题或摘要")
        for key in required:
            if not isinstance(record[key], str) or not record[key].strip() or len(record[key]) > 4000:
                raise Problem("invalid_record", "公告字段格式不正确")
        url(record["source_url"])
        status = record.get("verification_status", "unverified")
        if status not in ("unverified", "partially_verified", "verified", "withdrawn"):
            raise Problem("invalid_record", "核验状态不支持")
        if status in ("verified", "partially_verified") and not (record.get("verification_evidence") and record.get("checked_at")):
            raise Problem("missing_evidence", "核验状态必须附人工核验时间与证据")
        for key in ("deadline_at", "checked_at", "published_at"):
            if record.get(key):
                record[key] = iso(timestamp(record[key]))
        for key in ("materials", "conditions", "unknown_fields"):
            if key in record and (not isinstance(record[key], list) or any(not isinstance(v, str) or len(v) > 500 for v in record[key])):
                raise Problem("invalid_record", "条件和材料必须为文本列表")
        if record.get("action_url"):
            url(record["action_url"])
        with self.connection() as db:
            row = db.execute("SELECT id FROM information WHERE owner='public' AND source_url=?", (record["source_url"],)).fetchone()
            identity = row["id"] if row else hashlib.sha256(record["source_url"].encode()).hexdigest()[:32]
            result = dict(record, id=identity, verification_status=status, saved_at=iso(now()))
            db.execute("INSERT INTO information VALUES(?,?,?,?) ON CONFLICT(owner,source_url) DO UPDATE SET data=excluded.data", (identity, "public", record["source_url"], json.dumps(result, ensure_ascii=False)))
        return result

    def information(self, db, subject, identity):
        row = db.execute("SELECT data FROM information WHERE id=? AND owner IN ('public',?)", (identity, subject)).fetchone()
        if not row:
            raise Problem("not_found", "信息不存在或无访问权限", 404)
        item = json.loads(row["data"])
        item["expired"] = bool(item.get("deadline_at") and timestamp(item["deadline_at"]) <= now())
        return item

    def call(self, token, tool, arguments, key=None):
        subject = self.authenticate(token)
        if tool not in TOOLS:
            raise Problem("unknown_tool", "工具不存在", 404)
        validate(arguments, TOOLS[tool]["schema"])
        write = TOOLS[tool]["write"]
        if write and (not key or not 8 <= len(key) <= 128):
            raise Problem("idempotency_required", "写操作需要 8-128 字符的 Idempotency-Key")
        fingerprint = hashlib.sha256(json.dumps([tool, arguments], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.connection() as db:
            if write:
                db.execute("BEGIN IMMEDIATE")
                previous = db.execute("SELECT fingerprint,result FROM requests WHERE subject=? AND key=?", (subject, key)).fetchone()
                if previous:
                    if not hmac.compare_digest(previous["fingerprint"], fingerprint):
                        raise Problem("idempotency_conflict", "该幂等键已用于不同请求", 409)
                    return json.loads(previous["result"])
            result = getattr(self, tool)(db, subject, arguments)
            response = {"success": True, "request_id": uuid.uuid4().hex, "result": result, "error": None}
            if write:
                db.execute("INSERT INTO requests VALUES(?,?,?,?)", (subject, key, fingerprint, json.dumps(response, ensure_ascii=False)))
                db.execute("INSERT INTO audit VALUES(?,?,?,?)", (response["request_id"], subject, tool, iso(now())))
            return response

    def save_information(self, db, subject, args):
        url(args["source_url"])
        record = dict(args, verification_status="unverified", saved_at=iso(now()), unknown_fields=["official_verification", "conditions", "materials"])
        if args.get("deadline_at"):
            record["deadline_at"] = iso(timestamp(args["deadline_at"]))
        row = db.execute("SELECT id FROM information WHERE owner=? AND source_url=?", (subject, args["source_url"])).fetchone()
        record["id"] = row["id"] if row else uuid.uuid4().hex
        db.execute("INSERT INTO information VALUES(?,?,?,?) ON CONFLICT(owner,source_url) DO UPDATE SET data=excluded.data", (record["id"], subject, args["source_url"], json.dumps(record, ensure_ascii=False)))
        return record

    def search_information(self, db, subject, args):
        items = []
        for row in db.execute("SELECT id FROM information WHERE owner IN ('public',?)", (subject,)):
            item = self.information(db, subject, row["id"])
            if not args.get("include_expired", False) and (item["expired"] or item["verification_status"] == "withdrawn"):
                continue
            if args.get("city") and item["city"] not in (args["city"], "全国"):
                continue
            haystack = " ".join(item.get(k, "") for k in ("title", "topic", "summary")).casefold()
            if args.get("query") and args["query"].casefold() not in haystack:
                continue
            items.append(item)
        items.sort(key=lambda i: (i.get("deadline_at") or "9999", i["id"]))
        return {"items": items[:args.get("limit", 5)], "total": len(items), "scope": "stored_information_only", "searched_at": iso(now()), "empty_message": "当前信息库没有匹配结果。请继续使用联网搜索核实，不代表没有相关政策。" if not items else None}

    def get_information(self, db, subject, args):
        return self.information(db, subject, args["information_id"])

    def prepare_action(self, db, subject, args):
        item = self.get_information(db, subject, args)
        if item["expired"] or item["verification_status"] == "withdrawn":
            raise Problem("not_actionable", "事项已过期或撤回，请先核对是否有新公告", 409)
        verified = item["verification_status"] == "verified"
        return {"information_id": item["id"], "title": item["title"], "verification_status": item["verification_status"], "source_url": item["source_url"], "action_url": item.get("action_url"), "deadline_at": item.get("deadline_at"), "conditions": item.get("conditions", []), "materials": item.get("materials", []), "unknown_fields": item.get("unknown_fields", []), "steps": (["核对公告更新、用户条件和期限", "准备公告要求的材料", "由用户打开官方入口核对并办理"] if verified else ["先阅读官方原文，核对条件、入口、材料和期限", "核验完成后再准备申请"]), "submission_status": "not_submitted", "eligibility_status": "not_determined", "notice": "本工具只生成清单，未提交报名。"}

    def create_followup(self, db, subject, args):
        if args["confirmed"] is not True:
            raise Problem("confirmation_required", "请先获得用户对事项和时间的明确确认")
        due = timestamp(args["due_at"])
        if due <= now():
            raise Problem("past_due", "提醒时间已过去，请确认新的时间")
        information = self.information(db, subject, args["information_id"]) if args.get("information_id") else None
        identity = uuid.uuid4().hex
        record = {"id": identity, "title": args["title"], "due_at": iso(due), "information_id": args.get("information_id"), "source_url": information["source_url"] if information else None, "status": "open", "version": 1, "created_at": iso(now()), "notification_status": "not_configured", "calendar_url": f"/v1/followups/{identity}/calendar.ics", "notice": "已记录待办，尚未设置手机通知。可导出日历，在手机中确认导入与提醒权限。"}
        db.execute("INSERT INTO followups VALUES(?,?,?)", (identity, subject, json.dumps(record, ensure_ascii=False)))
        return record

    def list_followups(self, db, subject, args):
        status = args.get("status", "open")
        items = [json.loads(r["data"]) for r in db.execute("SELECT data FROM followups WHERE subject=?", (subject,))]
        items = [i for i in items if (status == "all" or i["status"] == status) and (not args.get("due_only") or i["status"] == "open" and timestamp(i["due_at"]) <= now())]
        return {"items": sorted(items, key=lambda i: (i["due_at"], i["id"])), "notification_status": "not_configured"}

    def followup(self, db, subject, identity):
        row = db.execute("SELECT data FROM followups WHERE id=? AND subject=?", (identity, subject)).fetchone()
        if not row:
            raise Problem("not_found", "事项不存在或无访问权限", 404)
        return json.loads(row["data"])

    def update_followup(self, db, subject, args):
        if args["confirmed"] is not True:
            raise Problem("confirmation_required", "请先获得用户明确同意")
        if not ("status" in args or "due_at" in args):
            raise Problem("missing_change", "请选择状态或新的时间")
        item = self.followup(db, subject, args["followup_id"])
        if item["version"] != args["version"]:
            raise Problem("version_conflict", "事项已被更新，请重新读取后再修改", 409)
        if "due_at" in args:
            due = timestamp(args["due_at"])
            if due <= now():
                raise Problem("past_due", "新的时间已过去")
            item["due_at"] = iso(due)
        item["status"] = args.get("status", item["status"])
        item["version"] += 1
        item["updated_at"] = iso(now())
        db.execute("UPDATE followups SET data=? WHERE id=? AND subject=?", (json.dumps(item, ensure_ascii=False), item["id"], subject))
        return item

    def calendar(self, token, identity):
        subject = self.authenticate(token)
        with self.connection() as db:
            item = self.followup(db, subject, identity)
        if item["status"] != "open":
            raise Problem("not_open", "事项已完成或取消，不再导出提醒", 409)
        escape = lambda s: s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HiDear//Followup//ZH", "BEGIN:VEVENT", f"UID:{identity}@hidear.local", f"DTSTAMP:{now().strftime('%Y%m%dT%H%M%SZ')}", f"DTSTART:{timestamp(item['due_at']).strftime('%Y%m%dT%H%M%SZ')}", f"SUMMARY:{escape(item['title'])}", "DESCRIPTION:HiDear待办。请自行核对官方公告和截止日期。", "BEGIN:VALARM", "TRIGGER:PT0S", "ACTION:DISPLAY", "DESCRIPTION:HiDear待办提醒", "END:VALARM", "END:VEVENT", "END:VCALENDAR"]
        folded = []
        for line in lines:
            chunk = ""
            for char in line:
                if len((chunk + char).encode()) > 73:
                    folded.append(chunk)
                    chunk = " "
                chunk += char
            folded.append(chunk)
        return "\r\n".join(folded) + "\r\n"


def openapi():
    paths = {}
    for name, tool in TOOLS.items():
        params = [{"name": "Idempotency-Key", "in": "header", "required": True, "schema": {"type": "string", "minLength": 8, "maxLength": 128}}] if tool["write"] else []
        paths[f"/tools/{name}"] = {"post": {"operationId": name, "description": tool["description"], "security": [{"bearerAuth": []}], "parameters": params, "requestBody": {"required": True, "content": {"application/json": {"schema": tool["schema"]}}}, "responses": {"200": {"description": "含 success、request_id、result、error 的结果"}, "400": {"description": "输入或确认缺失"}, "401": {"description": "凭证无效"}, "404": {"description": "资源无访问权限"}, "409": {"description": "版本、幂等或过期冲突"}}}}
    for name in ("search_information", "get_information", "prepare_action"):
        definition = json.loads(json.dumps(paths[f"/tools/{name}"]))
        definition["post"]["operationId"] = "public_" + name
        definition["post"]["security"] = []
        definition["post"]["description"] += " 此公开接口仅返回管理员收录的公开信息，不读取用户线索。"
        paths[f"/public/tools/{name}"] = definition
    return {"openapi": "3.1.0", "info": {"title": "HiDear Tools", "version": "0.1.0"}, "paths": paths, "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}}}


class App:
    def __init__(self, service, public_only=False):
        self.service = service
        self.public_only = public_only
        self.last_public_request = None

    def __call__(self, env, start_response):
        path, method = env.get("PATH_INFO", ""), env.get("REQUEST_METHOD", "GET")
        content_type = "application/json; charset=utf-8"
        status = 200
        try:
            if method == "GET" and path == "/health":
                result = {"status": "ok", "version": "0.1.0", "automatic_notifications": False}
                if self.public_only:
                    result["last_public_request"] = self.last_public_request
            elif method == "GET" and path == "/openapi.json":
                result = openapi()
            elif method == "GET" and path == "/":
                result = (ROOT / ("public.html" if self.public_only else "console.html")).read_bytes()
                content_type = "text/html; charset=utf-8"
            elif method == "POST" and path.startswith("/public/tools/"):
                tool = path[len("/public/tools/"):]
                if tool not in ("search_information", "get_information", "prepare_action"):
                    raise Problem("unknown_tool", "公开接口不支持个人记录或写操作", 404)
                if env.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
                    raise Problem("unsupported_media", "需要 application/json", 415)
                try:
                    length = int(env.get("CONTENT_LENGTH") or "0")
                except ValueError:
                    raise Problem("invalid_input", "请求长度无效")
                if length < 1 or length > 16384:
                    raise Problem("request_too_large", "请求必须为 1 至 16384 字节", 413)
                try:
                    arguments = json.loads(env["wsgi.input"].read(length))
                except (ValueError, UnicodeError):
                    raise Problem("invalid_json", "JSON 格式错误")
                validate(arguments, TOOLS[tool]["schema"])
                with self.service.connection() as db:
                    public_result = getattr(self.service, tool)(db, "public", arguments)
                result = {"success": True, "request_id": uuid.uuid4().hex, "result": public_result, "error": None}
            else:
                if self.public_only:
                    raise Problem("not_found", "此演示仅提供公开查询，不保存个人待办", 404)
                auth = env.get("HTTP_AUTHORIZATION", "")
                if not auth.startswith("Bearer "):
                    raise Problem("unauthorized", "需要用户凭证", 401)
                token = auth[7:]
                if method == "GET" and path.startswith("/v1/followups/") and path.endswith("/calendar.ics"):
                    identity = path.split("/")[3]
                    result = self.service.calendar(token, identity).encode()
                    content_type = "text/calendar; charset=utf-8"
                elif method == "POST" and path.startswith("/tools/"):
                    if env.get("CONTENT_TYPE", "").split(";")[0] != "application/json":
                        raise Problem("unsupported_media", "需要 application/json", 415)
                    try:
                        length = int(env.get("CONTENT_LENGTH") or "0")
                    except ValueError:
                        raise Problem("invalid_input", "请求长度无效")
                    if length < 1 or length > 16384:
                        raise Problem("request_too_large", "请求必须为 1 至 16384 字节", 413)
                    try:
                        arguments = json.loads(env["wsgi.input"].read(length))
                    except (ValueError, UnicodeError):
                        raise Problem("invalid_json", "JSON 格式错误")
                    result = self.service.call(token, path[len("/tools/"):], arguments, env.get("HTTP_IDEMPOTENCY_KEY"))
                else:
                    raise Problem("not_found", "接口不存在", 404)
        except Problem as exc:
            status = exc.status
            result = {"success": False, "request_id": uuid.uuid4().hex, "result": None, "error": {"code": exc.code, "message": exc.message}}
        except Exception:
            status = 500
            result = {"success": False, "request_id": uuid.uuid4().hex, "result": None, "error": {"code": "internal_error", "message": "服务暂不可用，请稍后重试"}}
        if isinstance(result, dict) and "success" in result:
            result["code"] = 0 if result["success"] else 1
        if self.public_only and path.startswith('/public/tools/'):
            self.last_public_request = {"time": iso(now()), "method": method, "path": path, "content_type": env.get('CONTENT_TYPE', '').split(';')[0][:80], "status": status, "error_code": result.get('error', {}).get('code') if result.get('error') else None}
        body = result if isinstance(result, bytes) else json.dumps(result, ensure_ascii=False).encode()
        from http import HTTPStatus
        headers = [("Content-Type", content_type), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"), ("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")]
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [body]


def factory():
    service = Service(os.environ.get("HIDEAR_DATABASE", str(ROOT / "data" / "hidear.sqlite3")))
    public_only = os.environ.get("HIDEAR_PUBLIC_ONLY") == "1"
    if public_only:
        for record in json.loads((ROOT / "public-information.json").read_text(encoding="utf-8")):
            service.import_public(record)
    return App(service, public_only=public_only)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "token", "import", "openapi"])
    parser.add_argument("--database", default=str(ROOT / "data" / "hidear.sqlite3"))
    parser.add_argument("--subject")
    parser.add_argument("--file")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "openapi":
        print(json.dumps(openapi(), ensure_ascii=False, indent=2))
        return
    service = Service(args.database)
    if args.command == "token":
        print(service.issue_token(args.subject))
    elif args.command == "import":
        records = json.loads(Path(args.file).read_text(encoding="utf-8"))
        for record in records:
            service.import_public(record)
        print(f"Imported {len(records)} public notices")
    else:
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        class QuietHandler(WSGIRequestHandler):
            def log_message(self, *_):
                pass
        print(f"HiDear local console: http://127.0.0.1:{args.port}", flush=True)
        with make_server("127.0.0.1", args.port, App(service), handler_class=QuietHandler) as server:
            server.serve_forever()


if __name__ == "__main__":
    main()

