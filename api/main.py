"""Internal support intelligence API; no writes to the external ticketing system."""
import os
import time
import secrets
import uuid
import math
from collections import Counter,defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from threading import Lock
from fastapi import FastAPI,Depends,HTTPException,Request,Response,Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import select,func,delete
from .db import database,User,Assignment,SessionRecord,Investigation,Review,Audit,Setting,now,ROOT
from .security import password_hash,verify_password,token_hash,LoginLimiter
from .service import DataStore,Jobs,import_outputs
from tam_agent.data import AS_OF_DATE
from tam_agent.schema import PRIORITIES,ROUTES

class Login(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    password:str=Field(min_length=1,max_length=256)
class UserInput(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    name:str=Field(min_length=1,max_length=100)
    role:Literal['support','manager','admin']
    password:str|None=Field(default=None,min_length=10,max_length=256)
    active:bool=True
    account_ids:list[str]=Field(default_factory=list,max_length=200)
class RunInput(BaseModel): ticket_id:str=Field(max_length=30)
class ReviewInput(BaseModel):
    state:Literal['approved','rejected','amended']
    note:str=Field(min_length=3,max_length=4000)
    priority:Literal['P1','P2','P3','P4']|None=None
    route_to:Literal['L1_support','L2_engineering','security','product']|None=None
class Price(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False)
    input_per_million:float=Field(ge=0,le=10000)
    output_per_million:float=Field(ge=0,le=10000)
    source:str=Field(min_length=3,max_length=500)


def create_app(database_url=None,demo=None,agent=None):
    engine,Factory=database(database_url)
    store=DataStore()
    jobs=Jobs(store,Factory,agent=agent) if agent else Jobs(store,Factory)
    limiter=LoginLimiter(); mutation_lock=Lock()
    demo=(os.getenv('APP_ENV','development')=='development' and os.getenv('ENABLE_DEMO_ACCOUNTS','false').lower()=='true') if demo is None else demo
    secure=os.getenv('APP_ENV','development')=='production'
    origins=[s.strip() for s in os.getenv('APP_ORIGINS','http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000').split(',') if s.strip()]
    dummy=password_hash(secrets.token_urlsafe(20))
    @asynccontextmanager
    async def lifespan(app):
        with Factory() as db:
            if not db.scalar(select(func.count()).select_from(User)):
                if demo:
                    for role,name in [('admin','Demo Administrator'),('manager','Support Manager'),('support','Support Engineer')]:
                        db.add(User(email=role+'@demo.local',name=name,role=role,password_hash=password_hash('Demo@1234')))
                    db.commit()
                    support=db.scalar(select(User).where(User.role=='support'))
                    # Explicit development fixture: accounts owning review tickets.
                    for aid in sorted({store.tickets[t]['resolved_account_id'] for t in store.review_ids}):
                        db.add(Assignment(user_id=support.id,account_id=aid))
                else:
                    email,password=os.getenv('BOOTSTRAP_ADMIN_EMAIL'),os.getenv('BOOTSTRAP_ADMIN_PASSWORD')
                    if email and password and len(password)>=12:
                        db.add(User(email=email.lower().strip(),name='Administrator',role='admin',password_hash=password_hash(password)))
                db.commit()
            for run in db.scalars(select(Investigation).where(Investigation.status.in_(['queued','running']))):
                run.status='failed'; run.error='Server restarted before investigation completed; retry explicitly.'; run.finished_at=now()
            db.commit()
            has_user=db.scalar(select(User.id).limit(1))
        if has_user: import_outputs(store,Factory)
        yield
        jobs.shutdown(); engine.dispose()
    app=FastAPI(title='Zycus Support Intelligence',version='1.0.0',lifespan=lifespan)
    app.state.factory=Factory; app.state.store=store; app.state.jobs=jobs
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=['GET','POST','PUT','DELETE'],allow_headers=['Content-Type','X-CSRF-Token'])
    @app.middleware('http')
    async def boundary(request,call_next):
        origin=request.headers.get('origin')
        if request.method in ('POST','PUT','PATCH','DELETE') and origin and origin not in origins:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'Origin not allowed'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        if request.url.path.startswith('/api/'): response.headers['Cache-Control']='no-store'
        return response
    def db_session():
        with Factory() as db: yield db
    def current(request:Request,db=Depends(db_session)):
        value=request.cookies.get('zycus_session','')
        record=db.get(SessionRecord,token_hash(value)) if value else None
        user=db.get(User,record.user_id) if record and record.expires_at>time.time() else None
        if not user or not user.active: raise HTTPException(401,'Please sign in')
        if request.method in ('POST','PUT','PATCH','DELETE'):
            if not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),record.csrf): raise HTTPException(403,'Invalid CSRF token')
        request.state.session=record
        return user
    def manager(user=Depends(current)):
        if user.role not in ('manager','admin'): raise HTTPException(403,'Manager permission required')
        return user
    def admin(user=Depends(current)):
        if user.role!='admin': raise HTTPException(403,'Administrator permission required')
        return user
    def assignments(db,user): return list(db.scalars(select(Assignment.account_id).where(Assignment.user_id==user.id)))
    def visible(db,user,aid): return user.role!='support' or aid in assignments(db,user)
    def ticket_for(tid,db,user):
        ticket=store.tickets.get(tid)
        if not ticket or not visible(db,user,ticket['resolved_account_id']): raise HTTPException(404,'Ticket not found')
        return ticket
    def run_for(rid,db,user):
        run=db.get(Investigation,rid)
        if not run or not visible(db,user,run.account_id): raise HTTPException(404,'Investigation not found')
        return run
    def user_view(db,user): return {'id':user.id,'email':user.email,'name':user.name,'role':user.role,'active':user.active,'account_ids':assignments(db,user)}
    def audit(db,user,action,target,detail=None): db.add(Audit(actor_id=user.id if user else None,action=action,target=str(target),detail=detail or {}))
    def run_view(run,detail=False):
        keys=['id','ticket_id','account_id','status','source','model','created_at','started_at','finished_at','error','seconds','llm_calls','input_tokens','output_tokens','estimated_cost_usd','pricing_snapshot','review_state']
        result={k:getattr(run,k) for k in keys}
        result['decision']={k:run.result.get(k) for k in ['category','priority','route_to','escalate','notify_tam','confidence','duplicate_of']} if run.result else None
        if detail: result.update(result=run.result,events=run.events)
        return result
    def scoped_runs(db,user):
        query=select(Investigation).order_by(Investigation.created_at.desc())
        if user.role=='support': query=query.where(Investigation.account_id.in_(assignments(db,user)))
        return list(db.scalars(query))

    @app.get('/api/health')
    def health(): return {'status':'ok','service':'support-intelligence'}
    @app.post('/api/auth/login')
    def login(body:Login,request:Request,response:Response,db=Depends(db_session)):
        email=body.email.strip().lower()
        limiter.check((request.client.host if request.client else 'local',email))
        user=db.scalar(select(User).where(User.email==email))
        valid=verify_password(body.password,user.password_hash if user else dummy)
        if not user or not valid or not user.active:
            audit(db,None,'auth.login_failed',email); db.commit(); raise HTTPException(401,'Invalid email or password')
        token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        db.execute(delete(SessionRecord).where(SessionRecord.expires_at<time.time()))
        db.add(SessionRecord(token_hash=token_hash(token),user_id=user.id,csrf=csrf,expires_at=time.time()+28800))
        audit(db,user,'auth.login',user.email); db.commit()
        response.set_cookie('zycus_session',token,httponly=True,secure=secure,samesite='lax',max_age=28800,path='/')
        return {'user':user_view(db,user),'csrf_token':csrf}
    @app.get('/api/auth/me')
    def me(request:Request,user=Depends(current),db=Depends(db_session)): return {'user':user_view(db,user),'csrf_token':request.state.session.csrf}
    @app.post('/api/auth/logout')
    def logout(response:Response,request:Request,user=Depends(current),db=Depends(db_session)):
        db.delete(request.state.session); audit(db,user,'auth.logout',user.email); db.commit()
        response.delete_cookie('zycus_session',path='/'); return {'ok':True}

    @app.get('/api/tickets')
    def tickets(q:str='',status:str='',module:str='',priority:str='',account_id:str='',sort:Literal['newest','oldest','subject']='newest',page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),user=Depends(current),db=Depends(db_session)):
        allowed=set(assignments(db,user)) if user.role=='support' else set(store.accounts)
        records=[t for t in store.tickets.values() if t['resolved_account_id'] in allowed]
        latest={}
        for run in scoped_runs(db,user):
            if run.ticket_id not in latest: latest[run.ticket_id]=run
        filtered=[]
        for t in records:
            run=latest.get(t['ticket_id']); decision=run.result if run and run.result else {}
            if q and q.lower() not in ' '.join(str(t.get(k,'')) for k in ['ticket_id','subject','description','company_name_raw']).lower(): continue
            if status and t['status']!=status or module and t['module']!=module or account_id and t['resolved_account_id']!=account_id: continue
            if priority and decision.get('priority')!=priority: continue
            filtered.append(dict(t,latest_run=run_view(run) if run else None))
        filtered.sort(key=lambda t:t['subject'].lower() if sort=='subject' else t['created_at'],reverse=sort=='newest')
        return {'items':filtered[(page-1)*page_size:page*page_size],'total':len(filtered),'page':page,'page_size':page_size,'modules':sorted({t['module'] for t in records if t['module']})}
    @app.get('/api/tickets/{tid}')
    def ticket_detail(tid:str,user=Depends(current),db=Depends(db_session)):
        ticket=ticket_for(tid,db,user)
        return dict(ticket,investigations=[run_view(r) for r in scoped_runs(db,user) if r.ticket_id==tid])
    @app.get('/api/accounts')
    def accounts(user=Depends(manager),db=Depends(db_session)):
        return {'items':list(store.accounts.values())}
    @app.get('/api/accounts/{aid}')
    def account_detail(aid:str,user=Depends(current),db=Depends(db_session)):
        if aid not in store.accounts or not visible(db,user,aid): raise HTTPException(404,'Account not found')
        from tam_agent.tools import TicketTools
        # Reuse existing risk calculations without constructing an LLM or retrieval index.
        from types import SimpleNamespace
        ctx=SimpleNamespace(accounts_by_id=store.accounts,usage_records=store.usage)
        tool=TicketTools(ctx,{}); tool.account_id=aid
        return {'account':store.accounts[aid],'insights':tool.account_insights(),'usage':[r for r in store.usage if r['account_id']==aid and r['month']<=AS_OF_DATE[:7]]}

    @app.post('/api/investigations',status_code=202)
    def investigate(body:RunInput,user=Depends(current),db=Depends(db_session)):
        ticket=ticket_for(body.ticket_id,db,user)
        if not agent and not os.getenv('GROQ_API_KEY'): raise HTTPException(503,'Groq is not configured on the server')
        with jobs.lock:
            active=db.scalar(select(Investigation).where(Investigation.ticket_id==body.ticket_id,Investigation.status.in_(['queued','running'])))
            if active: return run_view(active)
            count=db.scalar(select(func.count()).select_from(Investigation).where(Investigation.status.in_(['queued','running'])))
            if count>=20: raise HTTPException(429,'Investigation queue is full; retry later')
            run=Investigation(id=str(uuid.uuid4()),ticket_id=body.ticket_id,account_id=ticket['resolved_account_id'],requested_by=user.id)
            db.add(run); audit(db,user,'investigation.requested',run.id,{'ticket_id':body.ticket_id}); db.commit()
            jobs.submit(run.id)
            return run_view(run)
    @app.get('/api/investigations')
    def investigations(status:str='',page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),user=Depends(current),db=Depends(db_session)):
        rows=[r for r in scoped_runs(db,user) if not status or r.status==status]
        return {'items':[run_view(r) for r in rows[(page-1)*page_size:page*page_size]],'total':len(rows)}
    @app.get('/api/investigations/{rid}')
    def investigation(rid:str,user=Depends(current),db=Depends(db_session)):
        run=run_for(rid,db,user)
        return dict(run_view(run,True),reviews=[{'id':r.id,'reviewer_id':r.reviewer_id,'state':r.state,'note':r.note,'overrides':r.overrides,'created_at':r.created_at} for r in db.scalars(select(Review).where(Review.run_id==rid).order_by(Review.id.desc()))])
    @app.post('/api/investigations/{rid}/reviews')
    def review(rid:str,body:ReviewInput,user=Depends(manager),db=Depends(db_session)):
        run=run_for(rid,db,user)
        if run.status!='succeeded': raise HTTPException(409,'Only completed investigations can be reviewed')
        overrides={k:v for k,v in {'priority':body.priority,'route_to':body.route_to}.items() if v}
        if body.state=='amended' and not overrides: raise HTTPException(422,'An amended review needs a priority or route override')
        if body.state!='amended' and overrides: raise HTTPException(422,'Overrides require an amended review')
        db.add(Review(run_id=rid,reviewer_id=user.id,state=body.state,note=body.note,overrides=overrides))
        run.review_state=body.state; audit(db,user,'investigation.reviewed',rid,{'state':body.state,'overrides':overrides}); db.commit()
        return {'ok':True}

    @app.get('/api/kb')
    def knowledge(q:str='',status:str='',page:int=Query(1,ge=1),page_size:int=Query(24,ge=1,le=100),user=Depends(current)):
        articles=[{'id':a['id'],**a['meta']} for a in store.articles if (not q or q.lower() in (a['id']+' '+a['meta']['title']+' '+a['body']).lower()) and (not status or a['meta']['status']==status)]
        return {'items':articles[(page-1)*page_size:page*page_size],'total':len(articles)}
    @app.get('/api/kb/{kid}')
    def knowledge_detail(kid:str,user=Depends(current)):
        if kid not in store.kb: raise HTTPException(404,'Article not found')
        return store.kb[kid]

    @app.get('/api/overview')
    def overview(user=Depends(current),db=Depends(db_session)):
        records=scoped_runs(db,user); latest={}
        for r in records:
            if r.result and r.ticket_id not in latest: latest[r.ticket_id]=r
        decisions=[r.result for r in latest.values()]
        allowed=set(assignments(db,user)) if user.role=='support' else set(store.accounts)
        visible_accounts=[a for a in store.accounts if a in allowed]
        visible_tickets=[t for t in store.tickets.values() if t['resolved_account_id'] in visible_accounts]
        health=[]
        from tam_agent.tools import TicketTools
        from types import SimpleNamespace
        context=SimpleNamespace(accounts_by_id=store.accounts,usage_records=store.usage)
        for aid in visible_accounts:
            tool=TicketTools(context,{}); tool.account_id=aid; risk=tool.account_insights()
            if risk['risk_override']: health.append({'account_id':aid,'company_name':store.accounts[aid]['company_name'],**risk})
        return {'ticket_count':len(visible_tickets),'open_tickets':sum(t['status'] in ('open','pending_customer') for t in visible_tickets),'investigations':len(records),'escalations':sum(d['escalate'] for d in decisions),'pending_reviews':sum(r.review_state=='pending' and r.status=='succeeded' for r in records),'priority_distribution':dict(Counter(d['priority'] for d in decisions)),'recent_runs':[run_view(r) for r in records[:6]],'account_health':health,'as_of_date':AS_OF_DATE}
    @app.get('/api/analytics')
    def analytics(user=Depends(manager),db=Depends(db_session)):
        records=scoped_runs(db,user); completed=[r for r in records if r.status in ('succeeded','failed')]
        measured=[r.seconds for r in completed if r.seconds is not None]
        tokens=[r for r in records if r.input_tokens is not None]
        priced=[r for r in records if r.estimated_cost_usd is not None]
        trend=defaultdict(lambda:{'runs':0,'failed':0,'input_tokens':0,'output_tokens':0})
        tools=Counter()
        for r in records:
            day=r.created_at[:10]; trend[day]['runs']+=1; trend[day]['failed']+=r.status=='failed'
            trend[day]['input_tokens']+=r.input_tokens or 0; trend[day]['output_tokens']+=r.output_tokens or 0
            for e in r.events:
                if e.get('tool'): tools[e['tool']]+=1
        return {'reviews':dict(Counter(r.review_state for r in records)), 'total_runs':len(records),'statuses':dict(Counter(r.status for r in records)),'success_rate':sum(r.status=='succeeded' for r in completed)/len(completed) if completed else None,'mean_latency':sum(measured)/len(measured) if measured else None,'p95_latency':sorted(measured)[max(0,math.ceil(len(measured)*.95)-1)] if measured else None,'input_tokens':sum(r.input_tokens for r in tokens) if tokens else None,'output_tokens':sum(r.output_tokens or 0 for r in tokens) if tokens else None,'token_coverage':len(tokens),'estimated_cost_usd':sum(r.estimated_cost_usd for r in priced) if priced else None,'priced_run_count':len(priced),'models':dict(Counter(r.model or 'unknown' for r in records)),'tools':dict(tools),'trend':[{'date':day,**data} for day,data in sorted(trend.items())],'expensive_runs':[run_view(r) for r in sorted(priced,key=lambda r:r.estimated_cost_usd,reverse=True)[:10]],'slow_runs':[run_view(r) for r in sorted([r for r in records if r.seconds is not None],key=lambda r:r.seconds,reverse=True)[:10]]}

    @app.get('/api/users')
    def users(user=Depends(admin),db=Depends(db_session)): return {'items':[user_view(db,u) for u in db.scalars(select(User).order_by(User.id))]}
    def validate_user(body,db,existing=None):
        email=body.email.strip().lower()
        if '@' not in email or ' ' in email: raise HTTPException(422,'Invalid email address')
        duplicate=db.scalar(select(User).where(User.email==email))
        if duplicate and (not existing or duplicate.id!=existing.id): raise HTTPException(409,'Email already exists')
        if any(aid not in store.accounts for aid in body.account_ids): raise HTTPException(422,'Unknown account assignment')
        if existing and existing.role=='admin' and (not body.active or body.role!='admin'):
            admins=db.scalar(select(func.count()).select_from(User).where(User.role=='admin',User.active==True))
            if admins<=1: raise HTTPException(409,'Cannot disable the last active administrator')
        return email
    @app.post('/api/users',status_code=201)
    def create_user(body:UserInput,user=Depends(admin),db=Depends(db_session)):
        with mutation_lock:
            email=validate_user(body,db)
            if not body.password: raise HTTPException(422,'Password required for new users')
            target=User(email=email,name=body.name,role=body.role,active=body.active,password_hash=password_hash(body.password))
            db.add(target); db.flush()
            for aid in set(body.account_ids): db.add(Assignment(user_id=target.id,account_id=aid))
            audit(db,user,'user.created',target.id,{'role':body.role,'account_ids':body.account_ids}); db.commit()
            return user_view(db,target)
    @app.put('/api/users/{uid}')
    def update_user(uid:int,body:UserInput,user=Depends(admin),db=Depends(db_session)):
        with mutation_lock:
            target=db.get(User,uid)
            if not target: raise HTTPException(404,'User not found')
            email=validate_user(body,db,target)
            target.email=email; target.name=body.name; target.role=body.role; target.active=body.active
            if body.password: target.password_hash=password_hash(body.password)
            db.execute(delete(Assignment).where(Assignment.user_id==uid))
            for aid in set(body.account_ids): db.add(Assignment(user_id=uid,account_id=aid))
            db.execute(delete(SessionRecord).where(SessionRecord.user_id==uid))
            audit(db,user,'user.updated',uid,{'role':body.role,'active':body.active,'account_ids':body.account_ids}); db.commit()
            return user_view(db,target)
    @app.get('/api/audit')
    def audits(page:int=Query(1,ge=1),page_size:int=Query(30,ge=1,le=100),user=Depends(admin),db=Depends(db_session)):
        rows=list(db.scalars(select(Audit).order_by(Audit.id.desc()).offset((page-1)*page_size).limit(page_size)))
        return {'items':[{'id':r.id,'actor_id':r.actor_id,'action':r.action,'target':r.target,'detail':r.detail,'created_at':r.created_at} for r in rows],'total':db.scalar(select(func.count()).select_from(Audit))}
    @app.get('/api/settings')
    def settings(user=Depends(admin),db=Depends(db_session)):
        setting=db.get(Setting,'pricing')
        return {'pricing':setting.value if setting else {},'model':os.getenv('LLM_MODEL','openai/gpt-oss-20b'),'groq_configured':bool(os.getenv('GROQ_API_KEY')),'demo_accounts_enabled':demo,'secure_cookies':secure,'reference_date':AS_OF_DATE,'ticket_count':len(store.tickets),'kb_count':len(store.kb),'worker':'single-process bounded queue','database':'SQLite','pricing_note':'Costs are estimates from reported tokens and configured rates, not invoices. Failed generation usage may not be reported.'}
    @app.put('/api/settings/pricing')
    def pricing(body:dict[str,Price],user=Depends(admin),db=Depends(db_session)):
        if len(body)>30: raise HTTPException(422,'Too many model rates')
        value={model:price.model_dump() for model,price in body.items()}
        current_setting=db.get(Setting,'pricing')
        if current_setting: current_setting.value=value
        else: db.add(Setting(key='pricing',value=value))
        audit(db,user,'settings.pricing_updated','pricing',{'models':list(value)}); db.commit()
        return {'ok':True}
    dist=ROOT/'frontend'/'dist'
    if dist.exists():
        if (dist/'assets').exists(): app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')
        @app.get('/{path:path}',include_in_schema=False)
        def frontend(path:str):
            if path.startswith('api/'): raise HTTPException(404,'API route not found')
            return FileResponse(dist/'index.html')
    return app

app=create_app()
