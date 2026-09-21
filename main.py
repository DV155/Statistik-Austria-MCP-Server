from typing import Any
import re
import io
import json
import pandas as pd

import httpx2
from mcp.server import MCPServer

mcp = MCPServer("statistik-austria")
client = httpx2.AsyncClient(timeout=30)
DATA_BASE = "https://data.statistik.gv.at"

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
     return [{"id": m[0], "title": m[1]}
            for m in re.findall(r'meta\.jsp\?dataset=([^"]+)"[^>]*>([^<]+)</a></h4>\s*<p>([^<]+)</p>')]

@mcp.resource("ogd://catalog") 
def get_catalog() -> str:
     """Complete catalog of Statistik Austria datasets, separated into distinct categories. 
     Each catalog entry identifies a dataset and provides its dataset ID and metadata URL.
     All datasets available as csv or json. 
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
        url = f"{DATA_BASE}/data/{dataset_id}.json"
        resp = (await client.get(url))
        try:
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
        url_json = f"{DATA_BASE}/data/{dataset_id}.json"
        url_csv = f"{DATA_BASE}/data/{dataset_id}.csv"
        resp = (await client.get(url_csv))
        try:
            resp.raise_for_status()
            raw_text = (await client.get(url_json)).json()
            dimension, measure = parse_att(raw_text["extras"]["attribute_description"])
            df = pd.read_csv(io.StringIO(resp.text), sep=";")
            for d in dimension:
                 code = d["code"]
                 midcsv = await client.get(f"{DATA_BASE}/data/{dataset_id}_{code}.csv")
                 cdf = pd.read_csv(io.StringIO(midcsv.text), sep=";")
                 df[code] = df[code].map(dict(zip(cdf.iloc[:, 0], cdf.iloc[:, 1]))).fillna(df[code])
            df = df.rename(columns={c["code"]: c["label"] for c in dimension + measure})
            return {"rows": df.to_dict(orient="records")}
        except Exception as e:
            return {"error": str(e)}

@mcp.tool()
async def search_dataset(query: str = "", category: str = "") -> dict: 
    resp = await client.get("/web/catalog.jsp")
    try:
        resp.raise_for_status()
    except Exception as e:
        return {"error": str(e)}
     



if __name__ == "__main__":
    mcp.run(transport="stdio")