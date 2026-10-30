from cachetools import TTLCache
import re
import io
import json
import pandas as pd
from html import unescape

import httpx2
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("statistik-austria")
DATA_BASE = "https://data.statistik.gv.at"
client = httpx2.AsyncClient(base_url=DATA_BASE, timeout=30, headers={"Accept-Language": "en"})
ROW_RE = re.compile(r'meta\.jsp\?dataset=([^"&]+)"[^>]*>([^<]+)</a></h4>\s*<p>([^<]*)</p>')
PAGE_BUDGET = 250000
ID_RE = re.compile(r"[A-Za-z0-9_.\-]+")
cache = TTLCache(maxsize=200000000, ttl=3600, getsizeof=lambda resp: len(resp.content))  #max 200 MB/1 hour

def norm(s: str) -> str: #helper function to convert german-specific letters to common latin alternatives
    s = s.lower()
    for a, b in (("ä","ae"),("ö","oe"),("ü","ue"),("ß","ss")):
          s = s.replace(a, b)
    return s 

def decode(raw: bytes) -> str: #helper function to avoid decoding errors
     try:
          return raw.decode("utf-8")
     except UnicodeDecodeError:
          return raw.decode("cp1252", errors="replace")

def newest_year(title: str) -> str: #helper function to get latest year in dataset
    years = re.findall(r"\d{4}", title)
    return max(years, default="")

def parse_att(att: str): #helper function to separate attribute descriptions into dimensions and measures
    dimension, measure = [], []
    for attribute in att.split(";"):
        parts = attribute.partition(":")
        code, label = parts[0], parts[2]
        if code.startswith("C-"):
               target = dimension
        else:
               target = measure
        target.append({"code": code, "label": label})
    return dimension, measure

def parse_html(html: str) -> list[dict]: #helper function to parse html for the dataset search tool
     return [{"id": m[0], "title": unescape(m[1]).strip(), "desc": unescape(m[2]).strip(),}
            for m in ROW_RE.findall(html)
     ]

def drop_agg(df: pd.DataFrame, column: str, cdf: pd.DataFrame) -> set[str]: #helper: codes in "column" that are totals of components also present in the data
    if "FK" not in cdf.columns:
        return set()
    present = set(df[column].dropna().unique())
    children = cdf.dropna(subset=["FK"])
    return set(children.loc[children["code"].astype(str).isin(present), "FK"].astype(str))

def unique_name(column: list[dict]) -> dict: #helper function which appends code of duplicate labels
    names, used = {}, set()
    for c in column:
        if c["code"] in names:
              continue
        label = c["label"].strip()
        if not label:
            label = c["code"]
        if label in used:
            label = f"{label} <{c['code']}>"
        used.add(label)
        names[c["code"]] = label
    return names

async def cache_get(url:str): #helper function that remembers successful responses
    if url in cache:
        return cache[url]
    resp = await client.get(url)
    if resp.status_code == 200 and len(resp.content) <= cache.maxsize:
        cache[url] = resp
    return resp

async def reason_unsupported(dataset_id: str) -> str | None: #helperthat gives reason why dataset has no standard CSV
    resp = await cache_get(f"/data/{dataset_id}.json")
    if resp.status_code != 200:
        return None
    resources = json.loads(decode(resp.content)).get("resources", [])
    main = next((r for r in resources if str(r.get("main_resource")).lower() == "true"), None)
    if main is None or main.get("url", "").endswith(f"{dataset_id}.csv"):
        return None
    kind = main.get("format", "").lower() or "an unknown format"
    if main.get("url", "").lower().endswith(".zip") and kind != "zip":
        kind += " inside a zip archive"
    return (f"This dataset's data is published as {kind}, not as a standard CSV table, "
            f"so this server can't load it. Details: https://data.statistik.gv.at/web/meta.jsp?dataset={dataset_id}")
         

@mcp.resource("ogd://catalog") 
def get_catalog() -> str:
     """Overview of the Statistik Austria OGD catalog: its categories with their
   anchors on the catalog page, and the URL pattern for dataset metadata pages.
   Use search_dataset to find specific datasets.
     """
     return json.dumps({"catalog": "https://data.statistik.gv.at/web/catalog.jsp", "categories": [{"name": "Latest data", "anchor": "#collapse_new"},
            {"name": "High-value datasets / HighValueDataset", "anchor": "#collapse_hvd"},
            {"name": "Economy and tourism", "anchor": "#collapse0"},
            {"name": "Education and science", "anchor": "#collapse1"},
            {"name": "Employment", "anchor": "#collapse2"},
            {"name": "Environment", "anchor": "#collapse3"},  
            {"name": "Finance", "anchor": "#collapse4"},
            {"name": "Geography and planning", "anchor": "#collapse5"},
            {"name": "Health", "anchor": "#collapse6"},
            {"name": "Population", "anchor": "#collapse7"}, 
            {"name": "Society", "anchor": "#collapse8"},
            {"name": "Transport", "anchor": "#collapse9"},  
            ], "metadata_url_pattern": "https://data.statistik.gv.at/web/meta.jsp?dataset={dataset_id}"},
            ensure_ascii=False, indent=2)

     

@mcp.tool()
async def fetch_dataset_json(dataset_id: str) -> dict:
        """Return the dimension and measure metadata for an OGD dataset. 
        dataset_id is the Statistik Austria dataset identifier (e.g. "OGD_vpi86_VPI_1986_1").
        """
        if not ID_RE.fullmatch(dataset_id):
            raise ToolError(f"Invalid dataset_id {dataset_id!r}; use an id from search_dataset.")
        url = f"/data/{dataset_id}.json"
        try:
            resp = (await cache_get(url))
            resp.raise_for_status()
            raw =  json.loads(decode(resp.content)) 
            dimension, measure = parse_att(raw["extras"]["attribute_description"])
            if not dimension:
                reason = await reason_unsupported(dataset_id)
                if reason:
                    raise ToolError(reason)
            return {"dimension":dimension, "measure": measure}
        except (httpx2.HTTPError, ValueError, KeyError) as e:
            raise ToolError(f"Could not load metadata for {dataset_id}: {type(e).__name__}: {e}") from e

@mcp.tool()
async def fetch_dataset_csv(dataset_id: str, offset: int = 0, limit: int = 1000, filters: dict[str, list[str]] | None = None) -> dict: #TODO: Fix tool breaking on zip (BINNENWAND?)
        """Fetch an OGD dataset's data with codes resolved to German labels, formatted "label <code>".
        dataset_id is the Statistik Austria dataset identifier (e.g. "OGD_vpi86_VPI_1986_1").
        "aggregate" names the dimensions in which a row is a total of other rows; never sum it with them.
        Empty "aggregate" does not guarantee rows can be summed (overlapping groupings exist, e.g. VPI).
        Dimensions in "unlabeled_dimensions" have raw codes and no aggregate information.
        filters: {dimension code: [value codes]} keeps matching rows, e.g. {"C-A10-0": ["A10-2024"]}; values are the <code> parts.
        Pages: at most `limit` rows (max 5000, fewer if rows are large); if "truncated", continue at offset + returned
        with the same filters.
        """
        if not ID_RE.fullmatch(dataset_id):
            raise ToolError(f"Invalid dataset_id {dataset_id!r}; use an id from search_dataset.")
        url_json = f"/data/{dataset_id}.json"
        url_csv = f"/data/{dataset_id}.csv"
        try:
            resp = (await cache_get(url_csv))
            if resp.status_code == 404:
                reason = await reason_unsupported(dataset_id)
                raise ToolError(reason or f"No data file for {dataset_id!r}; check the id with search_dataset.")
            resp.raise_for_status()
            resp_json = await cache_get(url_json)
            resp_json.raise_for_status()
            raw_text = json.loads(decode(resp_json.content))
            dimension, measure = parse_att(raw_text["extras"]["attribute_description"])
            names = unique_name(dimension + measure)
            df = pd.read_csv(io.StringIO(decode(resp.content)), sep=";", decimal = ",", dtype={d["code"]: str for d in dimension}, keep_default_na=False, na_values=[""])
            if df.empty:
                return {"total_rows": 0, "rows": [], "note": "The dataset file contains no data rows."}
            flags = {}
            labels = {}
            unlabeled = []
            for d in dimension:
                code = d["code"]
                midcsv = await cache_get(f"/data/{dataset_id}_{code}.csv")
                if midcsv.status_code == 404:
                    unlabeled.append({"dimension": names[code], "reason": "no classification file"})
                    continue
                midcsv.raise_for_status()
                try:
                    cdf = pd.read_csv(io.StringIO(decode(midcsv.content)), sep=";", dtype=str, keep_default_na=False, na_values=[""])
                    agg = df[code].isin(drop_agg(df, code, cdf))
                    lab = {}
                    for c, n in zip(cdf.iloc[:, 0], cdf.iloc[:, 1]):
                        if isinstance(n, str) and n.strip():
                            lab[c] = " ".join(n.split())
                        else:
                            lab[c] = c
                except Exception as e:
                    unlabeled.append({"dimension": names[code], "reason": f"{type(e).__name__}: {e}"})
                    continue
                flags[names[code]] = agg
                labels[code] = lab
            flag_df = pd.DataFrame(flags, index=df.index)
            if filters:
                for dim, wanted in filters.items():
                    if dim not in df.columns or not dim.startswith("C-"):
                        raise ToolError(f"Unknown dimension {dim!r}; use a dimension code from fetch_dataset_json.")
                    matching = df[dim].isin(wanted)
                    if not matching.any():
                        raise ToolError(f"No rows where {dim} is one of {wanted}; filters take the <code> part of values.")
                    df = df[matching]
                    flag_df = flag_df[matching]
            limit = max(1, min(limit, 5000))
            offset = max(0, offset)
            page = df.iloc[offset:offset + limit].copy()
            for code, lab in labels.items():
                page[code] = page[code].map(lab).fillna(page[code]) + " <" + page[code] + ">"
            page["aggregate"] = ""
            for name in flag_df.columns:
                is_total = flag_df[name].iloc[offset:offset + limit].to_numpy()
                page.loc[is_total, "aggregate"] += "; " + name
            page["aggregate"] = page["aggregate"].str.removeprefix("; ")
            rows = page.rename(columns=names).to_dict(orient="records")
            for row in rows:
                for key, value in row.items():
                    if pd.isna(value):
                        row[key] = None
            size = len(json.dumps(rows, ensure_ascii=False).encode())
            if size > PAGE_BUDGET:
                rows = rows[:max(1, int(len(rows) * PAGE_BUDGET / size))]
            return {"total_rows": len(df),
                    "aggregate_rows": int(flag_df.any(axis=1).sum()),
                    "offset": offset,
                    "returned": len(rows),
                    "truncated": offset + len(rows) < len(df),
                    "unlabeled_dimensions": unlabeled,
                    "rows": rows}
        except httpx2.TransportError as e:
            raise ToolError(f"Statistik Austria's server did not respond ({type(e).__name__}); try again in a moment.") from e
        except (httpx2.HTTPStatusError, ValueError, KeyError) as e:
            raise ToolError(f"Could not load {dataset_id}: {type(e).__name__}: {e}") from e

@mcp.tool()
async def search_dataset(query: str = "", limit: int = 20, offset: int = 0, match_all: bool = True) -> dict: #TODO: Bring back 'category: str = "" '
    """Search the OGD catalog by keyword. By default every query word of 3+ characters
  must appear in a result; word parts match too. An empty query returns recently updated datasets.
  Titles are in German, so search with German keywords (e.g. "Bevölkerung", not "population").
  Pass a result's "id" to fetch_dataset_json or fetch_dataset_csv. Some datasets aren't standard CSV tables; fetch_dataset_csv then explains why it can't load them.
  Pages: at most `limit` results (max 50); if "truncated", continue at offset + returned.
  Setting match_all=False returns datasets containing any query word, best matches first.
  
    """
    try:
        resp = await cache_get("/web/catalog.jsp")
        resp.raise_for_status()
        entries = parse_html(resp.text)
    except httpx2.HTTPError as e:
        raise ToolError(f"Could not load the catalog page: {e}") from e
    if not entries:
        raise ToolError("Catalog page loaded but no datasets could be parsed; the page structure may have changed")
    
    unique = {}
    for entry in entries:
        unique[entry["id"]] = entry
    entries = list(unique.values())
    limit = max(1, min(limit, 50))
    offset = max(0, offset)
    words = []
    for word in norm(query).split():
        if len(word) >= 3:
            words.append(word)
    if query.strip() and not words:
        return {"query": query, "total_matches": 0, "returned": 0, "results": [],
                "hint": "All query words are shorter than 3 characters; use longer keywords."}

    matches = []
    for entry in entries:
        title = norm(entry["title"])
        rest = norm(entry["desc"] + " " + entry["id"])
        score = 0
        all_found = True
        for word in words:
              if word in title:
                   score += 3
              elif word in rest:
                   score += 1
              elif match_all:
                   all_found = False
                   break
        if all_found and (score > 0 or not words):
            matches.append((score, entry))
    if words:
        matches.sort(key=lambda pair: (pair[0], newest_year(pair[1]["title"])), reverse=True)

    results = []
    for score, entry in matches[offset:offset + limit]:
        item = {"id": entry["id"], "title": entry["title"]}
        desc = entry["desc"]
        if desc and desc != entry["title"]:
            if len(desc) > 200:
                desc = desc[:200] + "..."
            item["desc"] = desc
        results.append(item)

    answer = {"query": query, "total_matches": len(matches), "returned": len(results), "truncated": offset + len(results) < len(matches), "results": results}     
    if not match_all:
        answer["hint"] = "Titles don't list every breakdown (e.g. by region); check candidates' dimensions with fetch_dataset_json before concluding data doesn't exist."
    if not matches:
        answer["hint"] = "No matches. Try alternative keywords?"
    return answer

def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()