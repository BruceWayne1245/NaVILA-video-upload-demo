"""Reclassify below-pin anchors with an honest 3-way split, parsing the raw
per-anchor (closest, berr, derr) already computed by below_pin_registrability.py.
No ICP re-run.

Distinguishes the three physically-different situations the single BAD/OK flag
conflated:
  REG   = robot approached (closest <= APPROACH_M) AND reading accurate
          (berr < BEAR_OK and derr < DIST_OK)
  DEGEN = robot approached but the reading is wrong  -> genuine ICP degeneracy
          ("vision wall": no gating can fix a wrong reading of a cloud the robot
          is standing right next to)
  FAR   = robot never got within APPROACH_M of the anchor -> NOT a registrability
          question; the robot had already drifted past/away (a downstream
          consequence of the pin, or an independent navigation failure)
"""
import re, sys

APPROACH_M = 2.0
BEAR_OK = 30.0
DIST_OK = 0.5
REPORT = "/home/teambruce/scratch_inv/an/below_pin_registrability_report.txt"

PIN = {5:11,20:8,319:4,367:11,498:5,500:10,680:6,813:6,889:9,994:6,1038:4,653:10}

ep_re = re.compile(r"^ep(\d+)\s+pin=a(\d+)")
an_re = re.compile(r"^\s*a(\d+)\s+closest=([\d.]+)m.*?berr=\s*([\d.]+)°\s+derr=([\d.]+)m")

def classify(closest, berr, derr):
    if closest > APPROACH_M:
        return "FAR"
    if berr < BEAR_OK and derr < DIST_OK:
        return "REG"
    return "DEGEN"

eps = {}
cur = None
for line in open(REPORT):
    m = ep_re.match(line)
    if m:
        cur = int(m.group(1)); eps[cur] = dict(pin=int(m.group(2)), anchors=[]); continue
    m = an_re.match(line)
    if m and cur is not None:
        idx, closest, berr, derr = int(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
        eps[cur]["anchors"].append(dict(idx=idx, closest=closest, berr=berr, derr=derr,
                                        cls=classify(closest, berr, derr)))

print("="*100)
print(f"BELOW-PIN ANCHORS — honest 3-way split (approached<={APPROACH_M}m; accurate: berr<{BEAR_OK}° & derr<{DIST_OK}m)")
print("="*100)
print(f"{'ep':>5} {'pin':>4} | {'REG':>3} {'DEGEN':>5} {'FAR':>3} | reg-chain-from-pin | pattern")

groups = {"routable_isolated":[], "final_approach":[], "offroute":[], "vision_wall":[], "mixed":[]}
for ep in sorted(eps):
    d = eps[ep]; A = {a["idx"]:a for a in d["anchors"]}; pin = d["pin"]
    n = {"REG":0,"DEGEN":0,"FAR":0}
    for a in d["anchors"]: n[a["cls"]] += 1
    # contiguous REG chain walking DOWN from pin-1 (what promotion needs; DEGEN or FAR breaks it)
    chain = []
    for i in range(pin-1, 0, -1):
        if i in A and A[i]["cls"]=="REG": chain.append(i)
        else: break
    # how far down does REG extend before the FIRST non-REG, and what breaks it
    first_break = None
    for i in range(pin-1, 0, -1):
        if i in A and A[i]["cls"]!="REG":
            first_break = (i, A[i]["cls"]); break
    reg_idxs = sorted([a["idx"] for a in d["anchors"] if a["cls"]=="REG"])
    degen_idxs = sorted([a["idx"] for a in d["anchors"] if a["cls"]=="DEGEN"])
    far_idxs = sorted([a["idx"] for a in d["anchors"] if a["cls"]=="FAR"])

    # pattern heuristic
    total = len(d["anchors"])
    reg_frac = n["REG"]/total
    if n["FAR"] >= 0.6*total:
        pat = f"OFF-ROUTE: robot never approached {far_idxs} (drifted; navigation/pin-consequence, not registrability)"
        groups["offroute"].append(ep)
    elif n["DEGEN"]==1 and reg_frac>=0.6:
        pat = f"ISOLATED DEGEN a{degen_idxs} blocks an otherwise-clean home stretch → reliability-quarantine (Inj-A) target"
        groups["routable_isolated"].append(ep)
    elif reg_frac>=0.6 and all(i<=2 for i in degen_idxs+far_idxs if i is not None) and (degen_idxs or far_idxs):
        pat = f"FINAL-APPROACH hard: clean down to ~a3, last ~2m {('degen '+str(degen_idxs)) if degen_idxs else ('not-approached '+str(far_idxs))}"
        groups["final_approach"].append(ep)
    elif n["DEGEN"] >= 0.5*total:
        pat = f"VISION WALL: {n['DEGEN']}/{total} degenerate at close range {degen_idxs}"
        groups["vision_wall"].append(ep)
    else:
        pat = f"MIXED: reg={reg_idxs} degen={degen_idxs} far={far_idxs}"
        groups["mixed"].append(ep)

    bstr = f"a{first_break[0]}({first_break[1]})" if first_break else "none"
    print(f"{ep:>5} a{pin:<3} | {n['REG']:>3} {n['DEGEN']:>5} {n['FAR']:>3} | down to a{chain[-1] if chain else pin} (break at {bstr}) | {pat}")

print("\n" + "="*100)
print("GROUPED VERDICT")
print("="*100)
labels = {
 "routable_isolated":"① Route-1 fixable — isolated degenerate anchor blocks a clean home stretch (Injection-A skip)",
 "final_approach":  "② Final-approach hard — clean most of the way, last ~2m degenerate or not-reached",
 "offroute":        "③ Off-route — robot never approached the home stretch (navigation / pin-consequence; NOT a registrability property)",
 "vision_wall":     "④ Vision wall — home stretch genuinely degenerate at point-blank range",
 "mixed":           "⑤ Mixed — scattered clean/degenerate, no clean chain",
}
for g, eps_ in groups.items():
    print(f"  {labels[g]}\n       episodes: {sorted(eps_)}  (n={len(eps_)})")

# pooled anchor-level counts among anchors the robot ACTUALLY approached
appr = [a for ep in eps for a in eps[ep]["anchors"] if a["cls"]!="FAR"]
reg = [a for a in appr if a["cls"]=="REG"]
print("\n" + "="*100)
print("POOLED (anchors the robot physically approached, i.e. registrability is even a question):")
print(f"  approached below-pin anchors: {len(appr)}")
print(f"  of those, registrable:        {len(reg)} ({len(reg)/len(appr):.0%})   degenerate: {len(appr)-len(reg)} ({(len(appr)-len(reg))/len(appr):.0%})")
allc = [a for ep in eps for a in eps[ep]["anchors"]]
far = [a for a in allc if a["cls"]=="FAR"]
print(f"  never-approached (excluded above): {len(far)}/{len(allc)} of all below-pin anchors ({len(far)/len(allc):.0%})")
print("\n  => Among clouds the robot actually stood near, the home stretch is MOSTLY registrable;")
print("     the 'vision wall' at close range is the minority. The bulk of below-pin 'badness'")
print("     is never-approached anchors — a consequence of the pin+drift, which this fix-OFF")
print("     capture CANNOT counterfactually undo (needs the fix-ON live run to settle).")
