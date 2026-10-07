"""Build public artifacts from an explicit allowlist; never include private data."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))
from app import TOOLS, openapi

PUBLIC_FILES = [
    'render.yaml', 'backend/public.html', 'backend/public-information.json', 'docs/free-demo.md',
    'README.md', '.gitignore', '.github/workflows/checks.yml', 'build_release.py',
    'backend/app.py', 'backend/console.html', 'backend/test_app.py', 'backend/setup_local.py',
    'backend/Dockerfile', 'backend/.dockerignore', 'review-cases.md',
    'skills/hidear-information-action/SKILL.md',
    'skills/hidear-information-action/scripts/hidear_tool.py',
    'skills/hidear-information-action/references/verification.md',
    'skills/hidear-information-action/references/tools.md',
    'skills/hidear-information-action/references/openapi.json',
    'docs/vivo-registration.md',
]


def manifests(base_url):
    result = []
    for name in ('search_information', 'get_information', 'prepare_action'):
        identity = 'hidear_' + name
        labels = {'search_information': '查询重要信息', 'get_information': '读取公告详情', 'prepare_action': '准备行动清单'}
        description = {'overview': TOOLS[name]['description'], 'useCases': '查询管理员收录的公开公告；不读取个人记录', 'constraints': '需服务已部署。不是全网搜索；不提交报名、不设置提醒', 'output': 'code、success、request_id、result、error', 'example': '在当前信息库查询公开信息'}
        protocol = {'operationId': identity, 'name': labels[name], 'appCode': 'hiDear', 'description': json.dumps(description, ensure_ascii=False), 'skillSource': '2', 'agentVersion': 30000, 'androidPerm': '[]', 'supportDevice': 5, 'executeScenarios': 7, 'remark': '', 'protocolType': 'vivo', 'daMetaData': None, 'skillFrameworkSpec': 'skillFw2_4', 'functionName': identity, 'parameters': TOOLS[name]['schema'], 'returns': {'type': 'Object', 'description': '统一返回结构', 'properties': {'code': {'type': 'integer', 'enum': [0, 1]}, 'success': {'type': 'boolean'}, 'request_id': {'type': 'string'}, 'result': {'type': 'object'}, 'error': {'type': 'object'}}, 'required': ['code', 'success', 'request_id']}, 'platformConfigs': {'customBasicFields': {}, 'customParamFields': {}, 'customReturnFields': {}}}
        result.append({'operationId': identity, 'name': labels[name], 'appCode': 'hiDear', 'appName': 'HiDear', 'description': json.dumps(description, ensure_ascii=False), 'kitVer': 'skillFw2_4', 'callDemo': '[]', 'skillUrl': base_url + '/public/tools/' + name if base_url else '', 'httpHeaders': '{"Content-Type":"application/json"}', 'defBodyParams': '{}', 'timeout': '5000', 'skillProtocol': json.dumps(protocol, ensure_ascii=False), 'triggerQueries': ['查找和我有关的重要信息', '帮我核对这条公告', '查看培训报名条件', '我要准备什么材料', '这条信息截止了吗']})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='')
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    if base:
        parsed = urlsplit(base)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Public deployment requires a credential-free HTTPS base URL')
    reference = ROOT / 'skills/hidear-information-action/references/openapi.json'
    reference.write_text(json.dumps(openapi(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    entries = []
    for relative in PUBLIC_FILES:
        entries.append({'path': relative, 'content': (ROOT / relative).read_text(encoding='utf-8-sig')})
    draft = json.dumps(manifests(base), ensure_ascii=False, indent=2) + '\n'
    (output / 'vivo-webservices.draft.json').write_text(draft, encoding='utf-8')
    entries.append({'path': 'integrations/vivo-webservices.draft.json', 'content': draft})
    (output / 'source-files.json').write_text(json.dumps(entries, ensure_ascii=False), encoding='utf-8')
    package = output / 'hidear-information-action.zip'
    with ZipFile(package, 'w', ZIP_DEFLATED) as archive:
        for entry in entries:
            if entry['path'].startswith('skills/'):
                archive.writestr(entry['path'][len('skills/'):], entry['content'].encode())
    with ZipFile(package) as archive:
        assert len(archive.namelist()) == 5
        assert all(name.startswith('hidear-information-action/') and '..' not in name for name in archive.namelist())
    report = {'files': len(entries), 'skill_files': 5, 'tool_count': len(TOOLS), 'public_tool_count': 3, 'sha256': hashlib.sha256(package.read_bytes()).hexdigest(), 'vivo_endpoints_configured': bool(base)}
    (output / 'build-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
