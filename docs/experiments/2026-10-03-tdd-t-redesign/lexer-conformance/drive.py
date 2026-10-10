import json, subprocess, sys, time, os
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.environ.get("WORKSHOP_REPO") or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..")))
from evals._harness.bash_classify import classify_bash_command
cases = [json.loads(l) for l in open("cases.jsonl")]
SH = {"bash": ["bash","--noprofile","--norc","runner.sh"], "zsh": ["zsh","-f","runner.sh"]}
os.makedirs("empty", exist_ok=True); os.makedirs("ck", exist_ok=True)
def enc(s): return s.replace("\n","\x01")
import signal, select, tempfile
SH = {k:[*v[:-1], os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.sh")] for k,v in SH.items()}
def solve(sh, lines, tmo=None):
    out=[]; pos=0
    while pos < len(lines):
        rest=lines[pos:]
        with tempfile.TemporaryFile() as fin:
            fin.write(("\n".join(rest)+"\n").encode()); fin.seek(0)
            for _t in range(30):
                try:
                    p=subprocess.Popen(SH[sh], stdin=fin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd="empty", start_new_session=True); break
                except BlockingIOError: time.sleep(2)
            buf=b""; got=[]
            while True:
                r,_,_=select.select([p.stdout],[],[],2.0)
                if not r:
                    os.killpg(p.pid, signal.SIGKILL); break
                d=os.read(p.stdout.fileno(),65536)
                if not d: break
                buf+=d
            p.wait()
            try: os.killpg(p.pid, signal.SIGKILL)
            except Exception: pass
            got=buf.decode().split("\n")
            got=got[:-1]   # drop partial/empty tail
        out+=got; pos+=len(got)
        if pos < len(lines):
            out.append("TIMEOUT"); pos+=1
    return out
CH=1000
chunks=[(i,[enc(s) for s,_ in cases[i:i+CH]]) for i in range(0,len(cases),CH)]
hung = {"bash":[], "zsh":[]}
def work(a):
    sh,(i,lines)=a
    fn=f"ck/{sh}_{i}.json"
    if os.path.exists(fn): return sh,i,json.load(open(fn))
    o=solve(sh,lines); json.dump(o,open(fn,"w")); return sh,i,o
res={"bash":[None]*len(cases),"zsh":[None]*len(cases)}
t=time.time()
with ThreadPoolExecutor(3) as ex:
    for sh,i,out in ex.map(work,[(sh,c) for sh in SH for c in chunks]):
        res[sh][i:i+len(out)]=out
print("oracle secs",time.time()-t, flush=True)
cls=[];slow=[]
for s,_ in cases:
    t0=time.perf_counter(); r=classify_bash_command(s); dt=time.perf_counter()-t0
    cls.append(r)
    if dt>0.5: slow.append((s,dt))
json.dump({"res":res,"cls":cls,"slow":slow},open("results.json","w"))
print("done",len(slow))
