"""Deterministic policy-reference comparison; never claims independent gold accuracy."""
import json
import re
import sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tam_agent.schema import validate
from tam_agent.data import load_accounts,load_tickets,load_review_set
from tam_agent.kb import load_kb

def evaluate():
    reference=json.loads((ROOT/'evaluation/policy_reference.json').read_text())
    kb={a['id']:a for a in load_kb()}
    accounts={a['domain']:a['account_id'] for a in load_accounts().to_dict('records')}
    tickets={t['ticket_id']:t for t in load_tickets().to_dict('records')}
    counters={field:{'correct':0,'total':0} for field in reference['fields']}
    classes={p:{'correct':0,'total':0} for p in ['P1','P2','P3','P4']}
    report={'verified_label_accuracy':None,'verified_labels_available':False,'assessment':reference['method'],
            'formula':'Correct Decisions / Total Evaluated Decisions * 100',
            'overall_definition':'Micro agreement on priority, route_to, escalate, notify_tam: up to four cells per ticket; duplicate priority is excluded because its original adjudicated label is absent. Category labels, citations and duplicate checks are not included in this denominator.',
            'tickets':[],'schema_valid':0,'citations':{'total':0,'valid_and_read':0,'policy_relevant':0,'issues':[]},
            'fully_scored_ticket_count':0,'possible_decision_cells':40,'identity_correct':0,'duplicate_agreement':0,'clarification_agreement':0,'strict_ticket_agreement':0,'grounding_findings':[]}
    for ref in reference['tickets']:
        tid=ref['ticket_id'];path=ROOT/'outputs'/(tid+'.json')
        if not path.exists():
            report['grounding_findings'].append(tid+': missing output');continue
        out=json.loads(path.read_text(encoding='utf-8'));errors=validate(out)
        report['schema_valid']+=not errors
        actual={field:out.get(field) for field in reference['fields']}
        mismatch=[]
        for field in reference['fields']:
            if ref['expected'][field] is None: continue
            correct=actual[field]==ref['expected'][field]
            counters[field]['total']+=1;counters[field]['correct']+=correct
            if not correct:mismatch.append({'field':field,'expected':ref['expected'][field],'actual':actual[field]})
        if ref['expected']['priority'] is not None:
            classes[ref['expected']['priority']]['total']+=1
            classes[ref['expected']['priority']]['correct']+=actual['priority']==ref['expected']['priority']
        if all(ref['expected'][field] is not None for field in reference['fields']):
            report['fully_scored_ticket_count']+=1
            report['strict_ticket_agreement']+=not mismatch
        report['identity_correct']+=out.get('account_id')==accounts[tickets[tid]['requester_domain']]
        report['duplicate_agreement']+=out.get('duplicate_of')==ref['expected_duplicate_of']
        report['clarification_agreement']+=out.get('needs_clarification')==ref['expected_clarification']
        read=set()
        for step in out.get('reasoning_trace',[]):
            try:obs=json.loads(step['observation'])
            except (ValueError,TypeError):continue
            if step['action']=='read_kb' and isinstance(obs,dict) and obs.get('id'):read.add(obs['id'])
            if step['action']=='policies' and isinstance(obs,list):read.update(a['id'] for a in obs)
        for cid in out.get('kb_references',[]):
            report['citations']['total']+=1
            valid=cid in kb and cid in read and kb[cid]['meta']['status']!='deprecated'
            report['citations']['valid_and_read']+=valid
            relevant=valid and cid in ref['relevant_kb']
            report['citations']['policy_relevant']+=relevant
            if not valid or not relevant:report['citations']['issues'].append({'ticket_id':tid,'kb':cid,'valid_read_current':valid,'within_manual_relevance_reference':relevant})
        prose=' '.join(out.get(k,'') for k in ['customer_reply','internal_note'])
        normalized=prose.translate(str.maketrans({'\u2011':'-','\u2010':'-'}))
        for claimed in set(re.findall(r'KB-\d+',normalized)):
            if claimed not in read:report['grounding_findings'].append(tid+': unread prose citation '+claimed)
        for account in set(re.findall(r'ACC-\d+',normalized)):
            if account!=out.get('account_id'):report['grounding_findings'].append(tid+': unsupported other-account identifier '+account)
        report['tickets'].append({'ticket_id':tid,'expected':ref['expected'],'actual':actual,'mismatches':mismatch,
            'rationale':ref['rationale'],'unscored_reason':ref.get('unscored_reason'),'kb_references':out.get('kb_references',[]),'schema_errors':errors})
    def percentage(item):return round(item['correct']/item['total']*100,2) if item['total'] else None
    for item in counters.values():item['policy_agreement_percent']=percentage(item)
    for item in classes.values():item['policy_agreement_percent']=percentage(item)
    correct=sum(i['correct'] for i in counters.values());total=sum(i['total'] for i in counters.values())
    report.update(policy_metrics=counters,priority_class_metrics=classes,overall_policy_agreement={'correct':correct,'total':total,'percent':round(correct/total*100,2) if total else None})
    return report
if __name__=='__main__':
    report=evaluate()
    (ROOT/'evaluation/decision_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
