"""String grounding only. No network, model calls, or automatic evidence insertion."""
import hashlib
import re


def _normalize(text, artifacts=False):
    """Whitelist only: whitespace, SHY, ZWSP/BOM, alphabetic line-wrap hyphens.

    No NFKC, case folding, digit/punctuation replacement, ZWJ or ZWNJ deletion.
    Every output character retains its half-open raw interval and transformations.
    """
    removed = {}
    if artifacts:
        for match in re.finditer(r"(?<=[A-Za-z])-[ \t]*\r?\n[ \t]*(?=[a-z])", text):
            for i in range(match.start(), match.end()):
                removed[i] = 'hyphen_joined'
        for i, char in enumerate(text):
            if char == '\u00ad':
                removed[i] = 'soft_hyphen_removed'
            elif char in {'\u200b', '\ufeff'}:
                removed[i] = 'zero_width_removed'
    chars, spans, methods = [], [], []
    pending = set()
    for i, char in enumerate(text):
        if i in removed:
            pending.add(removed[i])
            continue
        char_methods = set(pending)
        pending.clear()
        if char.isspace():
            if char != ' ' or (chars and chars[-1] == ' '):
                char_methods.add('whitespace_normalized')
            if chars and chars[-1] == ' ':
                spans[-1] = (spans[-1][0], i + 1)
                methods[-1].update(char_methods)
                continue
            char = ' '
        chars.append(char)
        spans.append((i, i + 1))
        methods.append(char_methods)
    return ''.join(chars), spans, methods


def _compact(text):
    normalized, spans, _ = _normalize(text)
    return normalized, spans


def locate(text, quote):
    """Return an auditable raw span, or None; never fuzzy-match/OCR-correct."""
    start = text.find(quote)
    if start >= 0:
        return start, start + len(quote), ['exact']
    for artifacts in (False, True):
        normalized, positions, methods = _normalize(text, artifacts)
        needle, _, needle_methods = _normalize(quote, artifacts)
        needle = needle.strip()
        if not needle:
            return None
        offset = normalized.find(needle)
        if offset >= 0:
            start, end = positions[offset][0], positions[offset + len(needle) - 1][1]
            # Derive methods from the actual raw match, not unrelated document text.
            used = set().union(*_normalize(text[start:end], artifacts)[2], *needle_methods)
            return start, end, sorted(used) or ['exact']
    return None


def segment_span(source, text, location):
    """Bind a declared structured segment to an unambiguous raw interval."""
    segments = source.get('segments', [])
    if not segments:
        return None
    chosen = [s for s in segments if s.get('location') == location]
    if len(chosen) != 1 or not isinstance(chosen[0].get('text'), str) or not chosen[0]['text']:
        raise ValueError('location_not_found')
    body = chosen[0]['text']
    marker = '[' + location + ']\n'
    start = text.find(marker + body)
    if start >= 0 and text.find(marker + body, start + 1) < 0:
        return start + len(marker), start + len(marker) + len(body)
    start = text.find(body)
    if start < 0 or text.find(body, start + 1) >= 0:
        raise ValueError('location_text_ambiguous')
    return start, start + len(body)


def validate(params, ctx=None):
    source = params.get("source") or {}
    text = source.get("text")
    # URL-routed calls may use the page fetched by SearchOS, with matching URL.
    if text is None and ctx is not None and source.get("url") == getattr(ctx, "url", None):
        text = getattr(ctx, "markdown", "")
    candidates = params.get("evidence")
    if not isinstance(candidates, list):
        raise ValueError("evidence must be a list")
    accepted, failures = [], []
    for evidence in candidates:
        if not isinstance(evidence, dict):
            raise ValueError("each evidence candidate must be an object")
        failure = None
        if (not params.get("run_id") or source.get("run_id") != params["run_id"]
                or source.get("status") != "opened" or not source.get("document_version")):
            failure = "source_not_opened_in_run"
        elif not source.get("source_id") or evidence.get("source_id") != source["source_id"]:
            failure = "source_mismatch"
        elif not isinstance(text, str) or not text.strip():
            failure = "source_text_unavailable"
        elif not all(isinstance(evidence.get(k), str) and evidence[k].strip()
                     for k in ("case_id", "field", "quote", "location")):
            failure = "invalid_evidence"
        if failure is None:
            quote = evidence["quote"]
            try:
                declared = segment_span(source, text, evidence['location'])
            except ValueError as exc:
                failures.append({"case_id": evidence.get("case_id"), "field": evidence.get("field"),
                                 "source_id": evidence.get("source_id"), "failure_type": str(exc),
                                 "candidate": evidence})
                continue
            bounds = evidence.get("search_span", list(declared) if declared else [0, len(text)])
            if (not isinstance(bounds, list) or len(bounds) != 2
                    or any(type(v) is not int for v in bounds)
                    or not 0 <= bounds[0] < bounds[1] <= len(text)):
                failures.append({"case_id": evidence.get("case_id"), "field": evidence.get("field"),
                                 "source_id": evidence.get("source_id"), "failure_type": "invalid_evidence",
                                 "candidate": evidence})
                continue
            if declared and not declared[0] <= bounds[0] < bounds[1] <= declared[1]:
                failures.append({"case_id": evidence.get("case_id"), "field": evidence.get("field"),
                                 "source_id": evidence.get("source_id"), "failure_type": "location_span_mismatch",
                                 "candidate": evidence})
                continue
            base, limit = bounds
            search_text = text[base:limit]
            match = locate(search_text, quote)
            if match is None:
                failure = "quote_not_found"
            else:
                start, end, methods = match
                method = '+'.join(methods)
            if failure is None:
                start += base
                end += base
        if failure:
            failures.append({"case_id": evidence.get("case_id"), "field": evidence.get("field"),
                             "source_id": evidence.get("source_id"), "failure_type": failure,
                             "candidate": evidence})
            continue
        accepted.append({**evidence, "grounding": {
            "status": "quote_found", "method": method, "normalization_methods": methods, "span": [start, end],
            "matched_text": text[start:end],
            "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "run_id": params["run_id"], "document_version": source["document_version"],
            "semantic_status": "unverified", "location_status": "unverified",
        }})
    # `facts` deliberately stays empty: matching words is not semantic evidence.
    return {"facts": [], "validated_candidates": accepted, "grounding_failures": failures,
            "semantic_status": "unverified"}


async def execute(params, ctx):
    return validate(params, ctx)
