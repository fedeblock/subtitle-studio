import os, uuid, time, pathlib, subprocess
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from app.core import initialize, SessionLocal, Project, Cue, queue, DATA
from app.subtitles import export

app=FastAPI(title='Subtitle Studio API')
MAX_BYTES=2*1024*1024*1024
ALLOWED={'.mp4','.mov','.mkv','.mp3','.wav','.m4a','.webm','.flac'}

@app.on_event('startup')
def init():
    pathlib.Path(DATA).mkdir(exist_ok=True,parents=True)
    initialize()

def as_project(p):
    return {k:getattr(p,k) for k in ['id','name','filename','state','progress','error','language','created']}

def as_cue(c):
    return {k:getattr(c,k) for k in ['id','position','start','end','original','translated']}

@app.get('/api/health')
def health(): return {'ok':True}

@app.get('/api/projects')
def projects():
    with SessionLocal() as db:
        return [as_project(x) for x in db.scalars(select(Project).order_by(Project.created.desc())).all()]

@app.post('/api/projects')
async def upload(file:UploadFile=File(...)):
    name=pathlib.Path(file.filename or '').name
    ext=pathlib.Path(name).suffix.lower()
    if ext not in ALLOWED: raise HTTPException(400,'Formato no admitido')
    pid=str(uuid.uuid4()); folder=pathlib.Path(DATA)/pid;folder.mkdir(parents=True)
    dest=folder/('source'+ext)
    n=0
    try:
        with dest.open('wb') as out:
            while chunk:=await file.read(1024*1024):
                n+=len(chunk)
                if n>MAX_BYTES: raise HTTPException(413,'Archivo demasiado grande (2 GB máximo)')
                out.write(chunk)
        with SessionLocal() as db:
            db.add(Project(id=pid,name=name,filename=dest.name,state='queued',created=time.time()))
            db.commit()
        queue().enqueue('app.worker.process_project',pid,job_timeout=14400)
        return {'id':pid}
    except Exception:
        if dest.exists():dest.unlink()
        raise

@app.get('/api/projects/{pid}')
def get_project(pid:str):
    with SessionLocal() as db:
        p=db.get(Project,pid)
        if not p: raise HTTPException(404)
        cues=db.scalars(select(Cue).where(Cue.project_id==pid).order_by(Cue.position)).all()
        return {'project':as_project(p),'cues':[as_cue(c) for c in cues]}

@app.get('/api/projects/{pid}/media')
def media(pid:str):
    with SessionLocal() as db:
        p=db.get(Project,pid)
        if not p:raise HTTPException(404)
        path=pathlib.Path(DATA)/pid/p.filename
        if not path.exists():raise HTTPException(404)
        return FileResponse(path,filename=None)

class CueUpdate(BaseModel):
    start:float=Field(ge=0)
    end:float=Field(gt=0)
    original:str=Field(max_length=10000)
    translated:str=Field(max_length=10000)

@app.put('/api/projects/{pid}/cues/{cid}')
def update_cue(pid:str,cid:str,body:CueUpdate):
    if body.end<=body.start: raise HTTPException(422,'Fin debe ser posterior al inicio')
    with SessionLocal() as db:
        c=db.get(Cue,cid)
        if not c or c.project_id!=pid:raise HTTPException(404)
        for field in ['start','end','original','translated']:setattr(c,field,getattr(body,field))
        db.commit()
        return as_cue(c)

@app.get('/api/projects/{pid}/export')
def get_export(pid:str,language:str=Query('es',pattern='^(es|original)$'),format:str=Query('srt',pattern='^(srt|vtt)$')):
    with SessionLocal() as db:
        p=db.get(Project,pid)
        if not p:raise HTTPException(404)
        cues=db.scalars(select(Cue).where(Cue.project_id==pid).order_by(Cue.position)).all()
        content=export(cues,language,format=='vtt')
        return PlainTextResponse(content,media_type='text/vtt' if format=='vtt' else 'text/plain',headers={'Content-Disposition':f'attachment; filename="{pid}.{language}.{format}"'})
