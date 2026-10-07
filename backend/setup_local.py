"""Provision an isolated local demo. Never commit the generated token or database."""
from pathlib import Path
from datetime import timedelta
from app import Service, iso, now

if __name__ == '__main__':
    directory = Path(__file__).resolve().parent / 'data'
    service = Service(directory / 'hidear.sqlite3')
    token_path = directory / 'console.token'
    if not token_path.exists():
        token_path.write_text(service.issue_token('local-demo'), encoding='utf-8')
    service.import_public({
        'title': '流程体验公告（模拟，不是真实报名活动）',
        'source_url': 'https://example.org/hidear-demo',
        'city': '全国', 'topic': '体验',
        'summary': '仅用于验证信息查询、行动清单和事项记录；不能据此报名。',
        'deadline_at': iso(now() + timedelta(days=30)),
        'verification_status': 'unverified',
        'unknown_fields': ['真实活动、条件、材料和报名入口均不存在'],
    })
    print('Local demo ready. User token is stored only in backend/data/console.token.')
