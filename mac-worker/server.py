import os, json, pathlib, subprocess, tempfile, re, urllib.request
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app=FastAPI(title='Subtitle Studio Mac inference gateway')
ROOT=pathlib.Path(os.environ['STUDIO_DATA']).resolve()
TOKEN=os.environ['STUDIO_TOKEN']
OLLAMA=os.environ.get('OLLAMA_URL','http://127.0.0.1:11434')
MODEL=os.environ.get('STUDIO_TRANSLATION_MODEL','qwen3:14b-q8_0')
ASR_MODEL=os.environ.get('STUDIO_ASR_MODEL','Qwen/Qwen3-ASR-1.7B')

@app.middleware('http')
async def protect(request, call_next):
    if request.headers.get('X-Worker-Token')!=TOKEN:
        return JSONResponse({'detail':'Unauthorized'},status_code=401)
    return await call_next(request)

class TranscribeRequest(BaseModel):
    project_id:str=Field(pattern=r'^[a-f0-9-]{36}$')

@app.post('/transcribe')
def transcribe(req:TranscribeRequest):
    folder=(ROOT/req.project_id).resolve()
    if folder.parent!=ROOT:raise HTTPException(400,'Invalid project')
    files=[f for f in folder.glob('source.*') if f.is_file()]
    if len(files)!=1:raise HTTPException(404,'Source missing')
    with tempfile.TemporaryDirectory(prefix='studio-asr-') as temp:
        command=['mlx-qwen3-asr',str(files[0]),'--model',ASR_MODEL,'--timestamps','-f','srt','-o',temp,'--quiet']
        try:
            subprocess.run(command,check=True,capture_output=True,text=True,timeout=14400)
        except subprocess.CalledProcessError as e:
            raise HTTPException(500,(e.stderr or e.stdout)[-2000:])
        except subprocess.TimeoutExpired:
            raise HTTPException(504,'Transcription timeout')
        outputs=list(pathlib.Path(temp).rglob('*.srt'))
        if not outputs:raise HTTPException(500,'No SRT generated; check CLI version')
        return {'srt':outputs[0].read_text(encoding='utf-8-sig')}

class TranslateRequest(BaseModel):
    texts:list[str]=Field(min_length=1,max_length=6)
    context:str=''

@app.post('/translate')
def translate(req:TranslateRequest):
    entries={str(i+1):line for i,line in enumerate(req.texts)}
    prompt=('Traduce subtítulos audiovisuales al español de España con naturalidad y precisión. '
            'No resumas, no añadas información. Devuelve únicamente JSON con las mismas claves. '
            'Conserva cada entrada como una frase independiente. Contexto anterior: '
            +req.context+'\nEntradas: '+json.dumps(entries,ensure_ascii=False))
    payload={'model':MODEL,'prompt':prompt,'system':'Eres un traductor audiovisual profesional.',
             'stream':False,'format':'json','think':False,'keep_alive':'10m',
             'options':{'temperature':0,'num_ctx':8192}}
    request=urllib.request.Request(OLLAMA+'/api/generate',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=900) as response:res=json.load(response)
        obj=json.loads(res['response'])
        if not isinstance(obj,dict) or set(obj)!=set(entries):raise ValueError('Invalid translation keys')
        values=[obj[str(i+1)] for i in range(len(entries))]
        if not all(isinstance(v,str) and v.strip() for v in values):raise ValueError('Empty translations')
        return {'texts':values}
    except Exception as e:
        raise HTTPException(502,f'Translation error: {e}')
