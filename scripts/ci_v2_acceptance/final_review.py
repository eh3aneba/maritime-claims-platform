"""Record conditional experimental evidence; never approves or merges #866."""
import json,os,subprocess
from pathlib import Path
root=Path(__file__).resolve().parent
checkpoint=Path(os.environ['RUNNER_TEMP'])/'cohort-checkpoint'
path=checkpoint/'additional-pairs-review.json'
cohort=json.loads(path.read_text()) if path.exists() else None
component_path=checkpoint/'collection-component-hosted.json'
component=json.loads(component_path.read_text()) if component_path.exists() else None
cohort_success=os.environ['COHORT_RESULT']=='success'
expiry_success=os.environ['EXPIRY_OUTCOME']=='success'
criteria={'five_observed_patch_cache_comparable_pairs':bool(cohort and cohort.get('comparable_samples',0)>=5),'median_wall_regression_at_most_5_percent':bool(cohort and cohort.get('median_wall_delta_percent',999)<=5),'median_backend_runner_cost_lower':bool(cohort and cohort.get('median_runner_delta_percent',0)<0),'collection_component_at_least_90_percent':bool(component and component.get('reduction_percent',0)>=90),'hosted_cohort_completed':cohort_success,'actual_expiry_and_recovery_completed':expiry_success}
report={'decision':'NOT ACCEPTED FOR MERGE: original #866 remains frozen pending explicit evidence/source review','coordinator_run':os.environ['GITHUB_RUN_ID'],'criteria':criteria,'conditional_experiment_criteria_met':all(criteria.values()),'cohort':cohort,'component':component,'limitations':['Pinned derivative refs are not the unchanged floating-runtime original PR.','Historical application source is not current-main regression proof.','Collection measurement is one-host serial; excludes artifact/install/test-body costs.','Small-sample observed p95 and queue/runner/image/cache variation require review.','No original PR update, readiness change, branch-protection bypass or merge is performed.'],'next_three':['Review conditional cohort and p95/runtime limitations.','Reconcile exact hosted expiry/recovery job evidence.','Propose acceptance/rejection and necessary source-bound revalidation; do not merge experiment branches.']}
(root/'combined-acceptance-review.json').write_text(json.dumps(report,indent=2)+'\n')
body='Hosted bounded acceptance coordinator completed its evidence review.\n```json\n'+json.dumps(report,indent=2)+'\n```\nCustomer Pilot remains NO-GO. No independent human or security-policy approval is implied.'
payload=root/'combined-review-body.json';payload.write_text(json.dumps({'body':body}))
subprocess.run(['gh','api','repos/eh3aneba/maritime-claims-platform/issues/553/comments','--method','POST','--input',str(payload),'--jq','.html_url'],check=True)
