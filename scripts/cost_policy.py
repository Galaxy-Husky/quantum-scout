"""Model call classification and accounting; unknown usage stays unknown."""
import math


def cost_category(contract):
    return {'ContextGem': 'extraction', 'Extraction': 'extraction', 'NativeExtraction': 'extraction',
            'AttributionResult': 'attribution', 'Judgments': 'semantic',
            'CounterQuoteSpanSelections': 'semantic',
            'CounterQuoteFidelity': 'semantic',
            'Query': 'orchestrator'}.get(contract, 'other')


def model_costs(events):
    """Join by call ID; attempts without a response/usage remain explicitly unknown."""
    started = {e['call_id']: e for e in events if e['kind'] == 'model_call_started'}
    responses = {e['call_id']: e for e in events if e['kind'] == 'model_response' and e.get('call_id')}
    categories = {k: {'calls': 0, 'responses': 0, 'usage_known_calls': 0,
                     'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0,
                     'known_token_calls': {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0},
                     'priced_calls': 0, 'known_usd': 0.0}
                  for k in ('extraction', 'attribution', 'semantic', 'orchestrator', 'other')}
    for cid in sorted(started.keys() | responses.keys()):
        start, response = started.get(cid, {}), responses.get(cid, {})
        category = start.get('cost_category', cost_category(start.get('output_contract')))
        row = categories.get(category, categories['other'])
        row['calls'] += 1
        row['responses'] += bool(response)
        usage = response.get('usage') or {}
        complete_usage = True
        for key in ('input_tokens', 'output_tokens', 'total_tokens'):
            value = usage.get(key)
            if key == 'total_tokens' and value is None and all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('input_tokens', 'output_tokens')):
                value = usage['input_tokens'] + usage['output_tokens']
            if type(value) is int and value >= 0:
                row[key] += value
                row['known_token_calls'][key] += 1
            else:
                complete_usage = False
        row['usage_known_calls'] += complete_usage
        usd = response.get('cost_usd')
        if type(usd) in (int, float) and math.isfinite(usd) and usd >= 0:
            row['priced_calls'] += 1
            row['known_usd'] += usd
    for row in categories.values():
        row['usd'] = row['known_usd'] if row['calls'] == row['priced_calls'] else None
        row['unpriced_calls'] = row['calls'] - row['priced_calls']
        row['unknown_usage_calls'] = row['calls'] - row['usage_known_calls']
    return categories


