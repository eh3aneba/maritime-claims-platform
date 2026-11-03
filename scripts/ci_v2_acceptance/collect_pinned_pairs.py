"""Bounded serial full-regression samples. New runs preserve old expiry fixture."""
import datetime,hashlib,json,subprocess,time,zipfile
from pathlib import Path
import audit_pair
ROOT=Path(__file__).resolve().parent;REPO='eh3aneba/maritime-claims-platform';END=time.monotonic()+8*3600
BASE='d6545960b203fa2448c1fe2c3cb8787090298bab';CAND='ac1ef11e110316814bc8d08a87055a7e3585ece3';FROZEN='998858f31d8c6ff8b8a2fe4b1184d787975efdf3'
FILE=ROOT/'additional-pairs-state.json'
state=json.loads(FILE.read_text()) if FILE.exists() else {'pairs':[],'component_run':41576740605,'component_posted':True}
def save():FILE.write_text(json.dumps(state,indent=2))
def gh(*args):return json.loads(subprocess.check_output(['gh',*args],text=True))
def api(path):return gh('api',f'repos/{REPO}/{path}')
def post(body):
 p=ROOT/'additional-pair-report.json';p.write_text(json.dumps({'body':body}))
 subprocess.run(['gh','api',f'repos/{REPO}/issues/553/comments','--method','POST','--input',str(p)],check=True,stdout=subprocess.DEVNULL)
def guard():
 p=gh('pr','view','866','--repo',REPO,'--json','state,isDraft,headRefOid')
 if p!={'state':'OPEN','isDraft':True,'headRefOid':FROZEN}:raise RuntimeError('frozen_PR_changed')
 if api('git/ref/heads/ci/v2-baseline-py31317')['object']['sha']!=BASE:raise RuntimeError('baseline_ref_changed')
 if api('git/ref/heads/ci/v2-candidate-py31317')['object']['sha']!=CAND:raise RuntimeError('candidate_ref_changed')
 if api('actions/runs/41389632800')['run_attempt']!=2:raise RuntimeError('expiry_fixture_attempt_changed')
def wait(run,head,full=True):
 previous=None
 while time.monotonic()<END:
  guard();d=api(f'actions/runs/{run}')
  if d['head_sha']!=head or d['run_attempt']!=1:raise RuntimeError('unexpected_run_identity')
  if d['status']!=previous:print(json.dumps({'run':run,'status':d['status']}),flush=True);previous=d['status']
  if d['status']=='completed':
   if d['conclusion']!='success':raise RuntimeError(f'run_{run}_not_successful')
   j=api(f'actions/runs/{run}/jobs?per_page=100')
   if full:
    shards=[x for x in j['jobs'] if x['name'].startswith('Backend tests shard ') and x['name'].split()[-1].isdigit()]
    if {x['name'] for x in shards}!={f'Backend tests shard {n}' for n in range(64)}:raise RuntimeError('missing_shards')
    for x in shards:
     if x['conclusion']!='success' or not any(s['name']=='Run backend test shard' and s['conclusion']=='success' for s in x['steps']):raise RuntimeError('unexecuted_shard')
    if not any(x['name']=='Backend tests' and x['conclusion']=='success' for x in j['jobs']):raise RuntimeError('aggregate_not_successful')
   return d,j
  time.sleep(30)
 raise RuntimeError('eight_hour_bounded_window_ended')
def dispatch(branch,head,entry,role):
 if entry.get(role):return entry[role]
 if entry.get(role+'_dispatch_requested'):raise RuntimeError('dispatch_state_ambiguous_reconcile_GitHub_before_retry')
 old={x['databaseId'] for x in gh('run','list','--repo',REPO,'--branch',branch,'--limit','50','--json','databaseId')}
 entry[role+'_dispatch_requested']=True;save()
 subprocess.run(['gh','workflow','run','backend-premerge.yml','--repo',REPO,'--ref',branch],check=True)
 for _ in range(18):
  runs=gh('run','list','--repo',REPO,'--branch',branch,'--limit','50','--json','databaseId,headSha,event')
  fresh=[x for x in runs if x['databaseId'] not in old and x['headSha']==head and x['event']=='workflow_dispatch']
  if len(fresh)>1:raise RuntimeError('ambiguous_new_dispatch')
  if fresh:entry[role]=fresh[0]['databaseId'];save();return entry[role]
  time.sleep(10)
 raise RuntimeError('new_dispatch_not_observed')
def download(path,destination):
 with destination.open('wb') as f:r=subprocess.run(['gh','api',f'repos/{REPO}/{path}'],stdout=f,stderr=subprocess.PIPE)
 if r.returncode:raise RuntimeError('download_failed_signed_redirect_withheld')
try:
 guard();save()
 # Do not overlap the new controlled cohort with the already-running float pair.
 if not state.get('floating_pair3_audited'):
  d,j=wait(41581942714,FROZEN)
  old=ROOT.parent/'pair3';old.mkdir(exist_ok=True)
  (old/'41581942714-attempt1-run.json').write_text(json.dumps(d));(old/'41581942714-attempt1-jobs.json').write_text(json.dumps(j))
  download('actions/runs/41581942714/attempts/1/logs',old/'41581942714-attempt1-logs.zip')
  a=next(x for x in api('actions/runs/41581942714/artifacts')['artifacts'] if x['name']=='backend-collection-1' and not x['expired'])
  archive=old/'backend-collection-attempt1.zip';download(f'actions/artifacts/{a["id"]}/zip',archive)
  if 'sha256:'+hashlib.sha256(archive.read_bytes()).hexdigest()!=a['digest']:raise RuntimeError('float_pair_archive_mismatch')
  with zipfile.ZipFile(archive) as z:
   if z.namelist()!=['backend-nodes.json']:raise RuntimeError('float_pair_archive_members')
   (old/'manifest-attempt1.json').write_bytes(z.read('backend-nodes.json'))
  audit_pair.ROOT=old;floating=audit_pair.audit(1,41578063433,41581942714);audit_pair.ROOT=ROOT
  post('Floating-runtime pair3 completed and independently audited; not an exactly patch-matched cohort sample.\n```json\n'+json.dumps(floating,indent=2)+'\n```\nFurther floating-version samples stopped after the observed mixed Python patch. Subsequent conditional experiment uses disposable pinned-runtime refs; original866 and its expiry fixture remain unchanged. No acceptance.')
  state['floating_pair3_audited']=True;save()
 wait(41576740605,'ead6e0e60c475a41904886a02b1237ebb95bd4f2',False)
 component=next(x for x in api('actions/runs/41576740605/artifacts')['artifacts'] if x['name']=='collection-component' and not x['expired'])
 archive=ROOT/'collection-component-hosted.zip';download(f'actions/artifacts/{component["id"]}/zip',archive)
 if 'sha256:'+hashlib.sha256(archive.read_bytes()).hexdigest()!=component['digest']:raise RuntimeError('component_archive_digest_mismatch')
 with zipfile.ZipFile(archive) as z:
  if z.namelist()!=['collection-component.json']:raise RuntimeError('component_archive_members_mismatch')
  raw=z.read('collection-component.json');report=json.loads(raw)
 if report['target']!=FROZEN or report['python']!='3.13.17' or report['shards']!=64 or not report['exact_node_partition_parity']:raise RuntimeError('component_report_identity_mismatch')
 (ROOT/'collection-component-hosted.json').write_bytes(raw)
 if not state.get('component_posted'):
  post('Hosted collection-only measurement completed on proof head ead6e0e60c475a41904886a02b1237ebb95bd4f2, run41576740605. Archive digest independently verified.\n```json\n'+json.dumps(report,indent=2)+'\n```\nThis single-host serial component result is not full Backend wall time or runner cost. No pytest bodies executed. #866 remains frozen Draft; acceptance requires the other paired/full-regression/expiry gates and runtime-confound review.')
  state['component_posted']=True;save()
 if report['reduction_percent']<90:raise RuntimeError('collection_component_under_90_percent_stop_before_expensive_samples')
 for number in range(1,6):
  existing=[e for e in state['pairs'] if e['pair']==number]
  entry=existing[0] if existing else {'pair':number}
  if not existing:state['pairs'].append(entry);save()
  folder=ROOT/f'pair{number}';folder.mkdir(exist_ok=True)
  for role,branch,head in [('baseline','ci/v2-baseline-py31317',BASE),('candidate','ci/v2-candidate-py31317',CAND)]:
   run=dispatch(branch,head,entry,role);d,j=wait(run,head)
   (folder/f'{run}-attempt1-run.json').write_text(json.dumps(d));(folder/f'{run}-attempt1-jobs.json').write_text(json.dumps(j))
   download(f'actions/runs/{run}/attempts/1/logs',folder/f'{run}-attempt1-logs.zip')
  candidate=entry['candidate'];a=next(x for x in api(f'actions/runs/{candidate}/artifacts')['artifacts'] if x['name']=='backend-collection-1' and not x['expired'])
  archive=folder/'backend-collection-attempt1.zip';download(f'actions/artifacts/{a["id"]}/zip',archive)
  if 'sha256:'+hashlib.sha256(archive.read_bytes()).hexdigest()!=a['digest']:raise RuntimeError('archive_digest_mismatch')
  with zipfile.ZipFile(archive) as z:
   if z.namelist()!=['backend-nodes.json']:raise RuntimeError('unexpected_archive_members')
   manifest=z.read('backend-nodes.json');doc=json.loads(manifest)
   expected_tree=subprocess.check_output(['git','rev-parse',CAND+'^{tree}'],text=True).strip()
   if doc['commit']!=CAND or doc['tree']!=expected_tree:raise RuntimeError('manifest_checkout_identity_mismatch')
   (folder/'manifest-attempt1.json').write_bytes(manifest)
  (folder/'artifact-metadata.json').write_text(json.dumps(a));audit_pair.ROOT=folder;result=audit_pair.audit(1,entry['baseline'],candidate)
  if not entry.get('posted'):
   post(f'Pinned-runtime conditional pair {number} completed and independently audited.\n```json\n'+json.dumps(result,indent=2)+'\n```\nDisposable runtime-pinned derivative refs differ from originals only by Python3.13.17 pinning; no application/selector change. Evidence is conditional on pinning, not exact original866 adoption. New workflow dispatch IDs preserve original candidate41389632800 attempt2 and its expiry fixture. All64 required shard steps executed on each run; fixed source/dependencies, runtime/cache conditions still must be reviewed from logs. Not acceptance: remaining cohort/cache/Pythonpatch/p95 and isolated collection result need review. #866 unchanged Draft. Next3: audit runtime comparability; complete remaining paired samples; reconcile real-expiry lifecycle and collection-only evidence before acceptance review. Customer Pilot NO-GO.')
   entry['posted']=True;save()
 summaries=[]
 for entry in state['pairs']:
  result=json.loads((ROOT/f"pair{entry['pair']}"/'pair-attempt1-audit.json').read_text())
  b=result['metrics'][str(entry['baseline'])];c=result['metrics'][str(entry['candidate'])]
  same_patch=b.get('observed_python_versions')==c.get('observed_python_versions') and len(b.get('observed_python_versions',{}))==1
  comparable=same_patch and b['shard_logs_with_explicit_cache_restore']==64 and c['shard_logs_with_explicit_cache_restore']==64
  summaries.append({'pair':entry['pair'],'baseline_run':entry['baseline'],'candidate_run':entry['candidate'],'runtime_cache_comparable':comparable,'baseline_python':b.get('observed_python_versions'),'candidate_python':c.get('observed_python_versions'),'baseline_wall':b['attempt_start_to_last_job_minutes'],'candidate_wall':c['attempt_start_to_last_job_minutes'],'baseline_runner_minutes':b['backend_runner_minutes_including_producer'],'candidate_runner_minutes':c['backend_runner_minutes_including_producer']})
 cohort=[x for x in summaries if x['runtime_cache_comparable']]
 import statistics
 review={'samples':summaries,'comparable_samples':len(cohort),'required_comparable_samples':5,'acceptance':'NOT ACCEPTED: conditional pinned-runtime derivative evidence; original866 adoption needs explicit review and final source/check/expiry evidence','component_report':'collection-component-hosted.json','historical_reference_wall_minutes':44,'historical_reference_shard_runner_minutes':505}
 if cohort:
  review['median_wall_delta_percent']=100*(statistics.median(x['candidate_wall'] for x in cohort)/statistics.median(x['baseline_wall'] for x in cohort)-1)
  review['median_runner_delta_percent']=100*(statistics.median(x['candidate_runner_minutes'] for x in cohort)/statistics.median(x['baseline_runner_minutes'] for x in cohort)-1)
  review['observed_p95_nearest_rank_baseline_minutes']=max(x['baseline_wall'] for x in cohort)
  review['observed_p95_nearest_rank_candidate_minutes']=max(x['candidate_wall'] for x in cohort)
 (ROOT/'additional-pairs-review.json').write_text(json.dumps(review,indent=2))
 post('Bounded additional-pair review complete.\n```json\n'+json.dumps(review,indent=2)+'\n```\nThese measurements concern historical fixed application source, not updated main. No #866 merge/readiness change. Small-sample p95 is an observed maximum for <=5 samples, not a population estimate. Reconcile actual expiry lifecycle, single-host component limitations and final exact-head required checks before proposing adoption. Next3: reconcile all evidence; resolve unfulfilled acceptance criteria; seek explicit #866 acceptance before any update/merge.')
 print('Additional pairs completed, audited and review recorded; no acceptance/merge.',flush=True)
except Exception as error:
 state['stopped_reason']=str(error);save();post('Additional-pair bounded observer stopped: '+str(error)+'. Do not infer success or rerun blindly. Inspect stored run IDs in additional-pairs-state.json and actual GitHub state; preserve original expiry fixture and frozen #866 Draft.')
 raise
