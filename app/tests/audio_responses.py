import json
from types import SimpleNamespace


def raw_interactions(create):
    def raw(**kwargs):
        response = create(**kwargs)
        return SimpleNamespace(text=lambda: json.dumps(response, default=vars), parse=lambda: response)

    return SimpleNamespace(with_raw_response=SimpleNamespace(create=raw))
