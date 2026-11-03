"""Never-merge proof: actual selector CLI timing, no backend test execution."""
import hashlib,json,os,platform,subprocess,sys,time
from pathlib import Path
TARGET='998858f31d8c6ff8b8a2fe4b1184d787975efdf3'
root=Path('frozen').resolve();temporary=Path(os.environ['RUNNER_TEMP']);cwd=root/'apps/api'
base=Path('scripts/ci_v2_baseline_selector_fa2.py').resolve();candidate=root/'scripts/backend_shard_selector.py'
# Require byte-identical baseline selector, not a reimplementation.
original=subprocess.check_output(['git','show','fa2c471463f5aecb988f89e791aae359385227e4:scripts/backend_shard_selector.py'],cwd=root)
if base.read_bytes()!=original:raise RuntimeError('baseline source mismatch')
def timed(command):
 start=time.perf_counter();result=subprocess.run(command,cwd=cwd,capture_output=True)
 if result.returncode:raise RuntimeError('selector/collection failed, not a valid timing sample')
 return result.stdout,time.perf_counter()-start
baseline={};baseline_seconds=[]
for shard in range(64):
 output,elapsed=timed([sys.executable,str(base),'--shard',str(shard),'--shards','64'])
 if not output.endswith(b'\0'):raise RuntimeError('invalid baseline nodes')
 baseline[shard]=output;baseline_seconds.append(elapsed)
 print(json.dumps({'baseline_shard':shard,'seconds':elapsed}),flush=True)
manifest=temporary/'component-manifest.json'
output,producer=timed([sys.executable,str(candidate),'--shards','64','--write-manifest',str(manifest),'--commit',TARGET])
digest=hashlib.sha256(manifest.read_bytes()).hexdigest()
if output.decode().strip()!='manifest_sha256='+digest:raise RuntimeError('producer checksum mismatch')
selection=[]
for shard in range(64):
 output,elapsed=timed([sys.executable,str(candidate),'--shard',str(shard),'--shards','64','--manifest',str(manifest),'--commit',TARGET,'--manifest-sha256',digest])
 if output!=baseline[shard]:raise RuntimeError('node assignment mismatch')
 selection.append(elapsed)
nodes=[n for value in baseline.values() for n in value.split(b'\0') if n]
if len(nodes)!=len(set(nodes)) or len(nodes)!=json.loads(manifest.read_bytes())['node_count']:raise RuntimeError('incomplete node partition')
report={'target':TARGET,'python':platform.python_version(),'image_os':os.environ.get('ImageOS'),'image_version':os.environ.get('ImageVersion'),'nodes':len(nodes),'shards':64,'baseline_selector_sha256':hashlib.sha256(original).hexdigest(),'manifest_sha256':digest,'baseline_collection_selection_seconds':sum(baseline_seconds),'candidate_collection_seconds':producer,'candidate_selection_seconds':sum(selection),'candidate_component_seconds':producer+sum(selection),'reduction_percent':100*(1-(producer+sum(selection))/sum(baseline_seconds)),'exact_node_partition_parity':True,'limitations':['Single-host serial algorithm-component observation; not full Backend wall time or runner cost.','All baseline processes precede candidate; filesystem/pip caches are not independent runner cold starts.','Does not include dependency installation or artifact transfer; full paired runs measure those separately.','No pytest test bodies executed; this is collection/selection proof only.']}
(temporary/'collection-component.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2),flush=True)
