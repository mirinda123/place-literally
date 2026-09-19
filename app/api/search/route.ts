import {z} from 'zod';
import {search} from '../../../lib/vector-search';
const requestSchema=z.object({query:z.string().trim().min(1).max(200),scope:z.enum(['exact','near','theme']).default('near'),limit:z.number().int().min(1).max(20).default(12)}).strict();
export async function POST(request:Request){
 if(Number(request.headers.get('content-length')||0)>4096)return Response.json({error:'请求内容过长。'},{status:413});
 try{const text=await request.text();if(new TextEncoder().encode(text).length>4096)return Response.json({error:'请求内容过长。'},{status:413});const parsed=requestSchema.safeParse(JSON.parse(text));if(!parsed.success)return Response.json({error:'请输入 1–200 字的查询，并选择有效的匹配范围。'},{status:400});const {query,scope,limit}=parsed.data;return Response.json(await search(query,scope,limit,request.signal),{headers:{'Cache-Control':'no-store'}});}catch{return Response.json({error:'无法处理查询，请稍后再试。'},{status:400});}
}
