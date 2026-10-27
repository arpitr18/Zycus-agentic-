"""Opaque server-side sessions; no browser-stored bearer tokens."""
import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict,deque
from threading import Lock
from fastapi import HTTPException

def password_hash(password):
    salt=secrets.token_bytes(16)
    key=hashlib.scrypt(password.encode(),salt=salt,n=32768,r=8,p=1,maxmem=64*1024*1024)
    return 'scrypt$'+base64.b64encode(salt).decode()+'$'+base64.b64encode(key).decode()
def verify_password(password,encoded):
    try:
        _,salt,key=encoded.split('$')
        actual=hashlib.scrypt(password.encode(),salt=base64.b64decode(salt),n=32768,r=8,p=1,maxmem=64*1024*1024)
        return hmac.compare_digest(actual,base64.b64decode(key))
    except (ValueError,TypeError): return False
def token_hash(token): return hashlib.sha256(token.encode()).hexdigest()
class LoginLimiter:
    def __init__(self): self.entries=defaultdict(deque); self.lock=Lock()
    def check(self,key):
        with self.lock:
            current=time.time()
            for old in list(self.entries):
                if not self.entries[old] or self.entries[old][-1]<current-900: del self.entries[old]
            queue=self.entries[key]
            while queue and queue[0]<current-900: queue.popleft()
            if len(queue)>=10: raise HTTPException(429,'Too many login attempts; try again in 15 minutes')
            queue.append(current)
