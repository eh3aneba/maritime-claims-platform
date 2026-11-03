"""One bounded, never-merge scheduling-order experiment; no automatic adoption."""
import collections,datetime,hashlib,json,os,re,statistics,subprocess,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent;CONFIG=json.loads((ROOT/'config.json').read_text());REPO='eh3aneba/maritime-claims-platform';END=time.monotonic()+170*60
STATE=ROOT/'state.json';state=json.loads(STATE.read_text()) if STATE.exists() else {}
def gh(*a):return json.loads(subprocess.check_output(['gh',*a],text=True))
def api(p):return gh('api',f'repos/{REPO}/{p}')
def save():STATE.write_text(json.dumps(state,indent=2))
def stamp(v):return datetime.datetime.fromisoformat(v.replace('Z','+00:00'))
def post(body):
 p=ROOT/'report-body.json';p.write_text(json.dumps({'body':body}));subprocess.run(['gh','api',f'repos/{REPO}/issues/553/comments','--method','POST','--input',str(p),'--jq','.html_url'],check=True)
def guard():
 p=gh('pr','view','866','--repo',REPO,'--json','state,isDraft,headRefOid')
 if p!={'state':'OPEN','isDraft':True,'headRefOid':'998858f31d8c6ff8b8a2fe4b1184d787975efdf3'}:raise RuntimeError('frozen866_changed')
 for role,branch in [('control','ci/order-canary-control'),('candidate','ci/order-canary-long-first')]:
  if api('git/ref/heads/'+branch)['object']['sha']!=CONFIG[role]:raise RuntimeError('canary_ref_changed')
def dispatch(role,branch):
 if state.get(role):return state[role]
 if state.get(role+'_requested'):raise RuntimeError('ambiguous_dispatch_reconcile_GitHub_before_retry')
 old={x['databaseId'] for x in gh('run','list','--repo',REPO,'--branch',branch,'--json','databaseId')};state[role+'_requested']=True;save()
 subprocess.run(['gh','workflow','run','backend-premerge.yml','--repo',REPO,'--ref',branch],check=True)
 for _ in range(18):
  fresh=[x for x in gh('run','list','--repo',REPO,'--branch',branch,'--json','databaseId,headSha,event') if x['databaseId'] not in old and x['headSha']==CONFIG[role] and x['event']=='workflow_dispatch']
  if len(fresh)>1:raise RuntimeError('ambiguous_new_run')
  if fresh:state[role]=fresh[0]['databaseId'];save();return state[role]
  time.sleep(10)
 raise RuntimeError('dispatch_not_observed')
def wait(run,head):
 while time.monotonic()<END:
  guard();d=api(f'actions/runs/{run}')
  if d['head_sha']!=head or d['run_attempt']!=1:raise RuntimeError('run_identity_changed')
  if d['status']=='completed':
   if d['conclusion']!='success':raise RuntimeError(f'run_{run}_failed')
   j=api(f'actions/runs/{run}/jobs?per_page=100')['jobs'];return d,j
  time.sleep(30)
 raise RuntimeError('bounded_canary_deadline')
def analyze(run,d,j,path):
 shards=[x for x in j if re.fullmatch(r'Backend tests shard \d+',x['name'])]
 if len(shards)!=64 or {x['name'] for x in shards}!={f'Backend tests shard {i}' for i in range(64)}:raise RuntimeError('invalid_shard_inventory')
 if not any(x['name']=='Backend tests' and x['conclusion']=='success' for x in j):raise RuntimeError('aggregate_not_successful')
 for x in shards:
  if x['conclusion']!='success' or not any(s['name']=='Run backend test shard' and s['conclusion']=='success' for s in x['steps']):raise RuntimeError('required_step_not_executed')
 nodes={};versions=collections.Counter();images=collections.Counter();cache=0
 with zipfile.ZipFile(path) as z:
  for name in z.namelist():
   m=re.fullmatch(r'\d+_Backend tests shard (\d+)\.txt',name)
   if not m:continue
   shard=int(m[1]);text=z.read(name).decode();versions.update(set(re.findall(r'Successfully set up CPython \(([^)]+)\)',text)));images.update(set(re.findall(r'Version: (20\d{6}\.\d+\.\d+)',text)));cache+=bool(re.search(r'Cache restored from key:|Cache hit for:',text))
   for line in text.splitlines():
    m=re.match(r'^\S+ (tests/.*?) (PASSED|SKIPPED|XFAIL|XPASS|FAILED|ERROR)',line)
    if m:
     node,status=m.groups()
     if node in nodes:raise RuntimeError('duplicate_outcome_node')
     nodes[node]={'shard':shard,'outcome':status}
 if len(nodes)!=CONFIG['node_count'] or hashlib.sha256('\n'.join(sorted(nodes)).encode()).hexdigest()!=CONFIG['node_set_sha256']:raise RuntimeError('current_main_inventory_mismatch')
 classifier=next(x for x in j if x['name']=='Classify backend changes')
 starts={int(x['name'].split()[-1]):next(s['started_at'] for s in x['steps'] if s['name']=='Set up job') for x in shards}
 delays={i:(stamp(v)-stamp(classifier['completed_at'])).total_seconds() for i,v in starts.items()}
 report={'run':run,'head':d['head_sha'],'nodes':len(nodes),'outcomes':dict(collections.Counter(v['outcome'] for v in nodes.values())),'python':dict(versions),'image_versions':dict(images),'cache_restores':cache,'wall_minutes':(max(stamp(x['completed_at']) for x in j if x['completed_at'])-stamp(d['run_started_at'])).total_seconds()/60,'shard_runner_minutes':sum((stamp(x['completed_at'])-stamp(x['started_at'])).total_seconds()/60 for x in shards),'longest16_median_start_delay_seconds':statistics.median(delays[i] for i in CONFIG['longest16']),'actual_shard_start_order':sorted(starts,key=lambda i:(starts[i],i)),'shard_start_delays_seconds':delays,'all64_executed':True}
 return report,nodes
def main():
 guard()
 show=lambda ref,path:subprocess.check_output(['git','show',ref+':'+path])
 for role in ('control','candidate'):
  for path in ('scripts/backend_shard_selector.py','scripts/ci_backend_narrow_scope.py'):
   if show(CONFIG[role],path)!=show(CONFIG['main'],path):raise RuntimeError('selection_or_classifier_changed')
  if subprocess.check_output(['git','rev-parse',CONFIG[role]+':apps'])!=subprocess.check_output(['git','rev-parse',CONFIG['main']+':apps']):raise RuntimeError('application_source_changed')
 a=show(CONFIG['control'],'.github/workflows/backend-premerge.yml');b=show(CONFIG['candidate'],'.github/workflows/backend-premerge.yml')
 normalize=lambda v:re.sub(rb'        shard: \[[^\]]+\]',b'        shard: [PERMUTATION]',v)
 if normalize(a)!=normalize(b):raise RuntimeError('more_than_matrix_order_changed')
 results={};membership={}
 for role,branch in [('control','ci/order-canary-control'),('candidate','ci/order-canary-long-first')]:
  run=dispatch(role,branch);print(json.dumps({'role':role,'run':run}),flush=True);d,j=wait(run,CONFIG[role]);(ROOT/f'{role}-jobs.json').write_text(json.dumps(j));(ROOT/f'{role}-run.json').write_text(json.dumps(d));path=ROOT/f'{role}-logs.zip'
  with path.open('wb') as f:p=subprocess.run(['gh','api',f'repos/{REPO}/actions/runs/{run}/logs'],stdout=f,stderr=subprocess.PIPE)
  if p.returncode:raise RuntimeError('logs_unavailable_signed_redirect_omitted')
  results[role],membership[role]=analyze(run,d,j,path);(ROOT/f'{role}-audit.json').write_text(json.dumps(results[role],indent=2))
 if membership['control']!=membership['candidate']:raise RuntimeError('node_shard_outcome_parity_failed')
 a,b=results['control'],results['candidate'];report={'decision':'NOT ADOPTED: one canary requires review, no merge','source_main':CONFIG['main'],'exact_node_shard_outcome_parity':True,'results':results,'wall_delta_percent':100*(b['wall_minutes']/a['wall_minutes']-1),'runner_delta_percent':100*(b['shard_runner_minutes']/a['shard_runner_minutes']-1),'longest16_start_delay_delta_seconds':b['longest16_median_start_delay_seconds']-a['longest16_median_start_delay_seconds'],'limitations':['One serial control/candidate pair, not a causal or p95 conclusion.','The canary does not execute every separate required workflow; future adoption needs applicable exact-head required gates.','Python pinned equally as experiment control; main is unchanged.','Runner images/cache/queue/CPU and coordinator occupancy may confound results.','Ranking came from an earlier same-tree PR run; GitHub need not honor creation order.'],'next_three':['Review actual long-job starts and source/runtime/cache parity.','Stop if ordering has no useful effect; otherwise propose bounded confirmation.','Do not merge experiment refs or change866 without review.']}
 (ROOT/'result.json').write_text(json.dumps(report,indent=2)+'\n');post('Single current-main scheduling-order canary completed.\n```json\n'+json.dumps(report,indent=2)+'\n```\nNo adoption,866revision,source-policy change or merge. Customer Pilot NO-GO.')
if __name__=='__main__':
 try:main()
 except Exception as error:
  state['stopped_reason']=str(error);save();post('Scheduling-order canary stopped: '+str(error)+'. No result/acceptance inferred; inspect hosted checkpoint/run IDs before resuming. No duplicate retry or test waiver.');raise
