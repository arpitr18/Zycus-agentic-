let csrf='';
export function setCsrf(value){csrf=value||''}
export async function api(path,options={}){
  const method=options.method||'GET';
  const response=await fetch('/api'+path,{credentials:'include',...options,headers:{...(options.body?{'Content-Type':'application/json'}:{}),...(['POST','PUT','PATCH','DELETE'].includes(method)?{'X-CSRF-Token':csrf}:{}),...options.headers}});
  let data;try{data=await response.json()}catch{data={detail:'The server returned an unreadable response'}}
  if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));error.status=response.status;if(response.status===401 && path!='/auth/login')window.dispatchEvent(new Event('session-expired'));throw error}
  return data;
}
export const send=(path,body,method='POST')=>api(path,{method,body:JSON.stringify(body)});
export function formatNumber(value){return value==null?'?':new Intl.NumberFormat().format(value)}
export function formatDate(value){if(!value)return 'Not recorded';const parsed=new Date(value);return Number.isNaN(parsed.valueOf())?value:parsed.toLocaleString()}
export function duration(value){return value==null?'Not recorded':value<60?`${value.toFixed(1)}s`:`${(value/60).toFixed(1)} min`}
