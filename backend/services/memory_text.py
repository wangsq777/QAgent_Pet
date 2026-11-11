"""Pure token budgeting and Chinese/Latin lexical helpers; no remote calls."""
import math
import re


def tokens(text):
    # UTF-8 bytes are a conservative upper bound for byte/BPE based model tokenizers.
    # Prefer exact counting if the deployment installs a matching tokenizer later.
    return len(str(text).encode('utf-8'))


def fit_text(text, budget):
    if budget < 3:
        return ''
    if tokens(text) <= budget:
        return text
    parts = re.split(r'(?<=[。！？!?\n])', text)
    result = ''
    for part in parts:
        if tokens(result + part) > budget:
            break
        result += part
    if result:
        return result
    # A single long sentence must still obey the hard budget; mark the omission.
    suffix = '…'
    return text.encode('utf-8')[:max(0, budget-tokens(suffix))].decode('utf-8', errors='ignore') + suffix


def chunks(text, budget):
    part = ''
    for char in text:
        if part and tokens(part + char) > budget:
            yield part
            part = ''
        part += char
    if part:
        yield part


def terms(text):
    result = set(re.findall(r'[a-z0-9_]+', text.lower()))
    for run in re.findall(r'[\u3400-\u9fff]+', text):
        if len(run) == 1:
            result.add(run)
        result.update(run[i:i+2] for i in range(len(run)-1))
    return result


def lexical_score(query, text):
    a = terms(query)
    if not a:
        return 0.0
    best=0.0
    for part in [text,*re.split(r'[。！？!?;；\n]',text)]:
        b=terms(part)
        if b:
            best=max(best,len(a & b)/math.sqrt(len(a)*len(b)))
    return best


def relevant_excerpt(query, text, budget):
    """Select complete relevant sentences/clauses, retaining negation instead of a prefix slice."""
    if tokens(text)<=budget:
        return text
    parts=re.split(r'(?<=[。！？!?;；\n])',text)
    ranked=sorted(enumerate(parts),key=lambda pair:lexical_score(query,pair[1]),reverse=True)
    chosen=[]
    used=0
    for index,part in ranked:
        if lexical_score(query,part)<=0:
            continue
        if tokens(part)>budget:
            # Clause boundaries are preferable to dropping an unrelated prefix of a long message.
            clauses=re.split(r'(?<=[，,])',part)
            part=''.join(c for c in clauses if lexical_score(query,c)>0 and tokens(c)<=budget)
        if part and used+tokens(part)<=budget:
            chosen.append((index,part))
            used+=tokens(part)
    return ''.join(part for _,part in sorted(chosen))
