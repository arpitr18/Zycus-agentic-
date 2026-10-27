"""Dataset access and a bounded, persistent investigation job adapter."""
import json
import hashlib
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from tam_agent.data import load_accounts,load_tickets,load_usage,AS_OF_DATE,load_review_set
from tam_agent.kb import load_kb
from tam_agent.agent import Context,triage
from tam_agent.llm import LLMClient
from tam_agent.schema import validate
from .db import Investigation,Audit,Setting,User,now,ROOT
import time

class DataStore:
    def __init__(self):
        self.accounts_frame,self.tickets_frame,self.usage_frame=load_accounts(),load_tickets(),load_usage()
        self.articles=load_kb()
        self.accounts={a['account_id']:a for a in self.accounts_frame.to_dict('records')}
        self.domains={a['domain']:a['account_id'] for a in self.accounts.values()}
        self.tickets={t['ticket_id']:t for t in self.tickets_frame.to_dict('records')}
        for ticket in self.tickets.values():
            ticket['resolved_account_id']=ticket['account_id'] or self.domains.get(ticket['requester_domain'])
        self.kb={a['id']:a for a in self.articles}
        self.usage=self.usage_frame.to_dict('records')
        self.review_ids=load_review_set()
    def context(self):
        return Context(self.accounts_frame,self.tickets_frame,self.usage_frame,self.articles)

class Jobs:
    def __init__(self,store,factory,agent=triage):
        self.store,self.factory,self.agent=store,factory,agent
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='triage')
        self.lock=threading.Lock()
        self.shared=None
    def submit(self,run_id):
        self.executor.submit(self.run,run_id)
    def run(self,run_id):
        with self.factory() as db:
            run=db.get(Investigation,run_id)
            if not run or run.status!='queued': return
            run.status='running'; run.started_at=now(); db.commit()
            ticket=dict(self.store.tickets[run.ticket_id])
        started=time.perf_counter()
        ctx=None
        try:
            # Reuse the immutable indexes; isolate client, trace and counters for each job.
            import copy
            if self.shared is None: self.shared=self.store.context()
            ctx=copy.copy(self.shared); ctx.llm=LLMClient(); ctx.last_events=[]; ctx.last_trace=[]
            ctx.audit_sink=lambda step,event:self.persist_event(run_id,{'kind':'tool',**event,**step})
            ctx.llm.event_sink=lambda event:self.persist_event(run_id,{'kind':'api',**event})
            with self.factory() as db:
                run=db.get(Investigation,run_id); run.model=ctx.llm.model; db.commit()
            result=self.agent(ticket,ctx)
            errors=validate(result)
            if errors: raise ValueError('Agent returned invalid schema: '+'; '.join(errors))
            if result['ticket_id']!=ticket['ticket_id'] or result['account_id']!=ticket['resolved_account_id']:
                raise ValueError('Agent result identity does not match source ticket')
            with self.factory() as db:
                run=db.get(Investigation,run_id); run.result=result; run.status='succeeded'
                run.finished_at=now(); run.seconds=round(time.perf_counter()-started,3)
                self.metrics(db,run,ctx)
                db.add(Audit(actor_id=run.requested_by,action='investigation.completed',target=run_id,detail={'status':run.status}))
                db.commit()
        except Exception as error:
            with self.factory() as db:
                run=db.get(Investigation,run_id); run.status='failed'; run.result=None; run.finished_at=now()
                run.seconds=round(time.perf_counter()-started,3)
                message=str(error)
                if os.getenv('GROQ_API_KEY'): message=message.replace(os.environ['GROQ_API_KEY'],'[REDACTED]')
                run.error=message[:1000]
                if ctx: self.metrics(db,run,ctx)
                db.add(Audit(actor_id=run.requested_by,action='investigation.failed',target=run_id,detail={'error_type':type(error).__name__}))
                db.commit()
    def persist_event(self,run_id,event):
        with self.factory() as db:
            run=db.get(Investigation,run_id)
            run.events=[*run.events,dict(event,recorded_at=now())]; db.commit()
    def metrics(self,db,run,ctx):
        run.llm_calls=ctx.llm.calls
        usage=[e['usage'] for e in ctx.llm.events if e.get('event')=='llm' and e.get('usage')]
        if usage:
            run.input_tokens=sum(u.get('prompt_tokens',0) for u in usage)
            run.output_tokens=sum(u.get('completion_tokens',0) for u in usage)
        pricing=db.get(Setting,'pricing')
        rate=(pricing.value if pricing else {}).get(run.model)
        if rate and run.input_tokens is not None:
            run.pricing_snapshot=rate
            run.estimated_cost_usd=round((run.input_tokens*rate['input_per_million']+run.output_tokens*rate['output_per_million'])/1_000_000,8)
    def shutdown(self): self.executor.shutdown(wait=True,cancel_futures=False)

def import_outputs(store,factory):
    """Import only real CLI artifacts; never manufacture investigation metrics."""
    logs=[]
    path=ROOT/'outputs'/'run_log.jsonl'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            try: logs.append(json.loads(line))
            except ValueError: pass
    with factory() as db:
        owner=db.scalar(select(User.id).where(User.role=='admin').limit(1)) or db.scalar(select(User.id).limit(1))
        if owner is None: return
        for path in sorted((ROOT/'outputs').glob('TKT-*.json')):
            try: result=json.loads(path.read_text(encoding='utf-8'))
            except ValueError: continue
            if validate(result) or result['ticket_id'] not in store.tickets: continue
            run_id='cli-'+hashlib.sha256(path.read_bytes()).hexdigest()[:24]
            if db.get(Investigation,run_id): continue
            ticket=store.tickets[result['ticket_id']]
            if result['account_id']!=ticket['resolved_account_id']: continue
            matching=[r for r in logs if r.get('ticket_id')==result['ticket_id'] and r.get('status')=='ok']
            record=matching[-1] if matching else {}
            usages=[e['usage'] for e in record.get('llm_events',[]) if e.get('event')=='llm' and e.get('usage')]
            input_tokens=sum(u.get('prompt_tokens',0) for u in usages) if usages else None
            output_tokens=sum(u.get('completion_tokens',0) for u in usages) if usages else None
            db.add(Investigation(id=run_id,ticket_id=result['ticket_id'],account_id=result['account_id'],requested_by=owner,
                source='cli',status='succeeded',result=result,model=record.get('model'),input_tokens=input_tokens,output_tokens=output_tokens,created_at=record.get('timestamp') or now(),
                finished_at=record.get('timestamp'),seconds=record.get('seconds'),llm_calls=record.get('llm_calls'),events=record.get('events',[])))
        db.commit()
