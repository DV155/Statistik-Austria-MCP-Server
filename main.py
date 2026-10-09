from typing import Any
import re
import io
import json
import pandas as pd
from html import unescape

import httpx2
from mcp.server import MCPServer

mcp = MCPServer("statistik-austria")
DATA_BASE = "https://data.statistik.gv.at"
client = httpx2.AsyncClient(base_url=DATA_BASE, timeout=30, headers={"Accept-Language": "en"})
ROW_RE = re.compile(r'meta\.jsp\?dataset=([^"&]+)"[^>]*>([^<]+)</a></h4>\s*<p>([^<]*)</p>')

def norm(s: str) -> str: #helper function to convert german-specific letters to common latin alternatives
    s = s.lower()
    for a, b in (("ä","ae"),("ö","oe"),("ü","ue"),("ß","ss")):
          s = s.replace(a, b)
    return s 

def newest_year(title: str) -> str:
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
        dataset_id is the Statistik Austria dataset identifier (e.g. "OGD_vpi86_VPI_2020_1").
        """
        url = f"/data/{dataset_id}.json"
        try:
            resp = (await client.get(url))
            resp.raise_for_status()
            raw =  resp.json()
            dimension, measure = parse_att(raw["extras"]["attribute_description"])
            return {"dimension":dimension, "measure": measure}
        except Exception as e:
            return {"error": str(e)}

@mcp.tool()
async def fetch_dataset_csv(dataset_id: str) -> dict:
        """Fetch an OGD dataset's full data with coded values resolved to human-readable German labels.
        dataset_id is the Statistik Austria dataset identifier (e.g. "OGD_vpi86_VPI_2020_1").
        """
        url_json = f"/data/{dataset_id}.json"
        url_csv = f"/data/{dataset_id}.csv"
        resp = (await client.get(url_csv))
        try:
            resp.raise_for_status()
            raw_text = (await client.get(url_json)).json()
            dimension, measure = parse_att(raw_text["extras"]["attribute_description"])
            df = pd.read_csv(io.StringIO(resp.text), sep=";")
            for d in dimension:
                 code = d["code"]
                 midcsv = await client.get(f"/data/{dataset_id}_{code}.csv")
                 cdf = pd.read_csv(io.StringIO(midcsv.text), sep=";")
                 df[code] = df[code].map(dict(zip(cdf.iloc[:, 0], cdf.iloc[:, 1]))).fillna(df[code])
            df = df.rename(columns={c["code"]: c["label"] for c in dimension + measure})
            return {"rows": df.to_dict(orient="records")}
        except Exception as e:
            return {"error": str(e)}

@mcp.tool()
async def search_dataset(query: str = "", limit: int = 20) -> dict: #TODO: Bring back 'category: str = "" '
    """Search the OGD catalog by keyword. Every query word
  must appear in a result; word parts match too. An empty query returns recently updated datasets.
  Pass a result's "id" to fetch_dataset_json or fetch_dataset_csv.
    """
    try:
        resp = await client.get("/web/catalog.jsp")
        resp.raise_for_status()
        entries = parse_html(resp.text)
    except Exception as e:
        return {"error": str(e)}
    if not entries:
         return {"error": "Catalog page loaded but no datasets could be parsed; the page structure may have changed"}
    
    unique = {}
    for entry in entries:
        unique[entry["id"]] = entry
    entries = list(unique.values())
    limit = max(1, min(limit, 50))
    words = []
    for word in norm(query).split():
        if len(word) >= 3:
            words.append(word)

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
              else:
                   all_found = False
                   break
        if all_found:
            matches.append((score, entry))
    matches.sort(key=lambda pair: (pair[0], newest_year(pair[1]["title"])), reverse=True)

    results = []
    for score, entry in matches[:limit]:
        item = {"id": entry["id"], "title": entry["title"]}
        desc = entry["desc"]
        if desc and desc != entry["title"]:
            if len(desc) > 200:
                desc = desc[:200] + "..."
            item["desc"] = desc
        results.append(item)

    answer = {"query": query, "total_matches": len(matches), "returned": len(results), "results": results}     
    if not matches:
        answer["hint"] = "No matches. Try alternative keywords?"
    return answer



if __name__ == "__main__":
    mcp.run(transport="stdio")