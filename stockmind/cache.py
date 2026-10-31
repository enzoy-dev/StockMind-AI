"""Cache limitado por conteúdo; separa previsão de decisões de estoque."""

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
from threading import RLock
from time import monotonic

import pandas as pd


def fingerprint(value):
    if isinstance(value, pd.DataFrame):
        h = hashlib.sha256()
        h.update(str([(str(c), str(t)) for c, t in value.dtypes.items()]).encode())
        h.update(pd.util.hash_pandas_object(value, index=False).values.tobytes())
        return h.hexdigest()
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


class AnalysisCache:
    def __init__(self, max_entries=16, ttl=300):
        self.max_entries, self.ttl = max_entries, ttl
        self.entries = OrderedDict()
        self.lock = RLock()

    def clear(self):
        with self.lock:
            self.entries.clear()

    def obtain(self, namespace, inputs, compute):
        key = (namespace, tuple(fingerprint(v) for v in inputs))
        with self.lock:
            found = self.entries.get(key)
            if found and monotonic() - found[0] < self.ttl:
                self.entries.move_to_end(key)
                return deepcopy(found[1])
            self.entries.pop(key, None)
        result = compute()
        with self.lock:
            self.entries[key] = (monotonic(), deepcopy(result))
            self.entries.move_to_end(key)
            while len(self.entries) > self.max_entries:
                self.entries.popitem(last=False)
        return deepcopy(result)


CACHE = AnalysisCache()


def forecast_cached(vendas, horizonte=7, contexto_futuro=None):
    from stockmind.forecasting import analisar_previsoes, _recortar_contexto

    context = _recortar_contexto(vendas, contexto_futuro, horizonte)
    return CACHE.obtain(
        "forecast-v1",
        (vendas, horizonte, context),
        lambda: analisar_previsoes(vendas, horizonte, context),
    )
