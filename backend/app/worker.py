import os, uuid, time, requests
from sqlalchemy import select, delete
from redis import Redis
from rq import Worker, Queue
from app.core import initialize, SessionLocal, Project, Cue
from app.subtitles import parse_srt

MAC_URL=os.environ.get('MAC_URL','http://host.docker.internal:8765')
TOKEN=os.environ.get('MAC_TOKEN','')

def set_status(pid,state,progress=0,error=''):
    with SessionLocal() as db:
        p=db.get(Project,pid)
        if p:
            p.state=state;p.progress=progress;p.error=error[:3000];db.commit()

def mac_post(path,json,timeout=14400):
    r=requests.post(MAC_URL+path,json=json,headers={'X-Worker-Token':TOKEN},timeout=timeout)
    r.raise_for_status()
    return r.json()

def process_project(pid):
    initialize()
    try:
        set_status(pid,'transcribing',10)
        result=mac_post('/transcribe',{'project_id':pid})
        cues=parse_srt(result['srt'])
        if not cues:raise ValueError('No se detectaron subtítulos válidos')
        with SessionLocal() as db:
            db.execute(delete(Cue).where(Cue.project_id==pid))
            for index,c in enumerate(cues):
                db.add(Cue(id=str(uuid.uuid4()),project_id=pid,position=index,**c))
            db.commit()
        set_status(pid,'translating',55)
        originals=[c['original'] for c in cues]
        all_translated=[]
        for k in range(0,len(originals),6):
            part=originals[k:k+6]
            context=' '.join(originals[max(0,k-3):k])
            answer=mac_post('/translate',{'texts':part,'context':context},timeout=900)['texts']
            if len(answer)!=len(part): raise ValueError('La traducción devolvió una cantidad distinta de líneas')
            all_translated.extend(answer)
            set_status(pid,'translating',55+int(40*len(all_translated)/len(cues)))
        with SessionLocal() as db:
            records=db.scalars(select(Cue).where(Cue.project_id==pid).order_by(Cue.position)).all()
            for c,t in zip(records,all_translated):c.translated=t
            db.commit()
        set_status(pid,'ready',100)
    except Exception as exc:
        set_status(pid,'failed',0,str(exc))
        raise

if __name__=='__main__':
    initialize()
    redis=Redis.from_url(os.environ['REDIS_URL'])
    Worker([Queue('subtitles',connection=redis)],connection=redis).work()
