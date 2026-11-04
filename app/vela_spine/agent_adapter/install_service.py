from pathlib import Path
import shutil
board=Path('/home/ggbird/openvela/vendor/allwinnertech/boards/r528/r528s3-gemini-s1/src')
p=board/'etc/init.d/rcS.nsh';s=p.read_text().replace('/data/agent/spine','/data/ai_agent/sp');marker='/* CODEX_SPINE_SERVICE */'
if marker not in s:
 shutil.copy2(p,p.with_name(p.name+'.pre-spine-service'))
 anchor='#ifdef CONFIG_LUNCHER_MINI_APP'
 assert s.count(anchor)==1
 s=s.replace(anchor,'''/* CODEX_SPINE_SERVICE */
#ifdef CONFIG_EXAMPLES_VELA_SPINE
if [ -f /data/ai_agent/sp/endpoint.txt ]
then
  vela_spine --service > /data/spine-watch.log &
fi
#endif

'''+anchor)
p.write_text(s)
out=Path('/home/ggbird/codex-network-fix-20261024/service-generated-backup');out.mkdir(exist_ok=True)
for rel in ['etctmp.c','etctmp.o','etctmp/etc/init.d/rcS']:
 p=board/rel
 if p.exists():
  shutil.copy2(p,out/rel.replace('/','_'));p.unlink()
