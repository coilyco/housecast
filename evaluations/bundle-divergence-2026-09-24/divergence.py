"""Bundle divergence for teable:coilyco-flight-deck/agent-compose#8166 (PREREGISTER.md).

answers <bundles dir> <out>   320 chat calls, cached per call id
jev <out>                     one Jev score per quartet, cached
score <out>                   latency, divergence, signal, agreement
selftest
"""
import json, os, random, re, sys, time, math, itertools, collections, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

PROXY = os.environ.get("DIVERGENCE_PROXY", "http://ser8:8080")
ROLES = ["scientist", "frontend-eng", "game-dev", "dev-advocate"]
ROUTES = ["evaluation/deepseek-v4-flash", "evaluation/deepseek-v4-pro"]
SAMPLES = 4
LEVELS = ["same", "slight", "moderate", "large", "opposite"]
HERE = os.path.dirname(os.path.abspath(__file__))

def prompts():
    return json.load(open(os.path.join(HERE, "prompts.json")))["prompts"]

def post(path, body, timeout):
    req = urllib.request.Request(PROXY + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def cached_batch(path, jobs, fn, width):
    done = {}
    if os.path.exists(path):
        for l in open(path):
            r = json.loads(l)
            if "error" not in r:
                done[r["id"]] = r
    todo = {k: v for k, v in jobs.items() if k not in done}
    with ThreadPoolExecutor(width) as ex, open(path, "a") as fh:
        futs = {ex.submit(fn, v): k for k, v in todo.items()}
        for f in as_completed(futs):
            k = futs[f]
            try:
                rec = {"id": k, **f.result()}
            except Exception as e:  # recorded, and a rerun retries only these
                rec = {"id": k, "error": repr(e)}
            fh.write(json.dumps(rec) + "\n"); fh.flush()
            if "error" not in rec:
                done[k] = rec
    return done

def answers(bundles, out):
    system = {r: open(os.path.join(bundles, f"{r}-frontier-compiled", "delivery", "compiled.md")).read() for r in ROLES}
    jobs = {}
    for route in ROUTES:
        for p in prompts():
            for r in ROLES:
                for s in range(SAMPLES):
                    jobs[f"{route}|{p['id']}|{r}|{s}"] = (route, system[r], p["text"])
    def call(job):
        route, sysmsg, text = job
        t = time.time()
        resp = post("/v1/chat/completions", {"model": route, "temperature": 0.7, "max_tokens": 1500,
                    "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": text}]}, 600)
        ch = resp["choices"][0]
        return {"secs": round(time.time() - t, 3), "content": ch["message"].get("content") or "",
                "finish": ch.get("finish_reason"), "usage": resp.get("usage")}
    done = cached_batch(os.path.join(out, "answers.jsonl"), jobs, call, 8)
    print(f"answers {len(done)}/{len(jobs)}")

def words(t):
    return set(re.findall(r"[a-z0-9']+", t.lower()))

def lexical(texts):
    ds = []
    for a, b in itertools.combinations(texts, 2):
        A, B = words(a), words(b)
        ds.append(1 - (len(A & B) / len(A | B) if A | B else 1))
    return sum(ds) / len(ds)

def quartets(ans):
    """(key, kind, route, prompt, members) for every between and within quartet."""
    q = []
    for route in ROUTES:
        for p in prompts():
            for s in range(SAMPLES):
                q.append((f"{route}|{p['id']}|between|{s}", "between", route, p, [f"{route}|{p['id']}|{r}|{s}" for r in ROLES]))
            for r in ROLES:
                q.append((f"{route}|{p['id']}|within|{r}", "within", route, p, [f"{route}|{p['id']}|{r}|{s}" for s in range(SAMPLES)]))
    return [x for x in q if all(m in ans for m in x[4])]

def jev_body(prompt_text, texts, key):
    order = list(range(len(texts))); random.Random(key).shuffle(order)
    state = {"prompt": prompt_text}
    for label, i in zip("ABCD", order):
        state[f"answer_{label}"] = texts[i]
    return {"model": "jev-1.13.0", "state": state, "questions": {"divergence": {"type": "score",
            "instructions": "How far apart are the stances these four answers take on the prompt?",
            "criteria": LEVELS}}}

def jev(out):
    ans = {r["id"]: r for r in map(json.loads, open(os.path.join(out, "answers.jsonl"))) if "error" not in r}
    jobs = {k: jev_body(p["text"], [ans[m]["content"] for m in mem], k) for k, _, _, p, mem in quartets(ans)}
    def call(body):
        t = time.time(); resp = post("/v1/systemone", body, 120)
        return {"secs": round(time.time() - t, 3), "answer": resp}
    done = cached_batch(os.path.join(out, "jev.jsonl"), jobs, call, 16)
    print(f"jev {len(done)}/{len(jobs)}, models {collections.Counter(r['answer'].get('model') for r in done.values())}")

def expected_level(ans):
    """Jev's own expected level. Its probabilities are rounded, so they are the fallback."""
    a = ans["answers"]["divergence"]
    if "score" in a:
        return a["score"]
    probs = a["probabilities"]
    return sum(int(k) * v for k, v in probs.items()) / sum(probs.values())

def pct(v, q):
    v = sorted(v); k = (len(v) - 1) * q; f = int(k); c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)

def spearman(a, b):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]: j += 1
            for k in range(i, j + 1): r[o[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = rank(a), rank(b); ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else float("nan")

def score(out):
    rows = [json.loads(l) for l in open(os.path.join(out, "answers.jsonl"))]
    ans = {r["id"]: r for r in rows if "error" not in r}
    jv = {r["id"]: r for r in map(json.loads, open(os.path.join(out, "jev.jsonl"))) if "error" not in r}
    print(f"answer calls ok {len(ans)}, errors {sum(1 for r in rows if 'error' in r)}")
    for route in ROUTES:
        rs = [r for k, r in ans.items() if k.startswith(route + "|")]
        s = [r["secs"] for r in rs]
        print(f"{route}: n={len(s)} p50={pct(s, .5):.2f}s p95={pct(s, .95):.2f}s max={max(s):.2f}s truncated={sum(1 for r in rs if r['finish'] == 'length')} empty={sum(1 for r in rs if not r['content'].strip())}")
    js = [r["secs"] for r in jv.values()]
    print(f"jev: n={len(js)} p50={pct(js, .5):.2f}s p95={pct(js, .95):.2f}s")
    qs = quartets(ans)
    lex = {k: lexical([ans[m]["content"] for m in mem]) for k, _, _, _, mem in qs}
    jl = {k: expected_level(jv[k]["answer"]) for k, *_ in qs if k in jv}
    for route in ROUTES:
        print(f"\n{route}  per prompt: jev between / within / signal | lexical between / within / signal")
        for p in prompts():
            def m(d, kind):
                v = [d[k] for k, kd, rt, pp, _ in qs if rt == route and pp["id"] == p["id"] and kd == kind and k in d]
                return sum(v) / len(v) if v else float("nan")
            jb, jw, lb, lw = m(jl, "between"), m(jl, "within"), m(lex, "between"), m(lex, "within")
            print(f"  {p['id']:15s} {p['kind']:7s} jev {jb:.2f} / {jw:.2f} / {jb - jw:+.2f} | lex {lb:.3f} / {lw:.3f} / {lb - lw:+.3f}")
        ks = [k for k, _, rt, *_ in qs if rt == route and k in jl]
        print(f"  agreement: spearman(jev, lexical) over {len(ks)} quartets = {spearman([jl[k] for k in ks], [lex[k] for k in ks]):.3f}")

def selftest():
    assert lexical(["a b c", "a b c", "a b c", "a b c"]) == 0
    assert lexical(["a", "b", "c", "d"]) == 1
    assert abs(lexical(["a b", "a c", "a b", "a c"]) - (4 * (1 - 1 / 3)) / 6) < 1e-9
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1 and spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1
    assert expected_level({"answers": {"divergence": {"score": 3.98, "probabilities": {"0": 0.5, "4": 0.5}}}}) == 3.98
    assert expected_level({"answers": {"divergence": {"probabilities": {"0": 0.5, "4": 0.5}}}}) == 2
    assert expected_level({"answers": {"divergence": {"score": 1.5}}}) == 1.5
    b = jev_body("p", ["w", "x", "y", "z"], "k")
    assert sorted(v for k, v in b["state"].items() if k.startswith("answer_")) == ["w", "x", "y", "z"]
    assert b == jev_body("p", ["w", "x", "y", "z"], "k")
    assert pct([1, 2, 3, 4, 5], .5) == 3
    print("selftest ok")

if __name__ == "__main__":
    c = sys.argv[1]
    {"selftest": lambda: selftest(), "answers": lambda: answers(sys.argv[2], sys.argv[3]),
     "jev": lambda: jev(sys.argv[2]), "score": lambda: score(sys.argv[2])}[c]()
