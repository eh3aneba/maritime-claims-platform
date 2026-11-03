"""Read-only, attempt-specific audit of downloaded synthetic CI evidence."""
import collections,datetime,hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def stamp(s):return datetime.datetime.fromisoformat(s.replace('Z','+00:00'))
def minutes(start,end):return (stamp(end)-stamp(start)).total_seconds()/60

def audit(attempt, baseline_run=41386381744, candidate_run=41389632800):
 results={};metrics={};digest=None
 manifest_file=ROOT/f'manifest-attempt{attempt}.json'
 manifest=json.loads(manifest_file.read_text()) if manifest_file.exists() else None
 if manifest:digest=hashlib.sha256(manifest_file.read_bytes()).hexdigest()
 for run in (baseline_run,candidate_run):
  runmeta=json.loads((ROOT/f'{run}-attempt{attempt}-run.json').read_text())
  j=json.loads((ROOT/f'{run}-attempt{attempt}-jobs.json').read_text());jobs=j['jobs'] if isinstance(j,dict) else j
  shards=[x for x in jobs if re.fullmatch(r'Backend tests shard \d+',x['name'])]
  assert {x['name'] for x in shards}=={f'Backend tests shard {n}' for n in range(64)}
  assert all(x['conclusion']=='success' and any(s['name']=='Run backend test shard' and s['conclusion']=='success' for s in x['steps']) for x in shards)
  producer=[x for x in jobs if x['name']=='Backend collection manifest'];assert len(producer)==(run==candidate_run)
  active=shards+producer
  step_sums=collections.defaultdict(float)
  for job in active:
   for s in job['steps']:
    if s['started_at'] and s['completed_at']:step_sums[s['name']]+=minutes(s['started_at'],s['completed_at'])
  metrics[str(run)]={'attempt':attempt,'head_sha':runmeta['head_sha'],'attempt_start_to_last_job_minutes':minutes(runmeta['run_started_at'],max(x['completed_at'] for x in jobs if x['completed_at'])),'backend_runner_minutes_including_producer':sum(minutes(x['started_at'],x['completed_at']) for x in active),'shard_runner_minutes':sum(minutes(x['started_at'],x['completed_at']) for x in shards),'producer_runner_minutes':sum(minutes(x['started_at'],x['completed_at']) for x in producer),'shard_start_spread_minutes':minutes(min(x['started_at'] for x in shards),max(x['started_at'] for x in shards)),'step_runner_minutes':dict(step_sums)}
  data={};checksum_matches=0;cache_restore_jobs=0;python_versions=collections.Counter()
  with zipfile.ZipFile(ROOT/f'{run}-attempt{attempt}-logs.zip') as z:
   for name in z.namelist():
    match=re.fullmatch(r'\d+_Backend tests shard (\d+)\.txt',name)
    if not match:continue
    shard=int(match[1]);text=z.read(name).decode()
    python_versions.update(set(re.findall(r'Successfully set up CPython \(([^)]+)\)',text)))
    cache_restore_jobs+=bool(re.search(r'Cache restored from key:|Cache hit for:',text))
    if run==candidate_run and manifest:
     assert re.findall(r'MANIFEST_SHA256: ([a-f0-9]{64})',text)==[digest];checksum_matches+=1
    for line in text.splitlines():
     match=re.match(r'^\S+ (tests/.*?) (PASSED|SKIPPED|XFAIL|XPASS|FAILED|ERROR)',line)
     if match:
      node,status=match.groups();assert node not in data;data[node]={'shard':shard,'outcome':status}
  metrics[str(run)]['shard_logs_with_explicit_cache_restore']=cache_restore_jobs
  metrics[str(run)]['consumer_checksum_matches']=checksum_matches
  metrics[str(run)]['observed_python_versions']=dict(python_versions)
  results[str(run)]=data
 a,b=results.values();assert a==b
 assert manifest and set(a)==set(manifest['nodes'])
 out={'baseline_run':baseline_run,'candidate_run':candidate_run,'attempt':attempt,'nodes':len(a),'outcomes':dict(collections.Counter(x['outcome'] for x in a.values())),'exact_node_assignment_outcome_parity':True,'manifest_sha256':digest,'metrics':metrics,'limitations':['One attempt is not a repeated benchmark.','Skip reasons may be clipped; exact status prefix parsed.','Run-attempt start used, never original created_at for reruns.','Logs with explicit cache restore are observations, not controlled cache parity.','Selection and pytest share one step; collection-only 90% gate cannot be inferred from its timing.']}
 (ROOT/f'pair-attempt{attempt}-audit.json').write_text(json.dumps(out,indent=2)+'\n');return out
if __name__=='__main__':
 import sys
 print(json.dumps(audit(int(sys.argv[1])),indent=2))
