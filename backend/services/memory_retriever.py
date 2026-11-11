"""Scoped hybrid retrieval with a full-partition vector index and lexical fallback."""
import json
import math
import re

from backend.config import settings
from backend.database import get_db
from backend.services.memory_store import memory_store
from backend.services.memory_text import lexical_score, terms, tokens, relevant_excerpt

ALIASES = {'current_city':'居住 城市 地区 住在哪里 现居', 'occupation':'职业 工作 做什么 专业',
           'interest':'喜欢 兴趣 爱好', 'avoidance':'不喜欢 讨厌 避免 喜好', 'identity':'身份 学生', 'experience':'经历 发生 以前',
           'support_preference':'安慰 倾听 支持 建议', 'ongoing_topic':'未完成 进展 后来'}


def cosine(a,b):
    if len(a)!=len(b) or not a or not all(math.isfinite(float(v)) for v in (*a,*b)):
        return 0.0
    denom = math.sqrt(sum(v*v for v in a)*sum(v*v for v in b))
    return sum(x*y for x,y in zip(a,b))/denom if denom else 0.0


class VectorIndex:
    async def search(self, identity, query_vector, model, *, history=False):
        clause,params = memory_store.access(identity,'m')
        statuses = "('active','superseded')" if history else "('active')"
        scores = {}
        async with get_db() as db:
            cursor = await db.execute(f'SELECT e.memory_id,e.embedding FROM memory_embeddings e JOIN memory_entries m '
                f'ON m.memory_id=e.memory_id AND m.revision=e.revision WHERE {clause} AND m.status IN {statuses} '
                'AND e.model=? AND e.dimension=?',(*params,model,len(query_vector)))
            while True:
                rows = await cursor.fetchmany(256)
                if not rows:
                    break
                for row in rows:
                    try:
                        score = cosine(query_vector,json.loads(row['embedding']))
                    except (ValueError,TypeError):
                        continue
                    scores[row['memory_id']] = max(scores.get(row['memory_id'],0),score)
        return scores


class MemoryRetriever:
    async def search(self, identity, query, *, budget=None, query_vector=None):
        budget = budget if budget is not None else settings.MEMORY_RECALL_TOKENS
        history = bool(re.search(r'以前|之前|曾经|去年|最早|过去|原来|历史',query))
        clause,params = memory_store.access(identity)
        statuses = "('active','superseded')" if history else "('active')"
        vector_scores = {}
        if query_vector is not None:
            vector_scores = await VectorIndex().search(identity,query_vector,settings.EMBEDDING_MODEL,history=history)
        exclusions = await memory_store.exclusions(identity)
        candidates = []
        fts_ids = set()
        async with get_db() as db:
            scoped, scoped_params = memory_store.access(identity,'m')
            match = ' OR '.join('"'+term.replace('"','""')+'"' for term in sorted(terms(query))[:32])
            if match:
                try:
                    rows = await (await db.execute(f'SELECT m.memory_id FROM memory_fts f JOIN memory_entries m '
                        f'ON m.memory_id=f.memory_id WHERE memory_fts MATCH ? AND {scoped} AND m.status IN {statuses} '
                        'ORDER BY bm25(memory_fts) LIMIT ?',
                        (match,*scoped_params,settings.MEMORY_CANDIDATES))).fetchall()
                    fts_ids = {r[0] for r in rows}
                except Exception as exc:
                    if 'no such' not in str(exc):
                        raise
            cursor = await db.execute(f'SELECT * FROM memory_entries WHERE {clause} AND status IN {statuses}',params)
            while True:
                rows = await cursor.fetchmany(256)
                if not rows:
                    break
                for row in rows:
                    item = dict(row)
                    if memory_store.redacted(item['content'],'',exclusions)!=item['content']:
                        continue
                    lexical = lexical_score(query,item['content']+' '+ALIASES.get(item['predicate'],''))
                    exact = 0.0
                    if item['predicate']=='current_city' and re.search(r'住|现居|城市|地区',query):
                        exact = .75
                    if item['predicate']=='occupation' and re.search(r'职业|工作|专业|做什么',query):
                        exact = .75
                    if item['predicate']=='interest' and re.search(r'喜欢|兴趣|爱好',query):
                        exact = .65
                    semantic = vector_scores.get(item['memory_id'],0)
                    if lexical < .12 and exact==0 and semantic < settings.MEMORY_MIN_SIMILARITY:
                        continue
                    score = max(exact,lexical,semantic) + (.05 if item['memory_id'] in fts_ids else 0) + (.05 if item['evidence_level']=='manual' else 0) + (.03 if item['pinned'] else 0)
                    if item['evidence_level']=='legacy':
                        score *= .7
                    item['score'] = score
                    candidates.append(item)
                # Candidate count bounds working memory, not the age of the searched records.
                candidates = sorted(candidates,key=lambda i:i['score'],reverse=True)[:settings.MEMORY_CANDIDATES]
        selected,used,seen = [],0,set()
        for item in sorted(candidates,key=lambda i:i['score'],reverse=True):
            key = (item['predicate'],item['value'],item['status'])
            if key in seen:
                continue
            line = self.format(item)
            cost = tokens(line)
            if used+cost > budget:
                excerpt=relevant_excerpt(query,item['content'],max(0,budget-used-tokens(line)+tokens(item['content'])-32))
                if not excerpt:
                    continue
                item['excerpt']='（相关片段）'+excerpt
                cost=tokens(self.format(item))
                if used+cost>budget:
                    continue
            full = await memory_store.get(identity,item['memory_id'])
            # A concurrent forget/edit must not leak a stale search candidate.
            if full['status']=='forgotten' or full['revision']!=item['revision']:
                continue
            if item.get('excerpt'):
                full['excerpt']=item['excerpt']
            selected.append(full)
            used += cost
            seen.add(key)
        return selected

    @staticmethod
    def format(item):
        scope = '共享基础资料' if item['scope']=='user' else '当前宠物的记录'
        return (f"[{item['memory_id']} | {scope} | {item['status']} | {item['valid_from']}"
                f"{(' 至 '+item['valid_to']) if item.get('valid_to') else ''}] {item['predicate']}: {item.get('excerpt',item['content'])}")

    async def history(self, identity, query, budget, exclude_ids=()):
        """On-demand raw evidence search; no fixed age cutoff, assistant text is not user fact."""
        exclusions = await memory_store.exclusions(identity)
        best = []
        async with get_db() as db:
            cursor = await db.execute('SELECT m.message_id,m.content,m.created_at FROM messages m JOIN pet_sessions s '
                'ON s.session_id=m.session_id WHERE s.user_id=? AND s.pet_type=? '
                "AND COALESCE(s.custom_pet_id,'')=COALESCE(?,'') AND m.role='user'",
                (identity['user_id'],identity['pet_type'],identity.get('custom_pet_id')))
            while True:
                rows = await cursor.fetchmany(256)
                if not rows:
                    break
                for row in rows:
                    if row['message_id'] in exclude_ids or memory_store.redacted(row['content'],row['message_id'],exclusions)!=row['content']:
                        continue
                    score = lexical_score(query,row['content'])
                    if score>=.2:
                        best.append((score,dict(row)))
                best = sorted(best,key=lambda pair:pair[0],reverse=True)[:settings.MEMORY_CANDIDATES]
        selected,used = [],0
        for _,row in best:
            header=f"[用户原话片段；仅当前宠物；{row['created_at']}；来源 {row['message_id']}] "
            excerpt=relevant_excerpt(query,row['content'],max(0,budget-used-tokens(header)))
            if not excerpt:
                continue
            text = header+excerpt
            if used+tokens(text)<=budget:
                selected.append(text)
                used+=tokens(text)
        return '\n'.join(selected)


memory_retriever = MemoryRetriever()
