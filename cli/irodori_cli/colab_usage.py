"""Account-wide CU snapshot; local estimates never contact Colab."""
import math
import re
import threading
import time


def parse_usage(raw):
    fields={}
    for key,pattern in {
        'balance':r'Current balance:\s*([0-9,]+(?:\.[0-9]+)?)\s+compute units',
        'rate':r'Usage rate:\s*([0-9,]+(?:\.[0-9]+)?)/hr',
        'active_assignments':r'Active assignments:\s*(\d+)',
    }.items():
        found=re.search(pattern,raw)
        if not found:raise ValueError('ColabのCU情報の形式を確認できませんでした')
        value=float(found[1].replace(',',''))
        if not math.isfinite(value) or value<0:raise ValueError('ColabのCU情報が不正です')
        fields[key]=int(value) if key=='active_assignments' else value
    return fields


class UsageCache:
    def __init__(self,fetch=None,clock=time.monotonic,wall=time.time):
        self.lock=threading.Lock();self.fetch=fetch or self._fetch
        self.clock=clock;self.wall=wall;self.sample=None;self.measured=None
        self.attempted=None;self.fingerprint=None;self.checking=False;self.error=None

    @staticmethod
    def _fetch():
        from irodori_local import colab_command
        from .connection import capture
        return parse_usage(capture(colab_command(),['usage'],45))

    def status(self):
        with self.lock:
            result={'checking':self.checking,'error':self.error,'scope':'account'}
            if self.sample is None:return result
            elapsed=max(0,self.clock()-self.measured)
            return {**result,**self.sample,'estimate':max(0,self.sample['balance']-self.sample['rate']*elapsed/3600),
                    'age_seconds':elapsed,'stale':elapsed>=900}

    def refresh(self,force=False,fingerprint=None):
        with self.lock:
            now=self.clock()
            # Single-flight and a cooldown also apply to repeated manual clicks.
            if self.checking or self.attempted is not None and now-self.attempted<30:return False
            changed=fingerprint is not None and fingerprint!=self.fingerprint
            if not force and not changed and self.measured is not None and now-self.measured<900:return False
            self.checking=True;self.attempted=now
            if fingerprint is not None:self.fingerprint=fingerprint
        threading.Thread(target=self._update,daemon=True).start()
        return True

    def _update(self):
        try:
            sample=self.fetch()
            with self.lock:
                self.sample={**sample,'checked_at':self.wall()};self.measured=self.clock();self.error=None
        except Exception:
            # Keep the last snapshot; never interpret an error as zero CU.
            with self.lock:self.error='CUを確認できませんでした。通信・CLI認証を確認して更新してください。'
        finally:
            with self.lock:self.checking=False
