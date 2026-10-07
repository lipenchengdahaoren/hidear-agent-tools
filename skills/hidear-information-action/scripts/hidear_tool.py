"""Run HiDear tools without exposing credentials to model arguments or output."""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

WRITE_TOOLS = {'save_information', 'create_followup', 'update_followup'}
READ_TOOLS = {'search_information', 'get_information', 'prepare_action', 'list_followups'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def run(tool, arguments, request_id=None):
    base = os.environ.get('HIDEAR_BASE_URL', '').rstrip('/')
    parsed = urlsplit(base)
    local = parsed.hostname in ('127.0.0.1', 'localhost', '::1')
    if not base or parsed.scheme not in ('https', 'http') or parsed.scheme == 'http' and not local or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('请配置 HTTPS HIDEAR_BASE_URL，本地体验可用 http://127.0.0.1:8765')
    if tool not in WRITE_TOOLS | READ_TOOLS:
        raise ValueError('工具名称不支持')
    token_file = os.environ.get('HIDEAR_TOKEN_FILE')
    if not token_file:
        raise ValueError('请由宿主配置 HIDEAR_TOKEN_FILE，不把凭证放在对话参数中')
    token = Path(token_file).read_text(encoding='utf-8').strip()
    if not token or len(token) > 200 or '\n' in token or '\r' in token:
        raise ValueError('用户凭证文件格式不正确')
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}
    if tool in WRITE_TOOLS:
        if not request_id or not 8 <= len(request_id) <= 128:
            raise ValueError('写操作必须提供 --request-id；重试使用原标识，新操作使用新标识')
        headers['Idempotency-Key'] = request_id
    request = Request(base + '/tools/' + tool, data=json.dumps(arguments, ensure_ascii=False).encode(), headers=headers, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            return json.loads(response.read(131072))
    except HTTPError as error:
        try:
            return json.loads(error.read(131072))
        except (ValueError, UnicodeError):
            return {'success': False, 'error': {'code': 'http_error', 'message': '接口返回错误，HTTP ' + str(error.code)}, 'result': None}
    except URLError:
        return {'success': False, 'error': {'code': 'connection_failed', 'message': '无法连接工具服务；写操作结果未知，重试须使用原 request-id'}, 'result': None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tool', choices=sorted(WRITE_TOOLS | READ_TOOLS))
    parser.add_argument('--request-id')
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)
        result = run(args.tool, data, args.request_id)
    except (ValueError, OSError):
        result = {'success': False, 'result': None, 'error': {'code': 'configuration_or_input_error', 'message': '请检查宿主服务地址、私有凭证文件和 JSON 输入；写操作必须提供 request-id'}}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
