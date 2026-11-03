"""Bounded one-shot observer; does not survive environment replacement."""
import datetime,json,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent;REPO='eh3aneba/maritime-claims-platform'
PROOF_SHA='15f984c57d17756cf41736d45ff0cde1a12fe3b3';TARGET='998858f31d8c6ff8b8a2fe4b1184d787975efdf3'
EXPIRY=datetime.datetime.fromisoformat('2026-11-03T14:45:43+00:00');DEADLINE=EXPIRY+datetime.timedelta(minutes=30)
def now():return datetime.datetime.now(datetime.timezone.utc)
def gh(*args):return json.loads(subprocess.check_output(['gh',*args],text=True))
def api(path):return gh('api',f'repos/{REPO}/{path}')
def guard():
 p=gh('pr','view','866','--repo',REPO,'--json','state,isDraft,headRefOid')
 if p!={'state':'OPEN','isDraft':True,'headRefOid':TARGET}:raise RuntimeError('frozen_PR_changed')
 d=api('actions/runs/41389632800')
 if d['run_attempt']!=2 or d['head_sha']!=TARGET:raise RuntimeError('originating_attempt_changed_no_natural_expiry_claim')
 branch=api('git/ref/heads/ci/v2-isolated-hosted-proof')
 if branch['object']['sha']!=PROOF_SHA:raise RuntimeError('proof_branch_changed')
def post(body):
 p=ROOT/'expiry-result.json';p.write_text(json.dumps({'body':body}))
 subprocess.run(['gh','api',f'repos/{REPO}/issues/553/comments','--method','POST','--input',str(p)],check=True,stdout=subprocess.DEVNULL)

def lifecycle_recovery():
 run=41575299778
 first=api(f'actions/runs/{run}/attempts/1/jobs?per_page=100')['jobs']
 producer=next(j for j in first if j['name']=='Synthetic proof producer')
 valid=next(j for j in first if j['name']=='Synthetic proof consumer valid')
 if producer['conclusion']!='success' or [s['name'] for s in valid['steps'] if s['conclusion']=='failure']!=['Inject one recoverable synthetic failure on first attempt only']:
  raise RuntimeError('pre_expiry_seed_not_verified')
 original=api(f'actions/runs/{run}')
 if original['run_attempt']!=1 or original['head_sha']!=PROOF_SHA:
  raise RuntimeError('seed_attempt_changed_refuse_duplicate_retry')
 def wait_for(attempt):
  while now()<DEADLINE:
   guard();d=api(f'actions/runs/{run}')
   if d['head_sha']!=PROOF_SHA or d['run_attempt']>attempt:raise RuntimeError('lifecycle_identity_changed')
   if d['run_attempt']==attempt and d['status']=='completed':
    jobs=api(f'actions/runs/{run}/attempts/{attempt}/jobs?per_page=100')['jobs']
    (ROOT/f'expiry-lifecycle-attempt{attempt}-jobs.json').write_text(json.dumps(jobs,indent=2));return d,jobs
   time.sleep(30)
  raise RuntimeError('lifecycle_deadline_pending')
 subprocess.run(['gh','run','rerun',str(run),'--repo',REPO,'--failed'],check=True)
 d,jobs=wait_for(2)
 retry=next(j for j in jobs if j['name']=='Synthetic proof consumer valid')
 reused=next(j for j in jobs if j['name']=='Synthetic proof producer')
 gate=next(j for j in jobs if j['name']=='Synthetic dependency and gate proof')
 if d['conclusion']!='failure' or gate['conclusion']!='success' or [s['name'] for s in retry['steps'] if s['conclusion']=='failure']!=['Download real hosted fixture artifact']:
  raise RuntimeError('expected_post_expiry_download_rejection_not_observed')
 if (reused['started_at'],reused['completed_at'])!=(producer['started_at'],producer['completed_at']):
  raise RuntimeError('failed_only_retry_did_not_reuse_original_producer')
 subprocess.run(['gh','run','rerun',str(run),'--repo',REPO],check=True)
 d,jobs=wait_for(3)
 fresh=next(j for j in jobs if j['name']=='Synthetic proof producer')
 if d['conclusion']!='success' or fresh['started_at']==producer['started_at']:
  raise RuntimeError('post_expiry_rerun_all_not_recovered')
 a=next(x for x in api(f'actions/runs/{run}/artifacts')['artifacts'] if x['name']==f'ci-v2-proof-{run}-3')
 post(f'Actual post-expiry lifecycle proof complete: run {run}, head {PROOF_SHA}. Attempt1 verified the real candidate backend-collection-2 artifact before natural expiry and deliberately failed one fixture consumer. After recorded natural expiry, failed-only attempt2 reused original producer execution but the consumer download failed; the exact frozen aggregate shell rejected its failed dependency (proof gate SUCCESS, workflow intentionally FAILURE). Rerun-all attempt3 SUCCESS with new producer execution and fresh artifact '+str(a['id'])+'. Fresh output uses an explicitly synthetic collector fixture, not full backend coverage. No artifact deletion or original #866 attempt mutation. #866 remains unchanged Draft; benchmark adoption still unapproved; Customer Pilot NO-GO.')
 print('Actual post-expiry failed-only rejection and rerun-all recovery recorded.',flush=True)

try:
 guard()
 (ROOT/'expiry-observer-state.json').write_text(json.dumps({'state':'waiting_for_actual_recorded_expiry','expiry':EXPIRY.isoformat(),'deadline':DEADLINE.isoformat(),'proof_sha':PROOF_SHA,'warning':'Process only runs in current environment. Reconstruct from GitHub after replacement.'},indent=2))
 print('Actual bounded observer waiting for recorded natural expiry: '+EXPIRY.isoformat(),flush=True)
 last_guard=time.monotonic()
 while now()<EXPIRY:
  if time.monotonic()-last_guard>300:guard();last_guard=time.monotonic()
  time.sleep(min(30,max(0,(EXPIRY-now()).total_seconds())))
 guard()
 old={x['databaseId'] for x in gh('run','list','--repo',REPO,'--branch','ci/v2-isolated-hosted-proof','--limit','50','--json','databaseId')}
 subprocess.run(['gh','workflow','run','backend-premerge.yml','--repo',REPO,'--ref','ci/v2-isolated-hosted-proof','-f','mode=expired-artifact'],check=True)
 run=None
 while now()<DEADLINE:
  guard()
  if run is None:
   runs=gh('run','list','--repo',REPO,'--branch','ci/v2-isolated-hosted-proof','--limit','50','--json','databaseId,headSha')
   new=[x for x in runs if x['databaseId'] not in old and x['headSha']==PROOF_SHA]
   if len(new)>1:raise RuntimeError('ambiguous_new_proof_runs')
   if new:run=new[0]['databaseId'];print('Natural expiry proof dispatched: '+str(run),flush=True)
  if run:
   d=api(f'actions/runs/{run}')
   if d['status']=='completed':
    jobs=api(f'actions/runs/{run}/jobs?per_page=100')['jobs'];job=next(x for x in jobs if x['name']=='Natural-expiry artifact availability proof')
    required=['Require the recorded expiry time and unchanged originating attempt','Attempt real download after recorded natural expiry','Require unavailable artifact after natural expiry']
    for name in required:
     step=next(s for s in job['steps'] if s['name']==name)
     expected='failure' if name=='Attempt real download after recorded natural expiry' else 'success'
     if step['conclusion']!=expected and not (name=='Attempt real download after recorded natural expiry' and step['conclusion']=='success'):
      raise RuntimeError('unexpected_expiry_step_outcome_'+name)
    # The download action has continue-on-error, so its conclusion can be success;
    # the final shell explicitly tests the actual download step outcome=failure.
    if d['conclusion']!='success' or job['conclusion']!='success':raise RuntimeError('expiry_proof_not_successful_run_'+str(run))
    (ROOT/'natural-expiry-jobs.json').write_text(json.dumps(jobs,indent=2))
    post(f'Natural-expiry hosted proof SUCCESS: run {run}, proof head {PROOF_SHA}. Real download of backend-collection-2 from unchanged candidate run 41389632800 attempt2 was unavailable after its recorded 2026-11-03T14:45:43Z expiry. The workflow required the actual download outcome=failure; no artifact was deleted to manufacture expiry. This proves post-expiry unavailability, not a cause for an unrelated 404. #866 remains unchanged Draft; no benchmark acceptance. Remaining: complete comparable paired measurements and collection-component evidence; apply the same failure/recovery checks to any revised candidate only with authorization. Customer Pilot NO-GO.')
    print('Natural-expiry proof completed and recorded.',flush=True)
    lifecycle_recovery()
    break
  time.sleep(30)
 else:raise RuntimeError('bounded_expiry_deadline_ended_pending')
except Exception as error:
 post('Natural-expiry observer stopped without acceptance: '+str(error)+'. Do not infer expiry or successful validation. Inspect actual GitHub state; no automatic retry, merge or artifact deletion.')
 raise
