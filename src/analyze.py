import json, re, numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = pd.DataFrame(json.load(open("data/shortages_raw.json")))
d["posted"] = pd.to_datetime(d.initial_posting_date, format="%m/%d/%Y")
d["updated"] = pd.to_datetime(d.update_date, format="%m/%d/%Y")
d["availability"] = d.availability.replace({"Unvailable": "Unavailable"})
d["company"] = d.company_name.fillna("").str.upper().str.replace(r"[^\w ]", " ", regex=True).str.replace(r"\b(INC|LLC|LTD|LIMITED|CORP|CORPORATION|CO|COMPANY|USA|US|PHARMACEUTICALS?|PHARMA|LABS?|LABORATORIES)\b", "", regex=True).str.split().str.join(" ")
print(len(d), "records;", d.generic_name.nunique(), "generic names;", d.company.nunique(), "companies")
out = {}

# ---- concentration
cs = d.company.value_counts()
share = cs / cs.sum()
out["top5_share"] = share.head(5).sum(); out["top10_share"] = share.head(10).sum(); out["hhi"] = (share ** 2).sum() * 10000
cs.head(15).rename("records").to_csv("data/top_companies.csv")
print("top5 share", round(out["top5_share"], 3), "top10", round(out["top10_share"], 3), "HHI", round(out["hhi"]))
print(cs.head(8))

# ---- form, category, reason, status
form = d.dosage_form.fillna("Unknown").where(d.dosage_form.fillna("").isin(d.dosage_form.value_counts().head(6).index), "Other")
form.value_counts().to_csv("data/by_dosage_form.csv")
cat = d.explode("therapeutic_category").therapeutic_category.value_counts(); cat.to_csv("data/by_therapeutic_category.csv")
reason = d.shortage_reason.fillna("(not stated)").value_counts(); reason.to_csv("data/by_stated_reason.csv")
print(form.value_counts().to_dict()); print(reason.to_dict())
print(pd.crosstab(d.status, d.availability))
inj = d.dosage_form.fillna("").eq("Injection")
print("share of records injection", inj.mean().round(3))

# ---- product level: how many companies per product are listed, and how much of the product is unavailable
prod = d.groupby("generic_name").agg(records=("package_ndc", "count"), companies=("company", "nunique"),
                                     unavailable=("availability", lambda s: (s == "Unavailable").mean()),
                                     first_posted=("posted", "min")).sort_values("records", ascending=False)
prod.to_csv("data/products.csv")
print("products with 1 company listed", (prod.companies == 1).mean().round(3), "median records per product", prod.records.median())

# ---- Kaplan-Meier for time in shortage
today = pd.Timestamp("2026-11-26")
k = d[d.status.isin(["Current", "Resolved"])].copy()
k["event"] = (k.status == "Resolved").astype(int)
k["days"] = np.where(k.event == 1, (k.updated - k.posted).dt.days, (today - k.posted).dt.days)
k = k[k.days > 0]

def km(days, event):
    t = np.sort(np.unique(days[event == 1])); s = 1.0; out = [(0, 1.0)]; var = 0.0; res = []
    for ti in t:
        n = (days >= ti).sum(); e = ((days == ti) & (event == 1)).sum()
        s *= 1 - e / n; var += e / (n * (n - e)) if n > e else 0
        res.append((ti, s, s * np.sqrt(var)))
    return res

def logrank(d1, e1, d2, e2):
    t = np.sort(np.unique(np.r_[d1[e1 == 1], d2[e2 == 1]])); O = E = V = 0.0
    for ti in t:
        n1 = (d1 >= ti).sum(); n2 = (d2 >= ti).sum(); n = n1 + n2
        dd = ((d1 == ti) & (e1 == 1)).sum() + ((d2 == ti) & (e2 == 1)).sum()
        O += ((d1 == ti) & (e1 == 1)).sum(); E += dd * n1 / n
        if n > 1: V += dd * (n1 / n) * (1 - n1 / n) * (n - dd) / (n - 1)
    chi = (O - E) ** 2 / V
    from math import erfc, sqrt
    return chi, erfc(sqrt(chi / 2))

print("records in KM", len(k), "resolved", int(k.event.sum()), "median days currently listed", k[k.event == 0].days.median())
allkm = km(k.days.values, k.event.values)
rows = []
for name, mask in [("all", np.ones(len(k), bool)), ("injection", (k.dosage_form == "Injection").values), ("non-injection", (k.dosage_form != "Injection").values)]:
    kk = k[mask]; r = km(kk.days.values, kk.event.values)
    last = r[-1] if r else (0, 1, 0)
    below = [x for x in r if x[1] <= 0.5]
    rows.append(dict(group=name, n=len(kk), resolved=int(kk.event.sum()), median_days_to_resolution=(below[0][0] if below else "not reached"),
                     survival_at_5_years=round(([x[1] for x in r if x[0] <= 1826] or [1])[-1], 3)))
kmt = pd.DataFrame(rows); kmt.to_csv("data/km_summary.csv", index=False); print(kmt.to_string())
a, b = k[k.dosage_form == "Injection"], k[k.dosage_form != "Injection"]
chi, p = logrank(a.days.values, a.event.values, b.days.values, b.event.values); print("logrank injection vs other chi2", round(chi, 2), "p", p)
pd.DataFrame([dict(test="log-rank injection vs non-injection", chi2=round(chi, 2), p=p)]).to_csv("data/logrank.csv", index=False)

# ---- link to recalls: do companies with more recall events have more shortage listings?
rc = pd.DataFrame([json.loads(l) for l in open("data/raw_enforcement.jsonl")])
def norm(s): return re.sub(r"\s+", " ", re.sub(r"\b(INC|LLC|LTD|LIMITED|CORP|CORPORATION|CO|COMPANY|USA|US|PHARMACEUTICALS?|PHARMA|LABS?|LABORATORIES)\b", "", re.sub(r"[^\w ]", " ", s.upper()))).strip()
rc["company"] = rc.recalling_firm.map(norm)
rcs = rc.groupby("company").event_id.nunique().rename("recall_events")
j = pd.concat([cs.rename("shortage_records"), rcs], axis=1).dropna()
def rank(x): return pd.Series(x).rank().values
rho = np.corrcoef(rank(j.shortage_records), rank(j.recall_events))[0, 1]
rng = np.random.default_rng(0); perm = [np.corrcoef(rank(j.shortage_records), rank(rng.permutation(j.recall_events.values)))[0, 1] for _ in range(5000)]
pval = (np.sum(np.abs(perm) >= abs(rho)) + 1) / 5001
print("companies in both", len(j), "of", cs.size, "shortage companies; spearman", round(rho, 3), "perm p", round(pval, 4))
j.sort_values("shortage_records", ascending=False).to_csv("data/company_shortage_vs_recall.csv")
pd.DataFrame([dict(companies_matched=len(j), shortage_companies=int(cs.size), spearman=round(rho, 3), perm_p=round(pval, 4))]).to_csv("data/recall_link.csv", index=False)

# ---- figure
fig, ax = plt.subplots(1, 3, figsize=(16, 4.4))
top = cs.head(10)[::-1]; ax[0].barh(top.index.str.title(), top.values, color="#4d4d4d"); ax[0].set_title(f"Shortage records by company (top 5 hold {out['top5_share']*100:.0f}%)"); ax[0].tick_params(axis="y", labelsize=8)
rs = d.assign(form=form).groupby("form").agg(records=("status", "size"), resolved=("status", lambda x: (x == "Resolved").sum()), to_be_discontinued=("status", lambda x: (x == "To Be Discontinued").sum()))
rs["resolved_pct"] = (100 * rs.resolved / rs.records).round(1); rs["discontinued_pct"] = (100 * rs.to_be_discontinued / rs.records).round(1)
rs = rs.sort_values("records", ascending=False); rs.to_csv("data/status_by_dosage_form.csv"); print(rs)
ax[1].barh(rs.index[::-1], rs.resolved_pct[::-1], color="#2166ac", label="Resolved"); ax[1].barh(rs.index[::-1], rs.discontinued_pct[::-1], left=rs.resolved_pct[::-1], color="#d6604d", label="To be discontinued")
ax[1].set_xlabel("% of records"); ax[1].set_title("Status by dosage form"); ax[1].legend(fontsize=8); ax[1].tick_params(axis="y", labelsize=8)
yr = d.posted.dt.year.value_counts().sort_index(); ax[2].bar(yr.index, yr.values, color="#b2182b"); ax[2].set_title("Records by year first posted"); 
plt.tight_layout(); plt.savefig("figures/shortage_overview.png", dpi=100)
