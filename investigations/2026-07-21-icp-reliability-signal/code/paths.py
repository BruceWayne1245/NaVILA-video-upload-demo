import glob, os, re, json

EVAL = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
TAG = "canonical_report_next_stopgate_100ep_20260720"

# 27 outbound-success episodes of batch2 (from earlier parse)
OUTBOUND_SUCCESS = [4,5,20,88,89,189,268,277,295,319,367,368,382,491,498,500,
                    537,589,647,653,669,680,783,813,889,994,1038]
RETURN_SUCCESS   = [4,189,268,295,368,647,783]
OLD50 = set([4,5,49,56,89,96,134,144,166,187,214,268,273,281,295,319,342,347,354,
             367,368,381,408,409,430,486,488,498,500,515,589,639,640,647,651,678,
             680,708,758,875,973,974,994,1000,1008,1011,1038,1040,1058,1068])

def build_paths(eps):
    d = {}
    for ep in eps:
        dirs = glob.glob(f"{EVAL}/*{TAG}*_ep{ep}")
        if not dirs:
            d[str(ep)] = None; continue
        mfiles = glob.glob(os.path.join(dirs[0], "measurements", "*.json"))
        if not mfiles:
            d[str(ep)] = None; continue
        mfiles.sort(key=lambda p: int(re.search(r"(\d+)\.json$", p).group(1)))
        m = mfiles[-1]
        step = int(re.search(r"(\d+)\.json$", m).group(1))
        t = os.path.join(dirs[0], "trajectories", f"output_{step}.jsonl")
        d[str(ep)] = (m, t) if os.path.exists(t) else None
    return d

if __name__ == "__main__":
    d = build_paths(OUTBOUND_SUCCESS)
    for ep, v in d.items():
        ok = "OK" if v else "MISSING"
        # check json loads + has needed fields
        detail = ""
        if v:
            try:
                j = json.load(open(v[0]))["round_trip"]
                cov = j.get("route_relocalization_diagnostics", {}).get("covisibility_records")
                pe = j.get("phase_events")
                detail = f"cov={len(cov) if cov else 0} phase_events={len(pe) if pe else 0}"
            except Exception as e:
                detail = f"CORRUPT: {str(e)[:50]}"
                ok = "CORRUPT"
        print(f"ep{ep:>5}: {ok}  {detail}")
