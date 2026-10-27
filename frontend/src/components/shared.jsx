import { Loader2, AlertCircle, Inbox, ArrowLeft, ArrowRight } from 'lucide-react';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card,CardContent } from './ui/card';
export function Status({value}){const tone={P1:'red',P2:'amber',P3:'blue',P4:'slate',succeeded:'green',failed:'red',running:'blue',queued:'amber',approved:'green',rejected:'red',amended:'blue',pending:'amber',active_incident:'red',deprecated:'amber',current:'green'}[value]||'slate';return <Badge tone={tone}>{value?.replaceAll('_',' ')||'Not investigated'}</Badge>}
export function Loading({label='Loading workspace?'}){return <div className="state"><Loader2 className="animate-spin" size={22}/><span>{label}</span></div>}
export function Empty({title='No records found',description='Try adjusting your filters or start a new investigation.'}){return <div className="state"><Inbox size={28}/><strong>{title}</strong><span>{description}</span></div>}
export function ErrorState({error,retry}){return <div role="alert" className="error-panel"><AlertCircle size={20}/><div><strong>Unable to complete this request</strong><p>{error?.message||String(error)}</p>{retry&&<Button variant="outline" size="sm" onClick={retry}>Try again</Button>}</div></div>}
export function PageHeader({eyebrow='SUPPORT OPERATIONS',title,description,action}){return <div className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{description&&<p>{description}</p>}</div>{action}</div>}
export function Metric({label,value,detail,icon:Icon}){return <Card><CardContent><div className="metric-label">{label}{Icon&&<Icon size={18}/>}</div><div className="metric-value">{value}</div>{detail&&<div className="muted text-xs">{detail}</div>}</CardContent></Card>}
export function Pagination({page,total,pageSize,onPage}){const pages=Math.max(1,Math.ceil(total/pageSize));return <div className="pagination"><span>{total.toLocaleString()} records ? Page {page} of {pages}</span><div className="flex gap-2"><Button aria-label="Previous page" variant="outline" size="sm" disabled={page<=1} onClick={()=>onPage(page-1)}><ArrowLeft size={14}/></Button><Button aria-label="Next page" variant="outline" size="sm" disabled={page>=pages} onClick={()=>onPage(page+1)}><ArrowRight size={14}/></Button></div></div>}
export function KeyValue({label,children}){return <div className="key-value"><span>{label}</span><strong>{children??'Not available'}</strong></div>}
export function Json({value}){return <pre className="json">{JSON.stringify(value,null,2)}</pre>}
