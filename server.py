from fastapi import FastAPI
from typing import Any
from datetime import datetime, timezone
import uuid, time
from bot import compose

app = FastAPI(title="Vera Merchant AI")
START = time.time()
STORE = {"category": {}, "merchant": {}, "customer": {}, "trigger": {}}
VERSIONS = {}
CONVS = {}

@app.get('/v1/healthz')
def healthz():
    return {"status":"ok","uptime_seconds":round(time.time()-START,2),"contexts_loaded":{k:len(v) for k,v in STORE.items()}}

@app.get('/v1/metadata')
def metadata():
    return {"team_name":"Your Team","team_members":[],"model":"deterministic-context-composer","approach":"trigger-family rules with context-grounded composition","version":"1.0.0"}

@app.post('/v1/context')
def context(req: dict):
    scope=req.get('scope'); cid=req.get('context_id'); ver=req.get('version',0)
    if scope not in STORE or not cid: return {"accepted":False,"reason":"invalid_scope","details":"scope/context_id required"}
    key=(scope,cid); old=VERSIONS.get(key,-1)
    if ver < old: return {"accepted":False,"reason":"stale_version","current_version":old}
    STORE[scope][cid]=req.get('payload',{})
    VERSIONS[key]=ver
    return {"accepted":True,"ack_id":"ack_"+uuid.uuid4().hex[:12],"stored_at":datetime.now(timezone.utc).isoformat()}

def resolve_trigger(tid): return STORE['trigger'].get(tid,{})
def resolve_merchant(mid): return STORE['merchant'].get(mid,{})
def resolve_customer(cid): return STORE['customer'].get(cid,{}) if cid else None
def resolve_category(slug): return STORE['category'].get(slug,{})

def make_action(tid, trig):
    mid=trig.get('merchant_id') or trig.get('payload',{}).get('merchant_id')
    cid=trig.get('customer_id')
    m=resolve_merchant(mid); c=resolve_customer(cid)
    cat=resolve_category(m.get('category_slug') or trig.get('payload',{}).get('category',''))
    out=compose(cat,m,trig,c)
    conv='conv_'+uuid.uuid4().hex[:12]
    CONVS[conv]={"merchant_id":mid,"customer_id":cid,"category":cat,"merchant":m,"customer":c,"trigger":trig,"history":[]}
    return {"conversation_id":conv,"merchant_id":mid,"customer_id":cid,"send_as":out['send_as'],"trigger_id":tid,"template_name":"vera_context_v1","template_params":[],**out}

@app.post('/v1/tick')
def tick(req: dict):
    actions=[]
    for tid in req.get('available_triggers',[]):
        trig=resolve_trigger(tid)
        if not trig: continue
        # avoid duplicate sends per suppression key in active process
        if any(v.get('trigger',{}).get('suppression_key')==trig.get('suppression_key') for v in CONVS.values()): continue
        actions.append(make_action(tid,trig))
        if len(actions)>=3: break
    return {"actions":actions}

@app.post('/v1/reply')
def reply(req: dict):
    conv=CONVS.get(req.get('conversation_id'))
    if not conv: return {"action":"end","rationale":"Unknown conversation; no safe context to continue."}
    msg=(req.get('message') or '').strip()
    low=msg.lower()
    if any(x in low for x in ['stop','unsubscribe','not interested','no thanks','leave me alone']):
        return {"action":"end","rationale":"Merchant/customer explicitly declined further outreach."}
    if any(x in low for x in ['yes','sure','do it','send it','okay','ok','go ahead']):
        return {"action":"send","body":"Absolutely — I’ll use the context already shared and keep the next step concrete. Tell me if you want the draft, checklist, or customer message first.","cta":"open_ended","rationale":"Acknowledges acceptance and asks for the smallest useful next artifact."}
    if any(x in low for x in ['later','busy','tomorrow','not now']):
        return {"action":"wait","wait_seconds":1800,"rationale":"Merchant asked to defer; backing off rather than pushing."}
    return {"action":"send","body":"Got it. I’ll work from the specific details you mentioned rather than send a generic suggestion. What part would you like me to focus on first?","cta":"open_ended","rationale":"Keeps the conversation grounded and invites clarification after an ambiguous reply."}
