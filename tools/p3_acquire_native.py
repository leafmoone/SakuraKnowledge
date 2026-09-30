"""Bounded official metadata GET; content-addressed raw stored once, no runtime I/O."""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

UA = 'SakuraKnowledge-P3/0.3 (https://github.com/leafmoone/SakuraKnowledge; offline metadata audit; no account)'
MAX_REQUESTS = 200
MAX_BYTES = 256*1024*1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--targets', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--aliases-only', action='store_true')
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    target_bytes = args.targets.read_bytes()
    names = [x['title'] for x in json.loads(target_bytes)['targets']]
    if not 0 < len(names) <= 500 or len(names) != len(set(names)):
        raise ValueError('invalid frozen target set')
    raw_dir = args.out.parent/'raw'
    raw_dir.mkdir(parents=True, exist_ok=True)
    previous = json.loads(args.previous.read_text()) if args.previous else None
    if args.aliases_only and previous is None:
        raise ValueError('bounded extension requires previous budget receipt')
    if previous and previous['status'] != 'SCOPED_COMPLETE':
        raise ValueError('blocked sources are never automatically resumed')
    records, total = [], 0
    prior_bytes = previous.get('cumulative_collector_bytes', previous['download_bytes_this_collector']) if previous else 0
    count = previous['requests_including_prior_docs'] if previous else 4
    documentation_byte_reserve = 4*1024*1024  # conservative reserve for the four earlier tool GETs
    last = 0.0

    def get(endpoint, params, role):
        nonlocal count, total, last
        if count >= MAX_REQUESTS:
            raise ValueError('request budget exhausted')
        delay = max(0, 1.05-(time.monotonic()-last))
        if delay:
            time.sleep(delay)  # protocol rate limit, never job polling
        count += 1
        url = endpoint+('?' + urllib.parse.urlencode(params) if params else '')
        record = {'request_ordinal':count,'endpoint':endpoint,'params':params,'role':role,
                  'fetched_at_utc':datetime.now(UTC).isoformat(),'scope':'predeclared targets only',
                  'pagination':'unknown','status':'STARTED'}
        records.append(record)
        # Durable request budget even if the collector is interrupted externally.
        with args.out.with_suffix('.journal.jsonl').open('a',encoding='utf-8') as journal:
            journal.write(json.dumps(record)+'\n')
        request = urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json'})
        last = time.monotonic()
        try:
            response = urllib.request.urlopen(request,timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        except (urllib.error.URLError, TimeoutError) as error:
            record['status'] = 'NETWORK_BLOCKED'
            record['error_type'] = type(error).__name__
            raise ValueError('source acquisition network blocked') from None
        with response:
            record['http_status'] = response.status
            record['retry_after'] = response.headers.get('Retry-After')
            data = response.read(min(MAX_BYTES-total-prior_bytes-documentation_byte_reserve+1, 8*1024*1024+1))
        total += len(data)
        record['bytes'] = len(data)
        record['sha256'] = hashlib.sha256(data).hexdigest()
        raw_path = raw_dir/(record['sha256']+'.raw')
        if not raw_path.exists():
            with raw_path.open('xb') as raw:
                raw.write(data)
        record['raw_path'] = raw_path.as_posix()
        if total+prior_bytes+documentation_byte_reserve > MAX_BYTES or len(data) > 8*1024*1024:
            record['status'] = 'BYTE_BUDGET_BLOCKED'
            raise ValueError('byte budget exceeded; body not accepted')
        if response.status != 200:
            record['status'] = 'HTTP_BLOCKED'
            # 401/403/captcha stop, 429 no retry: hence no Retry-After violation.
            raise ValueError('HTTP stop; no retry/identity rotation')
        record['status'] = 'FROZEN'
        with args.out.with_suffix('.journal.jsonl').open('a',encoding='utf-8') as journal:
            journal.write(json.dumps(record)+'\n')
        return data, record

    status = 'SCOPED_COMPLETE'
    try:
        if not args.aliases_only:
            for file in ('tag.rb','tag_alias.rb','tag_relationship.rb'):
                get('https://raw.githubusercontent.com/danbooru/danbooru/master/app/models/'+file,{},'schema_rule')
            get('https://danbooru.donmai.us/wiki_pages/help:api',{},'policy')
            get('https://testbooru.donmai.us/tags.json',{'search[name_normalize]':names[0],'limit':'1000'},'test_metadata')
            data, record = get('https://danbooru.donmai.us/tags.json',
                               {'search[name_normalize]':','.join(names),'limit':'1000',
                                'only':'id,name,category,post_count,is_deprecated,created_at,updated_at,wiki_page,antecedent_alias',
                                'includes':'wiki_page,antecedent_alias'},'tags_and_wiki')
            tags = json.loads(data)
            if not isinstance(tags,list) or len(tags) >= 1000:
                raise ValueError('unexpected or truncated tags list')
            if any(x.get('name') not in names for x in tags):
                raise ValueError('tag response outside target scope')
            record['pagination'] = 'scoped_complete; exact target predicate, fewer than limit1000'
        for name in names:
            data, record = get('https://danbooru.donmai.us/tag_aliases.json',
                               {'search[antecedent_name_matches]':name.replace('\\','\\\\').replace('*','\\*'),
                                'limit':'1000'},'outgoing_alias_scope')
            aliases = json.loads(data)
            if not isinstance(aliases,list) or len(aliases) >= 1000:
                raise ValueError('alias scope incomplete')
            if any(x.get('antecedent_name') != name for x in aliases):
                raise ValueError('alias response scope conflict')
            record['tag_scope'] = name
            record['pagination'] = 'scoped_complete; exact literal escaped name, fewer than limit1000'
    except (ValueError,json.JSONDecodeError) as error:
        status = 'SOURCE_ACQUISITION_BLOCKED' if not any(x['role']=='tags_and_wiki' and x['status']=='FROZEN'
                                                       for x in records) else 'SOURCE_ACQUISITION_PARTIAL'
        failure = str(error)
    else:
        failure = None
    result = {'status':status,'target_sha256':hashlib.sha256(target_bytes).hexdigest(),'target_count':len(names),
              'requests_including_prior_docs':count,'prior_policy_schema_tool_requests':4,
              'download_bytes_this_collector':total,'cumulative_collector_bytes':prior_bytes+total,
              'prior_receipt':str(args.previous) if args.previous else None,
              'documentation_byte_reserve':documentation_byte_reserve,'aliases_only':args.aliases_only,
              'budget':{'requests':MAX_REQUESTS,'bytes':MAX_BYTES,
                                                            'concurrency':1,'min_interval_s':1},
              'user_agent':UA,'authentication':'none; no invented user ID','records':records,'failure':failure,
              'license':'unknown; raw official metadata local-only pending source license verification',
              'transaction_snapshot':False,'time_window':'per-response fetched_at; not a database transaction snapshot',
              'retries':0,'runtime_network':False}
    with args.out.open('x',encoding='utf-8',newline='\n') as output:
        json.dump(result,output,indent=2)
    print(json.dumps({'status':status,'requests':count,'bytes':total,'failure':failure}))
    return 0 if status == 'SCOPED_COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
