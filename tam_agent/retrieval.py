"""Portable sparse TF-IDF + BM25 reciprocal rank fusion; optional semantic channel."""
import math
import os
import re
from collections import Counter
from rank_bm25 import BM25Okapi
ALIASES = {"clm":"Contracts", "contract management":"Contracts", "contracts":"Contracts",
    "einv":"eInvoice", "einvoice":"eInvoice", "e-invoicing":"eInvoice", "invoicing":"eInvoice",
    "analytics":"Spend Analytics", "spend analytics":"Spend Analytics", "spend":"Spend Analytics",
    "supplier portal":"Supplier Management", "supplier management":"Supplier Management", "srm":"Supplier Management",
    "procurement":"eProcurement", "eprocurement":"eProcurement", "p2p":"eProcurement"}

ALIASES.update({
    "ap":"eInvoice", "e-invoice":"eInvoice", "eproc":"eProcurement", "e-procurement":"eProcurement",
    "contract mgmt":"Contracts", "contract":"Contracts", "rfx":"Sourcing", "esourcing":"Sourcing",
    "sourcing events":"Sourcing", "sim":"Supplier Management", "supplier mgmt":"Supplier Management",
    "reports":"Spend Analytics", "api":"Integrations", "erp integration":"Integrations",
    "connector":"Integrations", "sso":"Platform", "login":"Platform"})

def canonical(module):
    value = str(module).strip()
    return ALIASES.get(value.lower(), value)

def tokens(text):
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())

def terms(text):
    words = tokens(text)
    return words + [a+" "+b for a,b in zip(words, words[1:])]

class HybridIndex:
    def __init__(self, texts, semantic=False):
        self.texts = texts
        self.bm25 = BM25Okapi([tokens(t) for t in texts])
        counts = [Counter(terms(t)) for t in texts]
        df = Counter(term for row in counts for term in row)
        self.idf = {term: math.log((len(texts)+1)/(freq+1))+1 for term,freq in df.items()}
        self.vectors = [self.vector(row) for row in counts]
        self.encoder = None
        model = os.getenv("EMBEDDING_MODEL") if semantic else None
        if model:
            from sentence_transformers import SentenceTransformer
            self.encoder = SentenceTransformer(model)
            self.embeddings = self.encoder.encode(texts, normalize_embeddings=True)

    def vector(self, counts):
        vector = {term:(1+math.log(count))*self.idf[term] for term,count in counts.items() if term in self.idf}
        norm = math.sqrt(sum(v*v for v in vector.values())) or 1
        return {k:v/norm for k,v in vector.items()}

    def search(self, query, limit=5):
        q = self.vector(Counter(terms(query)))
        tf = [sum(value*row.get(term,0) for term,value in q.items()) for row in self.vectors]
        channels = [self.bm25.get_scores(tokens(query)), tf]
        if self.encoder:
            channels.append(self.embeddings @ self.encoder.encode([query], normalize_embeddings=True)[0])
        scores = [0.0]*len(self.texts)
        for values in channels:
            for rank,index in enumerate(sorted(range(len(values)), key=lambda i: -values[i])):
                if values[index] > 0:
                    scores[index] += 1/(60+rank+1)
        return [(i,round(scores[i],5)) for i in sorted(range(len(scores)),key=lambda i:-scores[i])[:limit] if scores[i]>0]
