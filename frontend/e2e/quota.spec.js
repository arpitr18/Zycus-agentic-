// Replays a real recorded CLI quota error as an API response contract.
// No Groq call, successful AI output, database result, or review JSON is created.
import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
test('recorded quota failure displays failed state without a completed recommendation',async({page})=>{
 const records=readFileSync(new URL('../../outputs/run_log.jsonl',import.meta.url),'utf8').trim().split('\n').map(JSON.parse);
 const original=records.reverse().find(r=>r.status==='exception'&&r.errors?.some(e=>/quota|tokens per day|longer wait/i.test(e)));
 expect(original).toBeTruthy();
 await page.goto('/login');await page.getByLabel('Email address').fill('manager@demo.local');await page.getByLabel('Password',{exact:true}).fill('Demo@1234');await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.getByRole('heading',{name:'Support overview'})).toBeVisible();
 await page.route('**/api/investigations/quota-replay',route=>route.fulfill({json:{id:'quota-replay',ticket_id:original.ticket_id,source:'cli',status:'failed',created_at:original.timestamp,model:original.model,error:original.errors.join('; '),seconds:original.seconds,llm_calls:original.llm_calls,input_tokens:null,output_tokens:null,estimated_cost_usd:null,review_state:'pending',result:null,events:[],reviews:[]}}));
 await page.goto('/investigations/quota-replay');await expect(page.getByText('failed',{exact:true})).toBeVisible();await expect(page.getByRole('alert')).toBeVisible();await expect(page.getByRole('button',{name:'Retry as a new investigation'})).toBeVisible();await expect(page.getByRole('heading',{name:'AI recommendation',exact:true})).toHaveCount(0);await expect(page.getByText('succeeded',{exact:true})).toHaveCount(0);
});
